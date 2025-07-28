import asyncio
import base64
import json
from nonebot import get_plugin_config, on_command, require, get_driver
from nonebot.plugin import PluginMetadata, inherit_supported_adapters
from nonebot.log import logger
from nonebot.adapters.onebot.v11.event import MessageEvent, GroupMessageEvent
from nonebot.exception import FinishedException
import datetime

require("nonebot_plugin_saa")
require("nonebot_plugin_orm")
require("nonebot_plugin_apscheduler")

from .config import Config
from .deltaapi import DeltaApi
from .db import UserDataDatabase
from .model import UserData, SafehouseRecord
from .util import trans_num_easy_for_read, get_map_name, seconds_to_duration
from . import migrations

from nonebot_plugin_saa import Image, Text, TargetQQGroup, Mention
from nonebot_plugin_orm import async_scoped_session, get_session
from nonebot_plugin_apscheduler import scheduler


driver = get_driver()


__plugin_meta__ = PluginMetadata(
    name="三角洲助手",
    description="主要有扫码登录、查看三角洲战绩等功能",
    usage="使用\"三角洲登录\"命令进行登录",

    type="application",
    # 发布必填，当前有效类型有：`library`（为其他插件编写提供功能），`application`（向机器人用户提供功能）。

    homepage="https://github.com/BraveCowardp/nonebot-plugin-delta-helper",
    # 发布必填。

    config=Config,
    # 插件配置项类，如无需配置可不填写。

    supported_adapters=inherit_supported_adapters("nonebot_plugin_saa"),
    # 支持的适配器集合，其中 `~` 在此处代表前缀 `nonebot.adapters.`，其余适配器亦按此格式填写。
    # 若插件可以保证兼容所有适配器（即仅使用基本适配器功能）可不填写，否则应该列出插件支持的适配器。
    extra={
        "orm_version_location": migrations,
    },
)

# config = get_plugin_config(Config)

bind_delta_help = on_command("三角洲帮助")
bind_delta_login = on_command("三角洲登录")
bind_delta_player_info = on_command("三角洲信息")
bind_delta_password = on_command("三角洲密码")
bind_delta_safehouse = on_command("三角洲特勤处")
bind_delta_safehouse_remind_open = on_command("三角洲特勤处提醒开启")
bind_delta_safehouse_remind_close = on_command("三角洲特勤处提醒关闭")

@bind_delta_help.handle()
async def _(event: MessageEvent, session: async_scoped_session):
    await bind_delta_help.finish("""三角洲助手插件使用帮助：
1. 三角洲登录：登录三角洲账号，需要用摄像头扫码，登录后会自动播报百万撤离或百万战损战绩
2. 三角洲信息：查看三角洲基本信息
3. 三角洲密码：查看三角洲今日密码门密码
4. 三角洲特勤处：查看三角洲特勤处制造状态
5. 三角洲特勤处提醒开启：开启特勤处提醒功能
6. 三角洲特勤处提醒关闭：关闭特勤处提醒功能""")

interval = 120
BROADCAST_EXPIRED_MINUTES = 7
SAFEHOUSE_CHECK_INTERVAL = 600  # 特勤处检查间隔（秒）

def generate_record_id(record_data: dict) -> str:
    """生成战绩唯一标识"""
    # 使用时间戳作为唯一标识
    event_time = record_data.get('dtEventTime', '')
    return event_time

def format_record_message(record_data: dict, user_name: str) -> str|None:
    """格式化战绩播报消息"""
    try:
        # 解析时间
        event_time = record_data.get('dtEventTime', '')
        # 解析地图ID
        map_id = record_data.get('MapId', '')
        # 解析结果
        escape_fail_reason = record_data.get('EscapeFailReason', 0)
        # 解析时长（秒）
        duration_seconds = record_data.get('DurationS', 0)
        # 解析击杀数
        kill_count = record_data.get('KillCount', 0)
        # 解析收益
        final_price = record_data.get('FinalPrice', '0')
        # 解析纯利润
        flow_cal_gained_price = record_data.get('flowCalGainedPrice', 0)
        
        # 格式化时长
        minutes = duration_seconds // 60
        seconds = duration_seconds % 60
        duration_str = f"{minutes}分{seconds}秒"
        
        # 格式化结果
        if escape_fail_reason == 1:
            result_str = "撤离成功"
        else:
            result_str = "撤离失败"
        
        # 格式化收益
        try:
            price_int = int(final_price)
            price_str = trans_num_easy_for_read(price_int)
        except:
            price_str = final_price

        # 计算战损
        loss_int = int(final_price) - int(flow_cal_gained_price)
        loss_str = trans_num_easy_for_read(loss_int)

        # logger.debug(f"获取到玩家{user_name}的战绩：时间：{event_time}，地图：{get_map_name(map_id)}，结果：{result_str}，存活时长：{duration_str}，击杀干员：{kill_count}，带出：{price_str}，战损：{loss_str}")
        
        if price_int > 1000000:
            # 构建消息
            message = f"🎯 {user_name} 百万撤离！\n"
            message += f"⏰ 时间: {event_time}\n"
            message += f"🗺️ 地图: {get_map_name(map_id)}\n"
            message += f"📊 结果: {result_str}\n"
            message += f"⏱️ 存活时长: {duration_str}\n"
            message += f"💀 击杀干员: {kill_count}\n"
            message += f"💰 带出: {price_str}\n"
            message += f"💸 战损: {loss_str}"
        elif loss_int > 1000000:
            message = f"🎯 {user_name} 百万战损！\n"
            message += f"⏰ 时间: {event_time}\n"
            message += f"🗺️ 地图: {get_map_name(map_id)}\n"
            message += f"📊 结果: {result_str}\n"
            message += f"⏱️ 存活时长: {duration_str}\n"
            message += f"💀 击杀干员: {kill_count}\n"
            message += f"💰 带出: {price_str}\n"
            message += f"💸 战损: {loss_str}"
        else:
            return None

        
        return message
    except Exception as e:
        logger.exception(f"格式化战绩消息失败: {e}")
        return None

def is_record_within_time_limit(record_data: dict, max_age_minutes: int = BROADCAST_EXPIRED_MINUTES) -> bool:
    """检查战绩是否在时间限制内"""
    try:
        event_time_str = record_data.get('dtEventTime', '')
        if not event_time_str:
            return False
        
        # 解析时间字符串 "2025-07-20 20: 04: 29"
        # 注意时间格式中有空格，需要处理
        event_time_str = event_time_str.replace(' : ', ':')
        
        # 解析时间
        event_time = datetime.datetime.strptime(event_time_str, '%Y-%m-%d %H:%M:%S')
        current_time = datetime.datetime.now()
        
        # 计算时间差
        time_diff = current_time - event_time
        time_diff_minutes = time_diff.total_seconds() / 60
        
        return time_diff_minutes <= max_age_minutes
    except Exception as e:
        logger.error(f"检查战绩时间限制失败: {e}")
        return False

@bind_delta_safehouse_remind_open.handle()
async def _(event: MessageEvent, session: async_scoped_session):
    user_data_database = UserDataDatabase(session)
    user_data = await user_data_database.get_user_data(event.user_id)
    if not user_data:
        await bind_delta_safehouse_remind_open.finish("未绑定三角洲账号，请先用\"三角洲登录\"命令登录", reply_message=True)
    if user_data.if_remind_safehouse:
        await bind_delta_safehouse_remind_open.finish("特勤处提醒功能已开启", reply_message=True)
    user_data.if_remind_safehouse = True
    
    # 在commit之前获取qq_id，避免会话关闭后无法访问ORM对象属性
    qq_id = user_data.qq_id
    
    await user_data_database.update_user_data(user_data)
    await user_data_database.commit()
    scheduler.add_job(watch_safehouse, 'interval', seconds=SAFEHOUSE_CHECK_INTERVAL, id=f'delta_watch_safehouse_{qq_id}', next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=10), replace_existing=True, kwargs={'qq_id': qq_id}, max_instances=1)
    await bind_delta_safehouse_remind_open.finish("特勤处提醒功能已开启", reply_message=True)

@bind_delta_safehouse_remind_close.handle()
async def _(event: MessageEvent, session: async_scoped_session):
    user_data_database = UserDataDatabase(session)
    user_data = await user_data_database.get_user_data(event.user_id)
    if not user_data:
        await bind_delta_safehouse_remind_close.finish("未绑定三角洲账号，请先用\"三角洲登录\"命令登录", reply_message=True)
    if not user_data.if_remind_safehouse:
        await bind_delta_safehouse_remind_close.finish("特勤处提醒功能已关闭", reply_message=True)
    user_data.if_remind_safehouse = False
    
    # 在commit之前获取qq_id，避免会话关闭后无法访问ORM对象属性
    qq_id = user_data.qq_id
    
    await user_data_database.update_user_data(user_data)
    await user_data_database.commit()
    try:
        scheduler.remove_job(f'delta_watch_safehouse_{qq_id}')
    except Exception:
        # 任务可能不存在，忽略错误
        pass
    await bind_delta_safehouse_remind_close.finish("特勤处提醒功能已关闭", reply_message=True)

@bind_delta_login.handle()
async def _(event: MessageEvent, session: async_scoped_session):
    deltaapi = DeltaApi()
    res = await deltaapi.get_sig()
    if not res['status']:
        await bind_delta_login.finish(f"获取二维码失败：{res['message']}")

    iamgebase64 = res['message']['image']
    cookie = json.dumps(res['message']['cookie'])
    # logger.debug(f"cookie: {cookie},type: {type(cookie)}")
    qrSig = res['message']['qrSig']
    qrToken = res['message']['token']
    loginSig = res['message']['loginSig']

    img = base64.b64decode(iamgebase64)
    await (Text("请使用摄像头扫码") + Image(image=img)).send(reply=True)

    while True:
        res = await deltaapi.get_login_status(cookie, qrSig, qrToken, loginSig)
        if res['code'] == 0:
            cookie = json.dumps(res['data']['cookie'])
            # logger.debug(f"cookie: {cookie},type: {type(cookie)}")
            res = await deltaapi.get_access_token(cookie)
            if res['status']:
                access_token = res['data']['access_token']
                openid = res['data']['openid']
                qq_id = event.user_id
                if isinstance(event, GroupMessageEvent):
                    group_id = event.group_id
                else:
                    group_id = 0
                res = await deltaapi.bind(access_token=access_token, openid=openid)
                if not res['status']:
                    await bind_delta_login.finish(f"绑定失败：{res['message']}", reply_message=True)
                res = await deltaapi.get_player_info(access_token=access_token, openid=openid)
                if res['status']:
                    user_data = UserData(qq_id=qq_id, group_id=group_id, access_token=access_token, openid=openid)
                    user_data_database = UserDataDatabase(session)
                    if not await user_data_database.add_user_data(user_data):
                        await bind_delta_login.finish("保存用户数据失败，请稍查看日志", reply_message=True)
                    await user_data_database.commit()
                    user_name = res['data']['player']['charac_name']
                    scheduler.add_job(watch_record, 'interval', seconds=interval, id=f'delta_watch_record_{qq_id}', next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=10), replace_existing=True, kwargs={'user_name': user_name, 'qq_id': qq_id}, max_instances=1)
                    await bind_delta_login.finish(f"登录成功，角色名：{user_name}，现金：{trans_num_easy_for_read(res['data']['money'])}\n登录有效期60天，在小程序登录会使这里的登录状态失效", reply_message=True)
                    
                else:
                    await bind_delta_login.finish(f"查询角色信息失败：{res['message']}", reply_message=True)
            else:
                await bind_delta_login.finish(f"登录失败：{res['message']}", reply_message=True)

        elif res['code'] == -4 or res['code'] == -2 or res['code'] == -3:
            await bind_delta_login.finish(f"登录失败：{res['message']}", reply_message=True)
        
        await asyncio.sleep(0.5)

@bind_delta_player_info.handle()
async def _(event: MessageEvent, session: async_scoped_session):
    user_data_database = UserDataDatabase(session)
    user_data = await user_data_database.get_user_data(event.user_id)
    if not user_data:
        await bind_delta_player_info.finish("未绑定三角洲账号，请先用\"三角洲登录\"命令登录", reply_message=True)
    deltaapi = DeltaApi()
    res = await deltaapi.get_player_info(access_token=user_data.access_token, openid=user_data.openid)
    try:
        if res['status']:
            # logger.debug(f"角色信息：{res['data']}")
            await bind_delta_player_info.finish(f"角色名：{res['data']['player']['charac_name']}，现金：{trans_num_easy_for_read(res['data']['money'])}", reply_message=True)
        else:
            await bind_delta_player_info.finish(f"查询角色信息失败：{res['message']}", reply_message=True)
    except FinishedException:
        pass
    except Exception as e:
        logger.exception(f"查询角色信息失败")
        await bind_delta_player_info.finish(f"查询角色信息失败，可以需要重新登录\n详情请查看日志", reply_message=True)

@bind_delta_safehouse.handle()
async def _(event: MessageEvent, session: async_scoped_session):
    user_data_database = UserDataDatabase(session)
    user_data = await user_data_database.get_user_data(event.user_id)
    if not user_data:
        await bind_delta_safehouse.finish("未绑定三角洲账号，请先用\"三角洲登录\"命令登录", reply_message=True)
    deltaapi = DeltaApi()
    res = await deltaapi.get_safehousedevice_status(access_token=user_data.access_token, openid=user_data.openid)
    message = None
    if res['status']:
        place_data = res['data'].get('placeData', [])
        relate_map = res['data'].get('relateMap', {})
        for device in place_data:
            object_id = device.get('objectId', 0)
            left_time = device.get('leftTime', 0)
            push_time = device.get('pushTime', 0)
            place_name = device.get('placeName', '')
            
            if object_id > 0 and left_time > 0:
                # 正在生产
                object_name = relate_map.get(str(object_id), {}).get('objectName', f'物品{object_id}')
                if not message:
                    message = Text(f"{place_name}：{object_name}，剩余时间：{seconds_to_duration(left_time)}，完成时间：{datetime.datetime.fromtimestamp(push_time).strftime('%m-%d %H:%M:%S')}")
                else:
                    message += Text(f"\n{place_name}：{object_name}，剩余时间：{seconds_to_duration(left_time)}，完成时间：{datetime.datetime.fromtimestamp(push_time).strftime('%m-%d %H:%M:%S')}")
            else:
                # 闲置状态
                if not message:
                    message = Text(f"{place_name}：闲置中")
                else:
                    message += Text(f"\n{place_name}：闲置中")
        
        if message:
            await message.finish(reply=True)
        else:
            await bind_delta_safehouse.finish("特勤处状态获取成功，但没有数据", reply_message=True)
    else:
        await bind_delta_safehouse.finish(f"获取特勤处状态失败：{res['message']}", reply_message=True)

@bind_delta_password.handle()
async def _(event: MessageEvent, session: async_scoped_session):
    user_data_database = UserDataDatabase(session)
    user_data_list = await user_data_database.get_user_data_list()
    for user_data in user_data_list:
        deltaapi = DeltaApi()
        res = await deltaapi.get_password(user_data.access_token, user_data.openid)
        msgs = None
        if res['status'] and len(res['data']) > 0:
            for map in res['data']:
                if msgs is None:
                    msgs = Text(f"{map}：{res['data'][map]}")
                else:
                    msgs += Text(f"\n{map}：{res['data'][map]}")
            if msgs is not None:
                await msgs.finish()
    await bind_delta_password.finish("所有已绑定账号已过期，请先用\"三角洲登录\"命令登录至少一个账号", reply_message=True)

async def watch_record(user_name: str, qq_id: int):
    session = get_session()
    user_data_database = UserDataDatabase(session)
    user_data = await user_data_database.get_user_data(qq_id)
    if user_data:
        deltaapi = DeltaApi()
        # logger.debug(f"开始获取玩家{user_name}的战绩")
        res = await deltaapi.get_record(user_data.access_token, user_data.openid)
        if res['status']:
            # logger.debug(f"玩家{user_name}的战绩：{res['data']}")
            
            # 只处理gun模式战绩
            gun_records = res['data'].get('gun', [])
            if not gun_records:
                # logger.debug(f"玩家{user_name}没有gun模式战绩")
                await session.close()
                return
            
            # 获取最新战绩
            if gun_records:
                latest_record = gun_records[0]  # 第一条是最新的
                
                # 检查时间限制
                if not is_record_within_time_limit(latest_record):
                    logger.debug(f"最新战绩时间超过{BROADCAST_EXPIRED_MINUTES}分钟，跳过播报")
                    await session.close()
                    return
                
                # 生成战绩ID
                record_id = generate_record_id(latest_record)
                
                # 获取之前的最新战绩ID
                latest_record_data = await user_data_database.get_latest_record(qq_id)
                
                # 如果是新战绩（ID不同）
                if not latest_record_data or latest_record_data.latest_record_id != record_id:
                    # 格式化播报消息
                    message = format_record_message(latest_record, user_name)
                    
                    # 发送播报消息
                    try:
                        if message:
                            if user_data.group_id != 0:
                                await Text(message).send_to(target=TargetQQGroup(group_id=user_data.group_id))
                                logger.info(f"播报战绩成功: {user_name} - {record_id}")
                        
                            # 更新最新战绩记录
                            if await user_data_database.update_latest_record(qq_id, record_id):
                                await user_data_database.commit()
                                logger.info(f"更新最新战绩记录成功: {user_name} - {record_id}")
                            else:
                                logger.error(f"更新最新战绩记录失败: {record_id}")
                        
                    except Exception as e:
                        logger.error(f"发送播报消息失败: {e}")
                else:
                    logger.debug(f"没有新战绩需要播报: {user_name}")
            
    try:
        await session.close()
    except Exception as e:
        logger.error(f"关闭数据库会话失败: {e}")

async def send_safehouse_message(qq_id: int, object_name: str, left_time: int):
    await asyncio.sleep(left_time)
    session = get_session()
    user_data_database = UserDataDatabase(session)
    user_data = await user_data_database.get_user_data(qq_id)
    if not user_data:
        await session.close()
        return

    if user_data.if_remind_safehouse:
        message = Mention(user_id=str(qq_id)) + Text(f" {object_name}生产完成！")
        
        await message.send_to(target=TargetQQGroup(group_id=user_data.group_id))
        logger.info(f"特勤处生产完成提醒: {qq_id} - {object_name}")

    await session.close()

async def watch_safehouse(qq_id: int):
    """监控特勤处生产状态"""
    session = get_session()
    user_data_database = UserDataDatabase(session)
    user_data = await user_data_database.get_user_data(qq_id)
    if not user_data:
        await session.close()
        return
    
    try:
        deltaapi = DeltaApi()
        res = await deltaapi.get_safehousedevice_status(user_data.access_token, user_data.openid)
        
        if not res['status']:
            logger.error(f"获取特勤处状态失败: {res['message']}")
            await session.close()
            return
        
        place_data = res['data'].get('placeData', [])
        relate_map = res['data'].get('relateMap', {})
        
        # 获取当前用户的特勤处记录
        current_records = await user_data_database.get_safehouse_records(qq_id)
        current_device_ids = {record.device_id for record in current_records}
        
        # 处理每个设备的状态
        for device in place_data:
            device_id = device.get('Id', '')
            left_time = device.get('leftTime', 0)
            object_id = device.get('objectId', 0)
            place_name = device.get('placeName', '')
            
            # 如果设备正在生产且有剩余时间
            if left_time > 0 and object_id > 0:
                # 获取物品信息
                object_info = relate_map.get(str(object_id), {})
                object_name = object_info.get('objectName', f'物品{object_id}')
                
                # 创建或更新记录
                safehouse_record = SafehouseRecord(
                    qq_id=qq_id,
                    device_id=device_id,
                    object_id=object_id,
                    object_name=object_name,
                    place_name=place_name,
                    left_time=left_time,
                    push_time=device.get('pushTime', 0)
                )
                
                await user_data_database.update_safehouse_record(safehouse_record)
                current_device_ids.discard(device_id)
                
                # 剩余时间小于检查间隔加60s，启动发送提醒任务
                if left_time <= SAFEHOUSE_CHECK_INTERVAL + 60:
                    # 启动发送提醒任务
                    scheduler.add_job(send_safehouse_message, 'date', run_date=datetime.datetime.now(), id=f'delta_send_safehouse_message_{qq_id}_{device_id}', replace_existing=True, kwargs={'qq_id': qq_id, 'object_name': object_name, 'left_time': left_time}, max_instances=1)
                    
                    # 删除记录
                    await user_data_database.delete_safehouse_record(qq_id, device_id)
        
        # 删除已完成的记录（设备不再生产）
        for device_id in current_device_ids:
            await user_data_database.delete_safehouse_record(qq_id, device_id)
        
        await user_data_database.commit()
        
    except Exception as e:
        logger.exception(f"监控特勤处状态失败: {e}")
    finally:
        await session.close()

async def start_watch_record():
    session = get_session()
    user_data_database = UserDataDatabase(session)
    user_data_list = await user_data_database.get_user_data_list()
    for user_data in user_data_list:
        deltaapi = DeltaApi()
        try:
            # 提前获取所有需要的属性，避免在调度器中访问ORM对象
            qq_id = user_data.qq_id
            access_token = user_data.access_token
            openid = user_data.openid
            if_remind_safehouse = user_data.if_remind_safehouse
            
            res = await deltaapi.get_player_info(access_token=access_token, openid=openid)
            if res['status'] and 'charac_name' in res['data']['player']:
                user_name = res['data']['player']['charac_name']
                scheduler.add_job(watch_record, 'interval', seconds=interval, id=f'delta_watch_record_{qq_id}', next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=10), replace_existing=True, kwargs={'user_name': user_name, 'qq_id': qq_id}, max_instances=1)
                # 添加特勤处监控任务

                if if_remind_safehouse:
                    scheduler.add_job(watch_safehouse, 'interval', seconds=SAFEHOUSE_CHECK_INTERVAL, id=f'delta_watch_safehouse_{qq_id}', next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=10), replace_existing=True, kwargs={'qq_id': qq_id}, max_instances=1)

            else:
                continue
        except Exception as e:
            logger.exception(f"启动战绩监控失败")
            continue

    await session.close()

# 启动时初始化
@driver.on_startup
async def initialize_plugin():
    """插件初始化"""
    # 启动战绩监控
    await start_watch_record()
    logger.info("三角洲助手插件初始化完成")

import asyncio
import base64
import json
import urllib.parse
import httpx
from openai import AsyncOpenAI
from nonebot import get_plugin_config, on_command, require, get_driver
from nonebot.plugin import PluginMetadata, inherit_supported_adapters
from nonebot.log import logger
from nonebot.permission import SUPERUSER
from nonebot.adapters.onebot.v11 import Message
from nonebot.adapters.onebot.v11.event import MessageEvent, GroupMessageEvent
from nonebot.exception import FinishedException
from nonebot.params import CommandArg
import datetime

require("nonebot_plugin_saa")
require("nonebot_plugin_orm")
require("nonebot_plugin_apscheduler")
require("nonebot_plugin_limiter")

from .config import Config
from .deltaapi import DeltaApi
from .db import UserDataDatabase
from .model import UserData, SafehouseRecord
from .util import Util
from .render import get_renderer, close_renderer
from . import migrations

from nonebot_plugin_saa import Image, Text, TargetQQGroup, Mention, AggregatedMessageFactory
from nonebot_plugin_orm import async_scoped_session, get_session
from nonebot_plugin_apscheduler import scheduler
from nonebot_plugin_limiter import UserScope, Cooldown, GlobalScope, Increaser


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

config = get_plugin_config(Config)

bind_delta_help = on_command("三角洲帮助")
bind_delta_login = on_command("三角洲登录", aliases={"三角洲登陆"})
bind_delta_player_info = on_command("三角洲信息")
bind_delta_password = on_command("三角洲密码")
bind_delta_safehouse = on_command("三角洲特勤处")
bind_delta_safehouse_remind_open = on_command("三角洲特勤处提醒开启")
bind_delta_safehouse_remind_close = on_command("三角洲特勤处提醒关闭")
bind_delta_daily_report = on_command("三角洲日报")
bind_delta_weekly_report = on_command("三角洲周报")
bind_delta_ai_comment = on_command("三角洲AI锐评", aliases={"三角洲ai锐评"})

@bind_delta_help.handle()
async def _(event: MessageEvent, session: async_scoped_session):
    try:
        renderer = await get_renderer()
        img_data = await renderer.render_card('help.html', {})
        await Image(image=img_data).finish()
    except FinishedException:
        raise
    except Exception as e:
        logger.error(f"渲染帮助卡片失败: {e}")
        # 降级到文本模式
    
    await bind_delta_help.finish("""三角洲助手插件使用帮助：
1. 三角洲登录：登录三角洲账号，需要用摄像头扫码，登录后会自动播报百万撤离或百万战损战绩
2. 三角洲信息：查看三角洲基本信息
3. 三角洲密码：查看三角洲今日密码门密码
4. 三角洲特勤处：查看三角洲特勤处制造状态
5. 三角洲特勤处提醒开启：开启特勤处提醒功能
6. 三角洲特勤处提醒关闭：关闭特勤处提醒功能
7. 三角洲日报：查看三角洲日报
8. 三角洲周报：查看三角洲周报
9. 三角洲AI锐评：ai锐评玩家数据""")

interval = 120
BROADCAST_EXPIRED_MINUTES = 7
SAFEHOUSE_CHECK_INTERVAL = 600  # 特勤处检查间隔（秒）
ai_api_key = config.delta_helper_ai_api_key
ai_base_url = config.delta_helper_ai_base_url
ai_model = config.delta_helper_ai_model
ai_proxy = config.delta_helper_ai_proxy

def generate_record_id(record_data: dict) -> str:
    """生成战绩唯一标识"""
    # 使用时间戳作为唯一标识
    event_time = record_data.get('dtEventTime', '')
    return event_time

async def format_record_message(record_data: dict, user_name: str) -> bytes|str|None:
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
            price_str = Util.trans_num_easy_for_read(price_int)
        except:
            price_str = final_price

        # 计算战损
        loss_int = int(final_price) - int(flow_cal_gained_price)
        loss_str = Util.trans_num_easy_for_read(loss_int)

        # logger.debug(f"获取到玩家{user_name}的战绩：时间：{event_time}，地图：{get_map_name(map_id)}，结果：{result_str}，存活时长：{duration_str}，击杀干员：{kill_count}，带出：{price_str}，战损：{loss_str}")
        
        if price_int > 1000000:
            # 构建消息
            message = f"🎯 {user_name} 百万撤离！\n"
            message += f"⏰ 时间: {event_time}\n"
            message += f"🗺️ 地图: {Util.get_map_name(map_id)}\n"
            message += f"📊 结果: {result_str}\n"
            message += f"⏱️ 存活时长: {duration_str}\n"
            message += f"💀 击杀干员: {kill_count}\n"
            message += f"💰 带出: {price_str}\n"
            message += f"💸 战损: {loss_str}"
            try:
                renderer = await get_renderer()
                img_data = await renderer.render_battle_record({
                    'user_name': user_name,
                    'title': '百万撤离！',
                    'time': event_time,
                    'map_name': Util.get_map_name(map_id),
                    'result': result_str,
                    'duration': duration_str,
                    'kill_count': kill_count,
                    'price': price_str,
                    'loss': loss_str,
                    'is_gain': True,
                    'main_value': price_str
                })
                return img_data
            except Exception as e:
                logger.exception(f"渲染战绩卡片失败: {e}")
                # 降级到文本模式
            return message
        elif loss_int > 1000000:
            message = f"🎯 {user_name} 百万战损！\n"
            message += f"⏰ 时间: {event_time}\n"
            message += f"🗺️ 地图: {Util.get_map_name(map_id)}\n"
            message += f"📊 结果: {result_str}\n"
            message += f"⏱️ 存活时长: {duration_str}\n"
            message += f"💀 击杀干员: {kill_count}\n"
            message += f"💰 带出: {price_str}\n"
            message += f"💸 战损: {loss_str}"
            try:
                renderer = await get_renderer()
                img_data = await renderer.render_battle_record({
                    'user_name': user_name,
                    'title': '百万战损！',
                    'time': event_time,
                    'map_name': Util.get_map_name(map_id),
                    'result': result_str,
                    'duration': duration_str,
                    'kill_count': kill_count,
                    'price': price_str,
                    'loss': loss_str,
                    'is_gain': False,
                    'main_value': loss_str
                })
                return img_data
            except Exception as e:
                logger.exception(f"渲染战绩卡片失败: {e}")
                # 降级到文本模式
            return message
        else:
            return None

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
    logger.info(f"启动特勤处监控任务: {qq_id}")
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
                    try:
                        renderer = await get_renderer()
                        img_data = await renderer.render_login_success(user_name, Util.trans_num_easy_for_read(res['data']['money']))
                        await Image(image=img_data).finish(reply=True)
                    except FinishedException:
                        raise
                    except Exception as e:
                        logger.error(f"渲染登录成功卡片失败: {e}")
                        # 降级到文本模式
                    await bind_delta_login.finish(f"登录成功，角色名：{user_name}，现金：{Util.trans_num_easy_for_read(res['data']['money'])}\n登录有效期60天，在小程序登录会使这里的登录状态失效", reply_message=True)
                    
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
            user_name = res['data']['player']['charac_name']
            money = Util.trans_num_easy_for_read(res['data']['money'])
            
            try:
                renderer = await get_renderer()
                img_data = await renderer.render_player_info(user_name, money)
                await Image(image=img_data).finish(reply=True)
            except FinishedException:
                raise
            except Exception as e:
                logger.error(f"渲染玩家信息卡片失败: {e}")
                # 降级到文本模式
            
            await bind_delta_player_info.finish(f"角色名：{user_name}，现金：{money}", reply_message=True)
        else:
            await bind_delta_player_info.finish(f"查询角色信息失败：{res['message']}", reply_message=True)
    except FinishedException:
        raise
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
    
    if res['status']:
        place_data = res['data'].get('placeData', [])
        relate_map = res['data'].get('relateMap', {})
        devices = []
        
        for device in place_data:
            object_id = device.get('objectId', 0)
            left_time = device.get('leftTime', 0)
            push_time = device.get('pushTime', 0)
            place_name = device.get('placeName', '')
            
            if object_id > 0 and left_time > 0:
                # 正在生产
                object_name = relate_map.get(str(object_id), {}).get('objectName', f'物品{object_id}')
                # 计算进度百分比
                total_time = device.get('totalTime', 0)
                progress = 100 - (left_time / total_time * 100) if total_time > 0 else 0
                
                devices.append({
                    'place_name': place_name,
                    'status': 'producing',
                    'object_name': object_name,
                    'left_time': Util.seconds_to_duration(left_time),
                    'finish_time': datetime.datetime.fromtimestamp(push_time).strftime('%m-%d %H:%M:%S'),
                    'progress': progress
                })
            else:
                # 闲置状态
                devices.append({
                    'place_name': place_name,
                    'status': 'idle'
                })
        
        if devices:
            try:
                renderer = await get_renderer()
                img_data = await renderer.render_safehouse(devices)
                await Image(image=img_data).finish(reply=True)
            except FinishedException:
                raise
            except Exception as e:
                logger.error(f"渲染特勤处卡片失败: {e}")
                # 降级到文本模式
        
        # 文本模式
        message = None
        for device_data in devices:
            if device_data['status'] == 'producing':
                text = f"{device_data['place_name']}：{device_data['object_name']}，剩余时间：{device_data['left_time']}，完成时间：{device_data['finish_time']}"
            else:
                text = f"{device_data['place_name']}：闲置中"
                
            if not message:
                message = Text(text)
            else:
                message += Text(f"\n{text}")
        
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
        password_list = res['data'].get('list', [])
        if password_list:
            for password in password_list:
                if msgs is None:
                    msgs = Text(f"{password.get('mapName', '未知地图')}：{password.get('secret', '未知密码')}")
                else:
                    msgs += Text(f"\n{password.get('mapName', '未知地图')}：{password.get('secret', '未知密码')}")
            if msgs is not None:
                await msgs.finish()
    await bind_delta_password.finish("所有已绑定账号已过期，请先用\"三角洲登录\"命令登录至少一个账号", reply_message=True)

@bind_delta_daily_report.handle()
async def _(event: MessageEvent, session: async_scoped_session):
    user_data_database = UserDataDatabase(session)
    user_data = await user_data_database.get_user_data(event.user_id)
    if not user_data:
        await bind_delta_daily_report.finish("未绑定三角洲账号，请先用\"三角洲登录\"命令登录", reply_message=True)
    deltaapi = DeltaApi()
    res = await deltaapi.get_daily_report(user_data.access_token, user_data.openid)
    if res['status']:
        solDetail = res['data'].get('solDetail', None)
        if solDetail:
            recentGainDate = solDetail.get('recentGainDate', '未知')
            recentGain = solDetail.get('recentGain', 0)
            gain_str = f"{'-' if recentGain < 0 else ''}{Util.trans_num_easy_for_read(abs(recentGain))}"
            userCollectionTop = solDetail.get('userCollectionTop', None)
            if userCollectionTop:
                userCollectionList = userCollectionTop.get('list', None)
                if userCollectionList:
                    userCollectionListStr = ""
                    for item in userCollectionList:
                        objectID = item.get('objectID', 0)
                        res = await deltaapi.get_object_info(access_token=user_data.access_token, openid=user_data.openid, object_id=objectID)
                        if res['status']:
                            obj_list = res['data'].get('list', [])
                            if obj_list:
                                obj_name = obj_list[0].get('objectName', '未知藏品')
                                if userCollectionListStr == "":
                                    userCollectionListStr = obj_name
                                else:
                                    userCollectionListStr += f"、{obj_name}"
                        else:
                            userCollectionListStr += f"未知藏品：{objectID}\n"
                else:
                    userCollectionListStr = "未知"
            else:
                userCollectionListStr = "未知"
            try:
                renderer = await get_renderer()
                img_data = await renderer.render_daily_report(recentGainDate, recentGain, gain_str, userCollectionListStr)
                await Image(image=img_data).finish(reply=True)
            except FinishedException:
                raise
            except Exception as e:
                logger.error(f"渲染日报卡片失败: {e}")
                # 降级到文本模式
            await bind_delta_daily_report.finish(f"三角洲日报\n日报日期：{recentGainDate}\n收益：{gain_str}\n价值最高藏品：{userCollectionListStr}", reply_message=True)
        else:
            await bind_delta_daily_report.finish("获取三角洲日报失败，没有数据", reply_message=True)
    else:
        await bind_delta_daily_report.finish(f"获取三角洲日报失败：{res['message']}", reply_message=True)

@bind_delta_weekly_report.handle()
async def _(event: MessageEvent, session: async_scoped_session):
    user_data_database = UserDataDatabase(session)
    user_data = await user_data_database.get_user_data(event.user_id)
    if not user_data:
        await bind_delta_weekly_report.finish("未绑定三角洲账号，请先用\"三角洲登录\"命令登录", reply_message=True)
    access_token = user_data.access_token
    openid = user_data.openid
    await user_data_database.commit()
    deltaapi = DeltaApi()
    res = await deltaapi.get_player_info(access_token=access_token, openid=openid)
    if res['status'] and 'charac_name' in res['data']['player']:
        user_name = res['data']['player']['charac_name']
    else:
        await bind_delta_weekly_report.finish("获取角色信息失败，可能需要重新登录", reply_message=True)
    for i in range (1,3):
        statDate, statDate_str = Util.get_Sunday_date(i)
        res = await deltaapi.get_weekly_report(access_token=access_token, openid=openid, statDate=statDate)
        if res['status'] and res['data']:
            # 解析总带出
            Gained_Price = int(res['data'].get('Gained_Price', 0))
            Gained_Price_Str = Util.trans_num_easy_for_read(Gained_Price)

            # 解析总带入
            consume_Price = int(res['data'].get('consume_Price', 0))
            consume_Price_Str = Util.trans_num_easy_for_read(consume_Price)

            # 解析总利润
            profit = Gained_Price - consume_Price
            profit_str = f"{'-' if profit < 0 else ''}{Util.trans_num_easy_for_read(abs(profit))}"

            # 解析使用干员信息
            total_ArmedForceId_num = res['data'].get('total_ArmedForceId_num', '')
            total_ArmedForceId_num = total_ArmedForceId_num.replace("'", '"')
            total_ArmedForceId_num_list = list(map(json.loads, total_ArmedForceId_num.split('#')))
            total_ArmedForceId_num_list.sort(key=lambda x: x['inum'], reverse=True)

            # 解析资产变化
            Total_Price = res['data'].get('Total_Price', '')
            import re
            def extract_price(text: str) -> str:
                m = re.match(r'(\w+)-(\d+)-(\d+)', text)
                if m:
                    return m.group(3)
                return ""
            price_list = list(map(extract_price, Total_Price.split(',')))

            # 解析资产净增
            rise_Price = int(price_list[-1]) - int(price_list[0])
            rise_Price_Str = f"{'-' if rise_Price < 0 else ''}{Util.trans_num_easy_for_read(abs(rise_Price))}"

            # 解析总场次
            total_sol_num = res['data'].get('total_sol_num', '0')

            # 解析总击杀
            total_Kill_Player = res['data'].get('total_Kill_Player', '0')

            # 解析总死亡
            total_Death_Count = res['data'].get('total_Death_Count', '0')

            # 解析总在线时间
            total_Online_Time = res['data'].get('total_Online_Time', '0')
            total_Online_Time_str = Util.seconds_to_duration(total_Online_Time)

            # 解析撤离成功次数
            total_exacuation_num = res['data'].get('total_exacuation_num', '0')

            # 解析百万撤离次数
            GainedPrice_overmillion_num = res['data'].get('GainedPrice_overmillion_num', '0')

            # 解析游玩地图信息
            total_mapid_num = res['data'].get('total_mapid_num', '')
            total_mapid_num = total_mapid_num.replace("'", '"')
            total_mapid_num_list = list(map(json.loads, total_mapid_num.split('#')))
            total_mapid_num_list.sort(key=lambda x: x['inum'], reverse=True)

            res = await deltaapi.get_weekly_friend_report(access_token=access_token, openid=openid, statDate=statDate)

            friend_list = []
            if res['status']:
                friends_sol_record = res['data'].get('friends_sol_record', [])
                if friends_sol_record:
                    for friend in friends_sol_record:
                        friend_dict = {}
                        Friend_is_Escape1_num = friend.get('Friend_is_Escape1_num', 0)
                        Friend_is_Escape2_num = friend.get('Friend_is_Escape2_num', 0)
                        if Friend_is_Escape1_num + Friend_is_Escape2_num <= 0:
                            continue

                        friend_openid = friend.get('friend_openid', '')
                        res = await deltaapi.get_user_info(access_token=access_token, openid=openid, user_openid=friend_openid)
                        if res['status']:
                            charac_name = res['data'].get('charac_name', '')
                            charac_name = urllib.parse.unquote(charac_name) if charac_name else "未知好友"
                            Friend_Escape1_consume_Price = friend.get('Friend_Escape1_consume_Price', 0)
                            Friend_Escape2_consume_Price = friend.get('Friend_Escape2_consume_Price', 0)
                            Friend_Sum_Escape1_Gained_Price = friend.get('Friend_Sum_Escape1_Gained_Price', 0)
                            Friend_Sum_Escape2_Gained_Price = friend.get('Friend_Sum_Escape2_Gained_Price', 0)
                            Friend_is_Escape1_num = friend.get('Friend_is_Escape1_num', 0)
                            Friend_is_Escape2_num = friend.get('Friend_is_Escape2_num', 0)
                            Friend_total_sol_KillPlayer = friend.get('Friend_total_sol_KillPlayer', 0)
                            Friend_total_sol_DeathCount = friend.get('Friend_total_sol_DeathCount', 0)
                            Friend_total_sol_num = friend.get('Friend_total_sol_num', 0)

                            friend_dict['charac_name'] = charac_name
                            friend_dict['sol_num'] = Friend_total_sol_num
                            friend_dict['kill_num'] = Friend_total_sol_KillPlayer
                            friend_dict['death_num'] = Friend_total_sol_DeathCount
                            friend_dict['escape_num'] =  Friend_is_Escape1_num
                            friend_dict['fail_num'] = Friend_is_Escape2_num
                            friend_dict['gained_str'] = Util.trans_num_easy_for_read(Friend_Sum_Escape1_Gained_Price + Friend_Sum_Escape2_Gained_Price)
                            friend_dict['consume_str'] = Util.trans_num_easy_for_read(Friend_Escape1_consume_Price + Friend_Escape2_consume_Price)
                            profit = Friend_Sum_Escape1_Gained_Price + Friend_Sum_Escape2_Gained_Price - Friend_Escape1_consume_Price - Friend_Escape2_consume_Price
                            friend_dict['profit_str'] = f"{'-' if profit < 0 else ''}{Util.trans_num_easy_for_read(abs(profit))}"
                            friend_list.append(friend_dict)
                    friend_list.sort(key=lambda x: x['sol_num'], reverse=True)
            msgs = []
            message = Text(f"【{user_name}烽火周报 - 日期：{statDate_str}】")
            msgs.append(message)
            message = Text(f"--- 基本信息 ---\n")
            message += Text(f"总览：{total_sol_num}场 | {total_exacuation_num}成功撤离 | {GainedPrice_overmillion_num}百万撤离\n")
            message += Text(f"KD： {total_Kill_Player}杀/{total_Death_Count}死\n")
            message += Text(f"在线时间：{total_Online_Time_str}\n")
            message += Text(f"总带出：{Gained_Price_Str} | 总带入：{consume_Price_Str}\n")
            message += Text(f"资产变化：{Util.trans_num_easy_for_read(price_list[0])} -> {Util.trans_num_easy_for_read(price_list[-1])} | 资产净增：{rise_Price_Str}\n")
            msgs.append(message)
            message = Text(f"--- 干员使用情况 ---")
            for armed_force in total_ArmedForceId_num_list:
                armed_force_name = Util.get_armed_force_name(armed_force.get('ArmedForceId', 0))
                armed_force_num = armed_force.get('inum', 0)
                message += Text(f"\n{armed_force_name}：{armed_force_num}场")
            msgs.append(message)
            message = Text(f"--- 地图游玩情况 ---")
            for map_info in total_mapid_num_list:
                map_name = Util.get_map_name(map_info.get('MapId', 0))
                map_num = map_info.get('inum', 0)
                message += Text(f"\n{map_name}：{map_num}场")
            msgs.append(message)
            message = Text(f"--- 队友协作情况 ---\n注：KD为好友KD，带出和带入为本人的数据")
            for friend in friend_list:
                message += Text(f"\n[{friend['charac_name']}]")
                message += Text(f"\n  总览：{friend['sol_num']}场 | {friend['escape_num']}撤离/{friend['fail_num']}失败 | {friend['kill_num']}杀/{friend['death_num']}死")
                message += Text(f"\n  带出：{friend['gained_str']} | 战损：{friend['consume_str']} | 利润：{friend['profit_str']}")
            msgs.append(message)
            try:
                renderer = await get_renderer()
                img_data = await renderer.render_weekly_report(
                    user_name, statDate_str, Gained_Price_Str, consume_Price_Str, rise_Price_Str, profit_str,
                    total_ArmedForceId_num_list, total_mapid_num_list, friend_list,
                    profit, rise_Price,
                    total_sol_num, total_Online_Time_str, total_Kill_Player,
                    total_Death_Count, total_exacuation_num, GainedPrice_overmillion_num, price_list)
                await Image(image=img_data).finish()
            except FinishedException:
                raise
            except Exception as e:
                logger.error(f"渲染周报卡片失败: {e}")
                # 降级到文本模式
            await AggregatedMessageFactory(msgs).finish()
        else:
            continue
    
    await bind_delta_weekly_report.finish("获取三角洲周报失败，可能需要重新登录或上周对局次数过少", reply_message=True)

@bind_delta_ai_comment.handle(parameterless=[
    Cooldown(
        UserScope(
            permission=SUPERUSER
        ), 
        3600,
        limit = 1,
        reject = "ai锐评功能对单个用户冷却时间60分钟，请稍后再试",
        set_increaser = True
    ),
    Cooldown(
        GlobalScope(), 
        60,
        limit = 4,
        reject = "ai锐评功能每分钟最多触发4次，请稍后再试",
        set_increaser = True
    )
])
async def _(event: MessageEvent, session: async_scoped_session, increaser: Increaser):
    user_data_database = UserDataDatabase(session)
    user_data = await user_data_database.get_user_data(event.user_id)
    if user_data:
        access_token = user_data.access_token
        openid = user_data.openid
        await user_data_database.commit()
    else:
        await user_data_database.commit()
        await bind_delta_ai_comment.finish("未绑定三角洲账号，请先用\"三角洲登录\"命令登录", reply_message=True)
   
    deltaapi = DeltaApi()
    res = await deltaapi.get_person_center_info(access_token=access_token, openid=openid)
    if not res['status']:
        await bind_delta_ai_comment.finish("获取角色信息失败，可能需要重新登录", reply_message=True)

    person_center_info = res['data']
    profitLossRatio = int(person_center_info.get('profitLossRatio', '0'))//100
    highKillDeathRatio = f"{(int(person_center_info.get('highKillDeathRatio', '0'))/100):.2f}"
    lowKillDeathRatio = f"{(int(person_center_info.get('lowKillDeathRatio', '0'))/100):.2f}"
    medKillDeathRatio = f"{(int(person_center_info.get('medKillDeathRatio', '0'))/100):.2f}"
    totalFight = person_center_info.get('totalFight', '0')
    totalEscape = person_center_info.get('totalEscape', '0')
    totalGainedPrice = person_center_info.get('totalGainedPrice', '0')
    totalConsumePrice = Util.seconds_to_duration(person_center_info.get('totalConsumePrice', '0'))
    totalKill = person_center_info.get('totalKill', '0')

    for i in range (1,3):
        statDate, statDate_str = Util.get_Sunday_date(i)
        res = await deltaapi.get_weekly_report(access_token=access_token, openid=openid, statDate=statDate)
        if res['status'] and res['data']:
            # 解析总带出
            Gained_Price = int(res['data'].get('Gained_Price', 0))

            # 解析资产净增
            rise_Price = int(res['data'].get('rise_Price', 0))

            # 解析资产变化
            Total_Price = res['data'].get('Total_Price', '')
            import re
            def extract_price(text: str) -> str:
                m = re.match(r'(\w+)-(\d+)-(\d+)', text)
                if m:
                    return m.group(3)
                return ""
            price_list = list(map(extract_price, Total_Price.split(',')))

            # 解析总场次
            total_sol_num = res['data'].get('total_sol_num', '0')

            # 解析总击杀
            total_Kill_Player = res['data'].get('total_Kill_Player', '0')

            # 解析总死亡
            total_Death_Count = res['data'].get('total_Death_Count', '0')

            # 解析总在线时间
            total_Online_Time = res['data'].get('total_Online_Time', '0')
            total_Online_Time_str = Util.seconds_to_duration(total_Online_Time)

            # 解析撤离成功次数
            total_exacuation_num = res['data'].get('total_exacuation_num', '0')

            # 解析百万撤离次数
            GainedPrice_overmillion_num = res['data'].get('GainedPrice_overmillion_num', '0')
        else:
            continue

        proxy = httpx.Proxy(ai_proxy)
        httpx_client = httpx.AsyncClient(proxies=proxy)
        client = AsyncOpenAI(
            api_key=ai_api_key,
            base_url=ai_base_url,
            http_client=httpx_client
        )

        response = await client.chat.completions.create(
        model="gemini-2.5-pro",
        messages=[
            {"role": "system", "content": "你是一个AI助手。"},
            {
                "role": "user",
                "content": "三角洲行动是一个类塔科夫的搜打撤游戏，这个游戏中的货币叫哈夫币。这个游戏地图分为常规、机密、绝密三个难度，常规没有准入门槛，很多玩家会选择什么都不带进去跑刀，机密需要一定价值的装备才允许进入，地图爆率也更高，当然敌人的装备也是更强大，绝密比机密更高一个等级门槛也更高敌人也更强，因为常规图死亡惩罚较少，所以很多人并不追求杀人或保命玩的比较随意，机密和绝密图因为玩家会携带高价值的装备所以会认真战斗并尽可能保命撤离，所以机密和绝密的KD会比常规图的KD更有含金量（也就是说如果一个人机密和绝密KD高而常规KD低说明这个人在常规图就没想杀人随便玩）。哈夫币几乎仅能通过搜索物资或者杀人舔装备获得，我接下来会向你输入一个玩家的游戏数据，你需要锐评一下这个玩家的数据，先来一句话简评，再详细锐评。因为只有锐评才会被展示，所以不要透露任何有先前对话的信息（也就是我在和你说的这段内容）语言尽量自然并且辛辣。不要有“一句话简评”或“详细锐评”等字眼，只要分段就行。"
            },
            {
                "role": "assistant",
                "content": "好的，请把这个玩家的游戏数据发给我，我已经准备好对他进行一番“友好”的点评了。"
            },
            {
                "role": "user",
                "content": f"这个玩家的生涯数据：赚损比（每死一次可以赚多少哈夫币）是{profitLossRatio}，绝密行动kda是{highKillDeathRatio}，机密行动kda是{medKillDeathRatio}，常规行动kda是{lowKillDeathRatio}，总场数是{totalFight}，总撤离数是{totalEscape}，总获取哈夫币是{totalGainedPrice}，总游戏时长是{totalConsumePrice}，总击杀是{totalKill}；这名玩家上周的数据：总场数是{total_sol_num}，总撤离数是{total_exacuation_num}，百万以上撤离次数是{GainedPrice_overmillion_num}，总击杀是{total_Kill_Player}，总死亡是{total_Death_Count}，总游戏时长是{total_Online_Time_str}，总带出是{Gained_Price}，资产是从{price_list[0]}到{price_list[-1]}，资产变化是{rise_Price}。"
            }
            ]
        )
        increaser.execute()
        if response.choices[0].message.content:
            msg = Mention(user_id=str(event.user_id)) + Text(' ') + Text(response.choices[0].message.content.strip())
            await msg.finish()
        else:
            logger.debug(f"AI锐评内容为空: {response.choices[0].message}")
            await bind_delta_ai_comment.finish("AI锐评内容为空，请查看日志", reply_message=True)


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
                    result = await format_record_message(latest_record, user_name)
                    
                    # 发送播报消息
                    try:
                        if result:
                            if user_data.group_id != 0:
                                if isinstance(result, bytes):
                                    # 有卡片数据
                                    img_data = result
                                    try:
                                        await Image(image=img_data).send_to(target=TargetQQGroup(group_id=user_data.group_id))
                                    except Exception as e:
                                        logger.error(f"发送战绩卡片失败: {e}")
                                else:
                                    # 只有文本消息
                                    message = result
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
        info = ""

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
                info += f"{place_name} - {object_name} - 剩余{left_time}秒\n"
                
                await user_data_database.update_safehouse_record(safehouse_record)
                current_device_ids.discard(device_id)
                
                # 剩余时间小于检查间隔加60s，启动发送提醒任务
                if left_time <= SAFEHOUSE_CHECK_INTERVAL + 60:
                    logger.info(f"{left_time}秒后启动发送提醒任务: {qq_id} - {device_id}")
                    # 启动发送提醒任务
                    scheduler.add_job(send_safehouse_message, 'date', run_date=datetime.datetime.now(), id=f'delta_send_safehouse_message_{qq_id}_{device_id}', replace_existing=True, kwargs={'qq_id': qq_id, 'object_name': object_name, 'left_time': left_time}, max_instances=1)
                    
                    # 删除记录
                    await user_data_database.delete_safehouse_record(qq_id, device_id)
        
        # 删除已完成的记录（设备不再生产）
        for device_id in current_device_ids:
            await user_data_database.delete_safehouse_record(qq_id, device_id)
        
        await user_data_database.commit()
        if info != "":
            logger.info(f"{qq_id}特勤处状态: {info}")
        else:
            logger.info(f"{qq_id}特勤处状态: 闲置中")
        
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
                    logger.info(f"启动特勤处监控任务: {qq_id}")
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
    await get_renderer()
    logger.info("三角洲助手插件初始化完成")

# 关闭时清理
@driver.on_shutdown
async def cleanup_plugin():
    """插件清理"""
    # 关闭渲染器
    await close_renderer()
    logger.info("三角洲助手插件清理完成")

import asyncio
import base64
import json
from typing import Union, Literal
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
from .model import UserData, SafehouseRecord, LatestRecord
from .util import Util
from .render import get_renderer, close_renderer
from . import migrations

from nonebot_plugin_saa import Image, Text, TargetQQGroup, Mention, AggregatedMessageFactory, enable_auto_select_bot
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
interval = 120
BROADCAST_EXPIRED_MINUTES = 7
SAFEHOUSE_CHECK_INTERVAL = 600  # 特勤处检查间隔（秒）
ai_api_key = config.delta_helper_ai_api_key
ai_base_url = config.delta_helper_ai_base_url
ai_model = config.delta_helper_ai_model
ai_proxy = config.delta_helper_ai_proxy
enable_broadcast_record = config.delta_helper_enable_broadcast_record

bind_delta_help = on_command("三角洲帮助")
bind_delta_login = on_command("三角洲登录", aliases={"三角洲登陆"})
bind_delta_player_info = on_command("三角洲信息")
bind_delta_password = on_command("三角洲密码")
bind_delta_safehouse = on_command("三角洲特勤处")
bind_delta_safehouse_remind_open_close = on_command("三角洲特勤处提醒")
bind_delta_daily_report = on_command("三角洲日报")
bind_delta_weekly_report = on_command("三角洲周报")
bind_delta_ai_comment = on_command("三角洲AI锐评", aliases={"三角洲ai锐评"})
bind_delta_get_record = on_command("三角洲战绩")
bind_delta_broadcast_record_open_close = on_command("三角洲战绩播报")

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
1. 三角洲登录：通过扫码登录三角洲账号，如果是在群聊，登录后会自动播报百万撤离或百万战损战绩以及战场百杀或分均1000+战绩，平台可选填qq/微信，不填参数默认qq登录
2. 三角洲信息：查看三角洲基本信息
3. 三角洲密码：查看三角洲今日密码门密码
4. 三角洲特勤处：查看三角洲特勤处制造状态
5. 三角洲特勤处提醒 [操作]：开启或关闭特勤处提醒功能，操作可选：开启/关闭
6. 三角洲日报：查看三角洲日报
7. 三角洲周报：查看三角洲周报
8. 三角洲AI锐评：ai锐评玩家数据
9. 三角洲战绩 [模式] [页码] L[战绩条数上限]：查看三角洲战绩，模式可选：烽火/战场，默认烽火，页码可选任意正整数，不指定页码则显示第一页，单页战绩条数上限可选任意正整数，不指定默认50
10. 三角洲战绩播报 [操作]：用户开启或关闭自己的战绩播报功能，操作可选：开启/关闭""")


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
        price_int = int(final_price)
        try:
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

async def format_tdm_record_message(record_data: dict, user_name: str) -> bytes|str|None:
    """格式化战场战绩播报消息"""
    try:
        # 解析时间
        event_time = record_data.get('dtEventTime', '')
        # 解析地图
        map_id = record_data.get('MapID', '')
        map_name = Util.get_map_name(map_id)
        # 解析结果
        match_result = Util.get_tdm_match_result(record_data.get('MatchResult', 0))
        # 解析KDA
        kill_num: int = record_data.get('KillNum', 0)
        death_num: int = record_data.get('Death', 0)
        assist_num: int = record_data.get('Assist', 0)
        # 分数与时长
        total_score: int = record_data.get('TotalScore', 0)
        game_time: int = record_data.get('GameTime', 0)  # 秒
        game_time_str = Util.seconds_to_duration(game_time)
        # 分均得分（避免除零）
        avg_score_per_minute: int = int(total_score * 60 / game_time) if game_time and game_time > 0 else 0

        # 触发条件
        trigger_kill = kill_num >= 100
        trigger_avg = avg_score_per_minute >= 1000
        if not (trigger_kill or trigger_avg):
            return None

        # 文本播报（回退或同时使用）
        if trigger_kill:
            message = f"🎯 {user_name} 捞薯大师！\n"
        else:
            message = f"🎯 {user_name} 刷分大王！\n"
        message += f"⏰ 时间: {event_time}\n"
        message += f"👤 干员: {Util.get_armed_force_name(record_data.get('ArmedForceId', 0))}\n"
        message += f"🗺️ 地图: {map_name}\n"
        message += f"📊 结果: {match_result}\n"
        message += f"⏱️ 时长: {game_time_str}\n"
        message += f"💀 KDA: {kill_num}/{death_num}/{assist_num}\n"
        message += f"💰 总得分: {total_score}\n"
        message += f"🎖️ 分均得分: {avg_score_per_minute}"

        # 构建卡片数据
        if trigger_kill:
            main_label = '捞薯大师'
            main_value = str(kill_num)
            badge_text = '100+杀'
        else:
            main_label = '刷分大王'
            main_value = str(avg_score_per_minute)
            badge_text = '1000+分均得分'

        card_data = {
            'user_name': user_name,
            'title': '战场高光！',
            'time': event_time,
            'map_name': map_name,
            'result': match_result,
            'gametime': game_time_str,
            'armed_force': Util.get_armed_force_name(record_data.get('ArmedForceId', 0)),
            'kill_count': kill_num,
            'death_count': death_num,
            'assist_count': assist_num,
            'total_score': total_score,
            'avg_score_per_minute': avg_score_per_minute,
            'is_good': True,
            'main_label': main_label,
            'main_value': main_value,
            'badge_text': badge_text,
        }

        try:
            renderer = await get_renderer()
            img_data = await renderer.render_tdm_battle_record(card_data)
            return img_data
        except Exception as e:
            logger.exception(f"渲染战场战绩卡片失败: {e}")
            return message
    except Exception as e:
        logger.exception(f"格式化战场战绩消息失败: {e}")
        return None

def is_record_within_time_limit(record_data: dict, max_age_minutes: int = BROADCAST_EXPIRED_MINUTES, mode: Literal["sol", "tdm"] = "sol") -> bool:
    """检查战绩是否在时间限制内"""
    try:
        event_time_str = record_data.get('dtEventTime', '')
        if not event_time_str:
            return False
        
        # 解析时间字符串 "2025-07-20 20: 04: 29"
        # 注意时间格式中有空格，需要处理
        event_time_str = event_time_str.replace(' : ', ':')
        
        # 解析时间
        if mode == "sol":
            event_time = datetime.datetime.strptime(event_time_str, '%Y-%m-%d %H:%M:%S')
        elif mode == "tdm":
            gametime = record_data.get('GameTime', 0)
            event_time = datetime.datetime.strptime(event_time_str, '%Y-%m-%d %H:%M:%S') + datetime.timedelta(seconds=gametime)
        current_time = datetime.datetime.now()
        
        # 计算时间差
        time_diff = current_time - event_time
        time_diff_minutes = time_diff.total_seconds() / 60
        
        return time_diff_minutes <= max_age_minutes
    except Exception as e:
        logger.error(f"检查战绩时间限制失败: {e}")
        return False

@bind_delta_safehouse_remind_open_close.handle()
async def safehouse_remind_open_close(event: MessageEvent, session: async_scoped_session, args: Message = CommandArg()):
    user_data_database = UserDataDatabase(session)
    user_data = await user_data_database.get_user_data(event.user_id)
    if not user_data:
        await bind_delta_safehouse_remind_open_close.finish("未绑定三角洲账号，请先用\"三角洲登录\"命令登录", reply_message=True)

    arg = args.extract_plain_text().strip()

    if arg == "开启" or arg == "":
        if user_data.if_remind_safehouse:
            await bind_delta_safehouse_remind_open_close.finish("特勤处提醒功能已开启", reply_message=True)
        user_data.if_remind_safehouse = True
        
        # 在commit之前获取qq_id，避免会话关闭后无法访问ORM对象属性
        qq_id = user_data.qq_id
        
        await user_data_database.update_user_data(user_data)
        await user_data_database.commit()
        logger.info(f"启动特勤处监控任务: {qq_id}")
        scheduler.add_job(watch_safehouse, 'interval', seconds=SAFEHOUSE_CHECK_INTERVAL, id=f'delta_watch_safehouse_{qq_id}', next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=10), replace_existing=True, kwargs={'qq_id': qq_id}, max_instances=1)
        await bind_delta_safehouse_remind_open_close.finish("特勤处提醒功能已开启", reply_message=True)
    
    elif arg == "关闭":
        if not user_data.if_remind_safehouse:
            await bind_delta_safehouse_remind_open_close.finish("特勤处提醒功能已关闭", reply_message=True)
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
        await bind_delta_safehouse_remind_open_close.finish("特勤处提醒功能已关闭", reply_message=True)
    else:
        await bind_delta_safehouse_remind_open_close.finish("参数错误，请使用\"三角洲特勤处提醒 开启\"或\"三角洲特勤处提醒 关闭\"", reply_message=True)

@bind_delta_broadcast_record_open_close.handle()
async def broadcast_record_open_close(event: MessageEvent, session: async_scoped_session, args: Message = CommandArg()):
    user_data_database = UserDataDatabase(session)
    user_data = await user_data_database.get_user_data(event.user_id)
    if not user_data:
        await bind_delta_broadcast_record_open_close.finish("未绑定三角洲账号，请先用\"三角洲登录\"命令登录", reply_message=True)

    arg = args.extract_plain_text().strip()

    if arg == "开启" or arg == "":
        if user_data.if_broadcast_record:
            await bind_delta_broadcast_record_open_close.finish("战绩播报功能已开启", reply_message=True)
        user_data.if_broadcast_record = True
        
        # 在commit之前获取qq_id，避免会话关闭后无法访问ORM对象属性
        qq_id = user_data.qq_id
        
        await user_data_database.update_user_data(user_data)
        await user_data_database.commit()

        deltaapi = DeltaApi(user_data.platform)
        res = await deltaapi.get_player_info(access_token=user_data.access_token, openid=user_data.openid)
        if res['status'] and res['data']:
            user_name = res['data']['player']['charac_name']
        else:
            user_name = "未知"

        if enable_broadcast_record:
            logger.info(f"启动战绩监控任务: {qq_id} - {user_name}")
            scheduler.add_job(watch_all_record, 'interval', seconds=interval, id=f'delta_watch_record_{qq_id}', next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=10), replace_existing=True, kwargs={'user_name': user_name, 'qq_id': qq_id}, max_instances=1)
            await bind_delta_broadcast_record_open_close.finish("战绩播报功能已开启", reply_message=True)
        else:
            await bind_delta_broadcast_record_open_close.finish("已更新播报监控状态，但bot配置未开启播报功能", reply_message=True)
    
    elif arg == "关闭":
        if not user_data.if_broadcast_record:
            await bind_delta_broadcast_record_open_close.finish("战绩播报功能已关闭", reply_message=True)
        user_data.if_broadcast_record = False
        
        # 在commit之前获取qq_id，避免会话关闭后无法访问ORM对象属性
        qq_id = user_data.qq_id
        
        await user_data_database.update_user_data(user_data)
        await user_data_database.commit()
        try:
            scheduler.remove_job(f'delta_watch_record_{qq_id}')
        except Exception:
            # 任务可能不存在，忽略错误
            pass
        await bind_delta_broadcast_record_open_close.finish("战绩播报功能已关闭", reply_message=True)
    else:
        await bind_delta_broadcast_record_open_close.finish("参数错误，请使用\"三角洲战绩播报 开启\"或\"三角洲战绩播报 关闭\"", reply_message=True)

@bind_delta_login.handle()
async def _(event: MessageEvent, session: async_scoped_session, args: Message = CommandArg()):
    platform = args.extract_plain_text()
    if platform == "" or platform == "QQ" or platform == "qq":
        platform = "qq"
    elif platform == "微信":
        platform = "wx"
    else:
        await bind_delta_login.finish("平台参数错误，请使用QQ或微信", reply_message=True)
    deltaapi = DeltaApi(platform)
    if platform == "qq":
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
        await (Text("请打开手机qq使用摄像头扫码") + Image(image=img)).send(reply=True)

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
                        user_data = UserData(qq_id=qq_id, group_id=group_id, access_token=access_token, openid=openid, platform=platform)
                        user_data_database = UserDataDatabase(session)
                        if not await user_data_database.add_user_data(user_data):
                            await bind_delta_login.finish("保存用户数据失败，请稍查看日志", reply_message=True)
                        await user_data_database.commit()
                        user_name = res['data']['player']['charac_name']
                        scheduler.add_job(watch_all_record, 'interval', seconds=interval, id=f'delta_watch_record_{qq_id}', next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=10), replace_existing=True, kwargs={'user_name': user_name, 'qq_id': qq_id}, max_instances=1)
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

    elif platform == "wx":
        res = await deltaapi.get_wechat_login_qr()
        if not res['status']:
            await bind_delta_login.finish(f"获取二维码失败：{res['message']}")
        img_url = res['data']['qrCode']
        uuid = res['data']['uuid']
        await (Text("请打开手机微信使用摄像头扫码") + Image(image=img_url)).send(reply=True)
        while True:
            res = await deltaapi.check_wechat_login_status(uuid)
            if res['status'] and res['code'] == 3:
                wx_code = res['data']['wx_code']
                res = await deltaapi.get_wechat_access_token(wx_code)
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
                        user_data = UserData(qq_id=qq_id, group_id=group_id, access_token=access_token, openid=openid, platform=platform)
                        user_data_database = UserDataDatabase(session)
                        if not await user_data_database.add_user_data(user_data):
                            await bind_delta_login.finish("保存用户数据失败，请稍查看日志", reply_message=True)
                        await user_data_database.commit()
                        user_name = res['data']['player']['charac_name']
                        scheduler.add_job(watch_all_record, 'interval', seconds=interval, id=f'delta_watch_record_{qq_id}', next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=10), replace_existing=True, kwargs={'user_name': user_name, 'qq_id': qq_id}, max_instances=1)
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

            elif not res['status']:
                await bind_delta_login.finish(f"登录失败：{res['message']}", reply_message=True)
            await asyncio.sleep(0.5)

@bind_delta_player_info.handle()
async def _(event: MessageEvent, session: async_scoped_session):
    user_data_database = UserDataDatabase(session)
    user_data = await user_data_database.get_user_data(event.user_id)
    if not user_data:
        await bind_delta_player_info.finish("未绑定三角洲账号，请先用\"三角洲登录\"命令登录", reply_message=True)
    deltaapi = DeltaApi(user_data.platform)
    res = await deltaapi.get_player_info(access_token=user_data.access_token, openid=user_data.openid)
    basic_info = await deltaapi.get_role_basic_info(access_token=user_data.access_token, openid=user_data.openid)
    sol_info = await deltaapi.get_person_center_info(access_token=user_data.access_token, openid=user_data.openid, resource_type='sol')
    tdm_info = await deltaapi.get_person_center_info(access_token=user_data.access_token, openid=user_data.openid, resource_type='mp')
    if basic_info['status']:
        propcapital = Util.trans_num_easy_for_read(basic_info['data']['propcapital'])
    else:
        propcapital = 0
    try:
        if res['status'] and sol_info['status'] and tdm_info['status']:
            user_name = res['data']['player']['charac_name']
            money = Util.trans_num_easy_for_read(res['data']['money'])
            rankpoint = res['data']['game']['rankpoint']
            soltotalfght = res['data']['game']['soltotalfght']
            solttotalescape = res['data']['game']['solttotalescape']
            soltotalkill = res['data']['game']['soltotalkill']
            solescaperatio = res['data']['game']['solescaperatio']
            profitLossRatio = Util.trans_num_easy_for_read(int(sol_info['data']['solDetail']['profitLossRatio'])//100)
            highKillDeathRatio = f"{int(sol_info['data']['solDetail']['highKillDeathRatio'])/100:.2f}"
            medKillDeathRatio = f"{int(sol_info['data']['solDetail']['medKillDeathRatio'])/100:.2f}"
            lowKillDeathRatio = f"{int(sol_info['data']['solDetail']['lowKillDeathRatio'])/100:.2f}"
            totalGainedPrice = Util.trans_num_easy_for_read(sol_info['data']['solDetail']['totalGainedPrice'])
            totalGameTime = Util.seconds_to_duration(sol_info['data']['solDetail']['totalGameTime'])


            tdmrankpoint = res['data']['game']['tdmrankpoint']
            avgkillperminute = f"{int(res['data']['game']['avgkillperminute'])/100:.2f}"
            tdmtotalfight = res['data']['game']['tdmtotalfight']
            totalwin = res['data']['game']['totalwin']
            tdmtotalkill = int(int(res['data']['game']['tdmduration'])*int(res['data']['game']['avgkillperminute'])/100)
            tdmduration = Util.seconds_to_duration(int(res['data']['game']['tdmduration'])*60)
            tdmsuccessratio = res['data']['game']['tdmsuccessratio']
            avgScorePerMinute = f"{int(tdm_info['data']['mpDetail']['avgScorePerMinute'])/100:.2f}"
            totalVehicleDestroyed = tdm_info['data']['mpDetail']['totalVehicleDestroyed']
            totalVehicleKill = tdm_info['data']['mpDetail']['totalVehicleKill']
            
            try:
                renderer = await get_renderer()
                player_data = {
                    'user_name': user_name,
                    'money': money,
                    'propcapital': propcapital,
                    'rankpoint': rankpoint,
                    'soltotalfght': soltotalfght,
                    'solttotalescape': solttotalescape,
                    'soltotalkill': soltotalkill,
                    'solescaperatio': solescaperatio,
                    'profitLossRatio': profitLossRatio,
                    'highKillDeathRatio': highKillDeathRatio,
                    'medKillDeathRatio': medKillDeathRatio,
                    'lowKillDeathRatio': lowKillDeathRatio,
                    'totalGainedPrice': totalGainedPrice,
                    'totalGameTime': totalGameTime,
                    'tdmrankpoint': tdmrankpoint,
                    'avgkillperminute': avgkillperminute,
                    'tdmtotalfight': tdmtotalfight,
                    'totalwin': totalwin,
                    'tdmtotalkill': tdmtotalkill,
                    'tdmduration': tdmduration,
                    'tdmsuccessratio': tdmsuccessratio,
                    'avgScorePerMinute': avgScorePerMinute,
                    'totalVehicleDestroyed': totalVehicleDestroyed,
                    'totalVehicleKill': totalVehicleKill
                }
                img_data = await renderer.render_player_info(player_data)
                await Image(image=img_data).finish(reply=True)
            except FinishedException:
                raise
            except Exception as e:
                logger.error(f"渲染玩家信息卡片失败: {e}")
                # 降级到文本模式
            
            message = Text(f"【{user_name}的个人信息】\n")
            message += Text("--- 账户信息 ---\n")
            message += Text(f"现金：{money}\n")
            message += Text(f"仓库流动资产：{propcapital}\n\n")
            message += Text("--- 烽火数据 ---\n")
            message += Text(f"总场数：{soltotalfght} | 总撤离数：{solttotalescape} | 撤离率：{solescaperatio}\n")
            message += Text(f"总击杀：{soltotalkill} | 排位分：{rankpoint} | 总游戏时长：{totalGameTime}\n")
            message += Text(f"赚损比{profitLossRatio} | 总带出：{totalGainedPrice}\n")
            message += Text(f"kd(常规 | 机密 | 绝密)：{highKillDeathRatio} | {medKillDeathRatio} | {lowKillDeathRatio}\n\n")
            message += Text("--- 战场数据 ---\n")
            message += Text(f"总场数：{tdmtotalfight} | 总胜场：{totalwin} | 胜率：{tdmsuccessratio}\n")
            message += Text(f"总击杀：{tdmtotalkill} | 排位分：{tdmrankpoint} | 总游戏时长：{tdmduration}\n")
            message += Text(f"分均击杀：{avgkillperminute} | 分均得分：{avgScorePerMinute}\n")
            message += Text(f"总摧毁载具：{totalVehicleDestroyed} | 总载具击杀：{totalVehicleKill}\n")
            await message.finish(reply=True)
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
    deltaapi = DeltaApi(user_data.platform)
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
        deltaapi = DeltaApi(user_data.platform)
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
    deltaapi = DeltaApi(user_data.platform)
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
    platform = user_data.platform
    await user_data_database.commit()
    deltaapi = DeltaApi(platform)
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
            if res['status'] and res['data']:
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
        platform = user_data.platform
        await user_data_database.commit()
    else:
        await user_data_database.commit()
        await bind_delta_ai_comment.finish("未绑定三角洲账号，请先用\"三角洲登录\"命令登录", reply_message=True)
   
    deltaapi = DeltaApi(platform)
    res = await deltaapi.get_person_center_info(access_token=access_token, openid=openid)
    if not res['status']:
        await bind_delta_ai_comment.finish("获取角色信息失败，可能需要重新登录", reply_message=True)

    person_center_info = res['data']['solDetail']
    profitLossRatio = int(person_center_info.get('profitLossRatio', '0'))//100
    highKillDeathRatio = f"{(int(person_center_info.get('highKillDeathRatio', '0'))/100):.2f}"
    lowKillDeathRatio = f"{(int(person_center_info.get('lowKillDeathRatio', '0'))/100):.2f}"
    medKillDeathRatio = f"{(int(person_center_info.get('medKillDeathRatio', '0'))/100):.2f}"
    totalFight = person_center_info.get('totalFight', '0')
    totalEscape = person_center_info.get('totalEscape', '0')
    totalGainedPrice = person_center_info.get('totalGainedPrice', '0')
    totalKill = person_center_info.get('totalKill', '0')
    totalGameTime = Util.seconds_to_duration(person_center_info.get('totalGameTime', '0'))

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
        
        if ai_proxy:
            httpx_client = httpx.AsyncClient(proxy=ai_proxy)
        else:
            httpx_client = httpx.AsyncClient()
        client = AsyncOpenAI(
            api_key=ai_api_key,
            base_url=ai_base_url,
            http_client=httpx_client
        )

        response = await client.chat.completions.create(
        model=ai_model,
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
                "content": f"这个玩家的生涯数据：赚损比（每死一次可以赚多少哈夫币）是{profitLossRatio}，绝密行动kda是{highKillDeathRatio}，机密行动kda是{medKillDeathRatio}，常规行动kda是{lowKillDeathRatio}，总场数是{totalFight}，总撤离数是{totalEscape}，总获取哈夫币是{totalGainedPrice}，总游戏时长是{totalGameTime}，总击杀是{totalKill}；这名玩家上周的数据：总场数是{total_sol_num}，总撤离数是{total_exacuation_num}，百万以上撤离次数是{GainedPrice_overmillion_num}，总击杀是{total_Kill_Player}，总死亡是{total_Death_Count}，总游戏时长是{total_Online_Time_str}，总带出是{Gained_Price}，资产是从{price_list[0]}到{price_list[-1]}，资产变化是{rise_Price}。"
            }
            ]
        )
        
        if response.choices[0].message.content:
            increaser.execute()
            msg = Mention(user_id=str(event.user_id)) + Text(' ') + Text(response.choices[0].message.content.strip())
            await msg.finish()
        else:
            logger.debug(f"AI锐评内容为空: {response.choices[0].message}")
            await bind_delta_ai_comment.finish("AI锐评内容为空，请查看日志", reply_message=True)

@bind_delta_get_record.handle()
async def get_record(event: MessageEvent, session: async_scoped_session, args: Message = CommandArg()):
    user_data_database = UserDataDatabase(session)
    user_data = await user_data_database.get_user_data(event.user_id)
    if not user_data:
        await bind_delta_get_record.finish("未绑定三角洲账号，请先用\"三角洲登录\"命令登录", reply_message=True)
    
    # 解析参数，支持：
    # [模式] [页码] L[战绩条数上限]
    # 默认：模式=烽火(type_id=4)，页码=1，条数上限=50
    raw_text = args.extract_plain_text().strip()
    type_id = 4
    page = 1
    line_limit = 50

    if raw_text:
        tokens = raw_text.split()
        seen_page = False
        seen_mode = False
        seen_limit = False

        for token in tokens:
            # 处理条数上限 L<number>
            if token.startswith(('L', 'l')):
                if seen_limit:
                    await bind_delta_get_record.finish("参数过多", reply_message=True)
                limit_str = token[1:]
                if not limit_str.isdigit():
                    await bind_delta_get_record.finish("参数错误", reply_message=True)
                value = int(limit_str)
                if value <= 0:
                    await bind_delta_get_record.finish("参数错误", reply_message=True)
                line_limit = value
                seen_limit = True
                continue

            # 处理模式
            if token in ["烽火", "烽火行动"]:
                if seen_mode:
                    await bind_delta_get_record.finish("参数过多", reply_message=True)
                type_id = 4
                seen_mode = True
                continue
            if token in ["战场", "大战场", "全面战场"]:
                if seen_mode:
                    await bind_delta_get_record.finish("参数过多", reply_message=True)
                type_id = 5
                seen_mode = True
                continue

            # 处理页码（正整数）
            try:
                page_value = int(token)
                if page_value <= 0:
                    await bind_delta_get_record.finish("参数错误", reply_message=True)
                if seen_page:
                    await bind_delta_get_record.finish("参数过多", reply_message=True)
                page = page_value
                seen_page = True
            except ValueError:
                # 非法的词元（既不是模式、也不是数字、也不是L上限）
                await bind_delta_get_record.finish("请输入正确参数，格式：三角洲战绩 [模式] [页码] L[战绩条数上限]", reply_message=True)

    deltaapi = DeltaApi(user_data.platform)
    res = await deltaapi.get_player_info(access_token=user_data.access_token, openid=user_data.openid)
    if not res['status']:
        await bind_delta_get_record.finish("获取玩家信息失败，可能需要重新登录", reply_message=True)
    user_name = res['data']['player']['charac_name']

    res = await deltaapi.get_record(user_data.access_token, user_data.openid, type_id, page)
    if not res['status']:
        await bind_delta_get_record.finish("获取战绩失败，可能需要重新登录", reply_message=True)

    if type_id == 4:
        if not res['data']['gun']:
            await bind_delta_get_record.finish("本页没有战绩", reply_message=True)

        index = 1
        msgs: list[Union[Text, Image]] = [Text(f"{user_name}烽火战绩 第{page}页")]
        
        # 受限并发渲染，保持顺序
        renderer = await get_renderer()
        concurrency_limit = 8  # 可按需调整
        semaphore = asyncio.Semaphore(concurrency_limit)

        tasks: list[asyncio.Task] = []

        for record in res['data']['gun']:
            # 捕获当前循环变量至局部，避免闭包引用问题
            cur_index = index
            index += 1

            if cur_index > line_limit:
                break
            # 解析时间
            event_time = record.get('dtEventTime', '')
            # 解析地图
            map_id = record.get('MapId', '')
            map_name = Util.get_map_name(map_id)
            # 解析结果
            escape_fail_reason = record.get('EscapeFailReason', 0)
            result_str = "撤离成功" if escape_fail_reason == 1 else "撤离失败"
            # 解析时长
            duration_seconds = record.get('DurationS', 0)
            minutes = duration_seconds // 60
            seconds = duration_seconds % 60
            duration_str = f"{minutes}分{seconds}秒"
            # 解析击杀数
            kill_count = record.get('KillCount', 0)
            # 解析收益
            final_price = record.get('FinalPrice', '0')
            if final_price is None:
                final_price = "未知"
            # 解析纯利润
            flow_cal_gained_price = record.get('flowCalGainedPrice', 0)
            flow_cal_gained_price_str = f"{'' if flow_cal_gained_price >= 0 else '-'}{Util.trans_num_easy_for_read(abs(flow_cal_gained_price))}"
            # 格式化收益
            try:
                price_int = int(final_price)
                price_str = Util.trans_num_easy_for_read(price_int)
            except:
                price_str = final_price

            # 解析干员
            ArmedForceId = record.get('ArmedForceId', '')
            ArmedForce = Util.get_armed_force_name(ArmedForceId)

            fallback_message = (
                f"#{cur_index} {event_time}\n"
                f"🗺️ 地图: {map_name} | 干员: {ArmedForce}\n"
                f"📊 结果: {result_str} | 存活时长: {duration_str}\n"
                f"💀 击杀干员: {kill_count}\n"
                f"💰 带出: {price_str}\n"
                f"💸 利润: {flow_cal_gained_price_str}"
            )

            card_data = {
                'user_name': user_name,
                'time': event_time,
                'map_name': map_name,
                'armed_force': ArmedForce,
                'result': result_str,
                'duration': duration_str,
                'kill_count': kill_count,
                'price': price_str,
                'profit': flow_cal_gained_price_str,
                'title': f"#{cur_index}"
            }

            async def render_task(data=card_data, text=fallback_message):
                await semaphore.acquire()
                try:
                    img = await renderer.render_single_battle_card(data)
                    return Image(image=img)
                except Exception as e:
                    logger.exception(f"渲染单战绩卡片失败: {e}")
                    return Text(text)
                finally:
                    semaphore.release()

            tasks.append(asyncio.create_task(render_task()))

        results = await asyncio.gather(*tasks, return_exceptions=False)
        msgs.extend(results)
        await AggregatedMessageFactory(msgs).finish()

    elif type_id == 5:
        if not res['data']['operator']:
            await bind_delta_get_record.finish("本页没有战绩", reply_message=True)

        index = 1
        msgs = [Text(f"{user_name}战场战绩 第{page}页")]

        # 受限并发渲染，保持顺序
        renderer = await get_renderer()
        concurrency_limit = 8
        semaphore = asyncio.Semaphore(concurrency_limit)
        tasks = []

        for record in res['data']['operator']:
            cur_index = index
            index += 1
            # 解析时间
            event_time = record.get('dtEventTime', '')
            # 解析地图
            map_id = record.get('MapID', '')
            map_name = Util.get_map_name(map_id)
            # 解析结果
            MatchResult = record.get('MatchResult', 0)
            if MatchResult == 1:
                result_str = "胜利"
            elif MatchResult == 2:
                result_str = "失败"
            elif MatchResult == 3:
                result_str = "中途退出"
            else:
                result_str = f"未知{MatchResult}"
            # 解析时长
            gametime = record.get('gametime', 0)
            minutes = gametime // 60
            seconds = gametime % 60
            duration_str = f"{minutes}分{seconds}秒"
            # 解析KDA
            KillNum = record.get('KillNum', 0)
            Death = record.get('Death', 0)
            Assist = record.get('Assist', 0)

            # 解析救援数
            RescueTeammateCount = record.get('RescueTeammateCount', 0)
            RoomId = record.get('RoomId', '')
            res = await deltaapi.get_tdm_detail(user_data.access_token, user_data.openid, RoomId)
            if res['status'] and res['data']:
                mpDetailList = res['data'].get('mpDetailList', [])
                for mpDetail in mpDetailList:
                    if mpDetail.get('isCurrentUser', False):
                        rescueTeammateCount = mpDetail.get('rescueTeammateCount', 0)
                        if rescueTeammateCount > 0:
                            RescueTeammateCount = rescueTeammateCount
                            break
            else:
                logger.error(f"获取战绩详情失败: {res['message']}")
                

            # 解析总得分
            TotalScore = record.get('TotalScore', 0)
            avgScorePerMinute = int(TotalScore * 60 / gametime) if gametime and gametime > 0 else 0

            # 解析干员
            ArmedForceId = record.get('ArmedForceId', '')
            ArmedForce = Util.get_armed_force_name(ArmedForceId)

            fallback_message = (
                f"#{cur_index} {event_time}\n"
                f"🗺️ 地图: {map_name} | 干员: {ArmedForce}\n"
                f"📊 结果: {result_str} | 时长: {duration_str}\n"
                f"💀 K/D/A: {KillNum}/{Death}/{Assist} | 救援: {RescueTeammateCount}\n"
                f"🥇 总得分: {TotalScore} | 分均得分: {avgScorePerMinute}"
            )

            card_data = {
                'title': f"#{cur_index}",
                'time': event_time,
                'user_name': user_name,
                'map_name': map_name,
                'armed_force': ArmedForce,
                'result': result_str,
                'gametime': duration_str,
                'kill_count': KillNum,
                'death_count': Death,
                'assist_count': Assist,
                'rescue_count': RescueTeammateCount,
                'total_score': TotalScore,
                'avg_score_per_minute': avgScorePerMinute,
            }

            async def render_task(data=card_data, text=fallback_message):
                await semaphore.acquire()
                try:
                    img = await renderer.render_single_tdm_card(data)
                    return Image(image=img)
                except Exception as e:
                    logger.exception(f"渲染战场单战绩卡片失败: {e}")
                    return Text(text)
                finally:
                    semaphore.release()

            tasks.append(asyncio.create_task(render_task()))

        results = await asyncio.gather(*tasks, return_exceptions=False)
        msgs.extend(results)
        await AggregatedMessageFactory(msgs).finish()
    


async def watch_record(user_name: str, qq_id: int):
    session = get_session()
    user_data_database = UserDataDatabase(session)
    user_data = await user_data_database.get_user_data(qq_id)
    if user_data:
        deltaapi = DeltaApi(user_data.platform)
        # logger.debug(f"开始获取玩家{user_name}的战绩")
        res = await deltaapi.get_record(user_data.access_token, user_data.openid)
        if res['status']:
            # logger.debug(f"玩家{user_name}的战绩：{res['data']}")
            
            # 处理gun模式战绩
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
                    RoomId = latest_record.get('RoomId', '')
                    res = await deltaapi.get_tdm_detail(user_data.access_token, user_data.openid, RoomId)
                    if res['status'] and res['data']:
                        mpDetailList = res['data'].get('mpDetailList', [])
                        for mpDetail in mpDetailList:
                            if mpDetail.get('isCurrentUser', False):
                                rescueTeammateCount = mpDetail.get('rescueTeammateCount', 0)
                                if rescueTeammateCount > 0:
                                    latest_record['RescueTeammateCount'] = rescueTeammateCount
                                    break
                    else:
                        logger.error(f"获取战绩详情失败: {res['message']}")

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
                            if not latest_record_data:
                                latest_record_data = LatestRecord(
                                    qq_id=qq_id,
                                    latest_record_id=record_id,
                                    latest_tdm_record_id=""
                                )
                            else:
                                latest_record_data.latest_record_id = record_id
                            if await user_data_database.update_latest_record(latest_record_data):
                                await user_data_database.commit()
                                logger.info(f"更新最新战绩记录成功: {user_name} - {record_id}")
                            else:
                                logger.error(f"更新最新战绩记录失败: {user_name} - {record_id}")
                        
                    except Exception as e:
                        logger.error(f"发送播报消息失败: {e}")
                else:
                    logger.debug(f"没有新战绩需要播报: {user_name}")
            
    try:
        await session.close()
    except Exception as e:
        logger.error(f"关闭数据库会话失败: {e}")

async def watch_record_tdm(user_name: str, qq_id: int):
    session = get_session()
    user_data_database = UserDataDatabase(session)
    user_data = await user_data_database.get_user_data(qq_id)
    if user_data:
        deltaapi = DeltaApi(user_data.platform)
        # logger.debug(f"开始获取玩家{user_name}的战绩")
        res = await deltaapi.get_record(user_data.access_token, user_data.openid, type_id=5)
        if res['status']:
            # logger.debug(f"玩家{user_name}的战绩：{res['data']}")
            
            # 处理operator模式战绩
            operator_records = res['data'].get('operator', [])
            if not operator_records:
                # logger.debug(f"玩家{user_name}没有operator模式战绩")
                await session.close()
                return
            
            # 获取最新战绩
            if operator_records:
                latest_record = operator_records[0]  # 第一条是最新的
                
                # 检查时间限制
                if not is_record_within_time_limit(latest_record, mode="tdm"):
                    logger.debug(f"最新战绩时间超过{BROADCAST_EXPIRED_MINUTES}分钟，跳过播报")
                    await session.close()
                    return
                
                # 生成战绩ID
                record_id = generate_record_id(latest_record)
                
                # 获取之前的最新战绩ID
                latest_record_data = await user_data_database.get_latest_record(qq_id)
                
                # 如果是新战绩（ID不同）
                if not latest_record_data or latest_record_data.latest_tdm_record_id != record_id:
                    # 格式化播报消息
                    result = await format_tdm_record_message(latest_record, user_name)
                    
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
                            if not latest_record_data:
                                latest_record_data = LatestRecord(
                                    qq_id=qq_id,
                                    latest_record_id="",
                                    latest_tdm_record_id=record_id
                                )
                            else:
                                latest_record_data.latest_tdm_record_id = record_id
                            if await user_data_database.update_latest_record(latest_record_data):
                                await user_data_database.commit()
                                logger.info(f"更新最新战绩记录成功: {user_name} - {record_id}")
                            else:
                                logger.error(f"更新最新战绩记录失败: {user_name} - {record_id}")
                        
                    except Exception as e:
                        logger.error(f"发送播报消息失败: {e}")
                else:
                    logger.debug(f"没有新战绩需要播报: {user_name}")
            
    try:
        await session.close()
    except Exception as e:
        logger.error(f"关闭数据库会话失败: {e}")

async def watch_all_record(user_name: str, qq_id: int):
    await watch_record(user_name, qq_id)
    await watch_record_tdm(user_name, qq_id)

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
        deltaapi = DeltaApi(user_data.platform)
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
        deltaapi = DeltaApi(user_data.platform)
        try:
            # 提前获取所有需要的属性，避免在调度器中访问ORM对象
            qq_id = user_data.qq_id
            access_token = user_data.access_token
            openid = user_data.openid
            if_remind_safehouse = user_data.if_remind_safehouse
            if_broadcast_record = user_data.if_broadcast_record
            
            res = await deltaapi.get_player_info(access_token=access_token, openid=openid)
            if res['status'] and 'charac_name' in res['data']['player']:
                user_name = res['data']['player']['charac_name']
                if enable_broadcast_record and if_broadcast_record:
                    logger.info(f"启动战绩监控任务: {qq_id} - {user_name}")
                    scheduler.add_job(watch_all_record, 'interval', seconds=interval, id=f'delta_watch_record_{qq_id}', next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=10), replace_existing=True, kwargs={'user_name': user_name, 'qq_id': qq_id}, max_instances=1)
                
                # 添加特勤处监控任务
                if if_remind_safehouse:
                    logger.info(f"启动特勤处监控任务: {qq_id} - {user_name}")
                    scheduler.add_job(watch_safehouse, 'interval', seconds=SAFEHOUSE_CHECK_INTERVAL, id=f'delta_watch_safehouse_{qq_id}', next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=10), replace_existing=True, kwargs={'qq_id': qq_id}, max_instances=1)

            else:
                continue
        except Exception as e:
            logger.exception(f"启动战绩监控失败")
            continue

    await session.close()

enable_auto_select_bot()

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

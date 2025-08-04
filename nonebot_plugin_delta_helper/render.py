"""
卡片渲染模块
使用Jinja2模板引擎渲染HTML，然后使用Playwright将HTML转换为图片
"""
import asyncio
import base64
import os
from pathlib import Path
from typing import Any, Dict, Optional
from jinja2 import Environment, FileSystemLoader
from playwright.async_api import async_playwright
from nonebot.log import logger


class CardRenderer:
    """卡片渲染器"""
    
    def __init__(self):
        # 设置模板目录
        template_dir = Path(__file__).parent / "templates"
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=True
        )
        self.browser = None
        self.context = None
        
    async def init(self):
        """初始化浏览器"""
        if not self.browser:
            try:
                playwright = await async_playwright().start()
                self.browser = await playwright.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox', 
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-gpu',
                        '--no-first-run',
                        '--disable-extensions',
                        '--disable-default-apps'
                    ]
                )
                self.context = await self.browser.new_context(
                    viewport={'width': 500, 'height': 800},
                    device_scale_factor=2,
                    locale='zh-CN'
                )
                logger.info("浏览器初始化成功")
            except Exception as e:
                logger.error(f"浏览器初始化失败: {e}")
                raise RuntimeError(f"无法启动浏览器，请确保已安装 Playwright: {e}")
    
    async def close(self):
        """关闭浏览器"""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
    
    async def render_card(self, template_name: str, data: Dict[str, Any]) -> bytes:
        """
        渲染卡片
        
        Args:
            template_name: 模板文件名
            data: 渲染数据
            
        Returns:
            图片的二进制数据
        """
        try:
            # 确保浏览器已初始化
            await self.init()
            
            # 渲染模板
            template = self.env.get_template(template_name)
            html = template.render(**data)
            
            # 创建新页面
            if not self.context:
                raise RuntimeError("浏览器未初始化")
            page = await self.context.new_page()
            
            # 设置页面内容
            await page.set_content(html)
            
            # 等待页面加载完成
            await page.wait_for_load_state('networkidle')
            
            # 获取卡片元素
            card_element = await page.query_selector('.card')
            
            # 截图
            if not card_element:
                raise RuntimeError("卡片元素未找到")
            screenshot = await card_element.screenshot(
                type='png',
                omit_background=True
            )
            
            # 关闭页面
            await page.close()
            
            return screenshot
            
        except Exception as e:
            logger.exception(f"渲染卡片失败: {e}")
            raise
    
    async def render_login_success(self, user_name: str, money: str) -> bytes:
        """渲染登录成功卡片"""
        return await self.render_card('login_success.html', {
            'user_name': user_name,
            'money': money
        })
    
    async def render_player_info(self, user_name: str, money: str) -> bytes:
        """渲染玩家信息卡片"""
        return await self.render_card('player_info.html', {
            'user_name': user_name,
            'money': money
        })
    
    async def render_safehouse(self, devices: list) -> bytes:
        """渲染特勤处状态卡片"""
        return await self.render_card('safehouse.html', {
            'devices': devices
        })
    
    async def render_password(self, passwords: list) -> bytes:
        """渲染密码门卡片"""
        return await self.render_card('password.html', {
            'passwords': passwords
        })
    
    async def render_daily_report(self, report_date: str, gain: int, gain_str: str, collections: str) -> bytes:
        """渲染日报卡片"""
        return await self.render_card('daily_report.html', {
            'report_date': report_date,
            'gain': gain,
            'gain_str': gain_str,
            'collections': collections
        })
    
    async def render_weekly_report(
        self,
        user_name: str,
        statDate_str: str,
        Gained_Price_Str: str,
        consume_Price_Str: str,
        rise_Price_Str: str,
        profit_str: str,
        total_ArmedForceId_num_list: list,
        total_mapid_num_list: list,
        friend_list: list,
        profit: int,
        rise_price: int,
        total_sol_num: int,
        total_Online_Time_str: str,
        total_Kill_Player: int,
        total_Death_Count: int,
        total_exacuation_num: str,
        GainedPrice_overmillion_num: int = 0,
        price_list: Optional[list] = None) -> bytes:
        """渲染周报卡片"""
        from .util import Util
        
        if price_list is None:
            price_list = []
        
        # 处理干员数据，转换为图表格式
        armed_forces = []
        if total_ArmedForceId_num_list:
            max_count = max([item.get('inum', 0) for item in total_ArmedForceId_num_list]) if total_ArmedForceId_num_list else 1
            for force in total_ArmedForceId_num_list:
                force_name = Util.get_armed_force_name(force.get('ArmedForceId', 0))
                force_count = force.get('inum', 0)
                percentage = (force_count / max_count * 100) if max_count > 0 else 0
                armed_forces.append({
                    'name': force_name,
                    'count': force_count,
                    'percentage': percentage
                })
        
        # 处理地图数据，转换为图表格式
        maps = []
        if total_mapid_num_list:
            max_count = max([item.get('inum', 0) for item in total_mapid_num_list]) if total_mapid_num_list else 1
            for map_info in total_mapid_num_list:
                map_name = Util.get_map_name(map_info.get('MapId', 0))
                map_count = map_info.get('inum', 0)
                percentage = (map_count / max_count * 100) if max_count > 0 else 0
                maps.append({
                    'name': map_name,
                    'count': map_count,
                    'percentage': percentage
                                })
        
        # 处理价格数据，转换为折线图格式
        chart_data = []
        weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        if price_list and len(price_list) >= 7:
            # 转换价格为数值，处理可能的字符串格式
            prices = []
            for price in price_list[:7]:  # 只取前7天
                try:
                    # 移除可能的货币符号和逗号
                    clean_price = str(price).replace(',', '').replace('¥', '').replace('$', '')
                    prices.append(float(clean_price))
                except (ValueError, TypeError):
                    prices.append(0)
            
            if prices and max(prices) > 0:
                min_price = min(prices)
                max_price = max(prices)
                price_range = max_price - min_price if max_price > min_price else 1
                
                for i, price in enumerate(prices):
                    # 计算相对高度（10-90%范围内）
                    height = ((price - min_price) / price_range * 80 + 10) if price_range > 0 else 50
                    # 计算x位置，让点在网格列的中心
                    x_pos = (i * 2 + 1) / 14 * 100  # 0-100范围内的位置
                    # 反转高度，让低数值在下方，高数值在上方
                    inverted_height = 100 - height
                    chart_data.append({
                        'day': weekdays[i],
                        'price': price,
                        'display_price': Util.trans_num_easy_for_read(int(price)),
                        'height': round(inverted_height, 1),    # CSS用，反转高度
                        'x_position': round(x_pos, 2),          # CSS用，百分比
                        'svg_x': round(x_pos * 4, 2),           # SVG用，0-400数值（匹配viewBox宽度）
                        'svg_y': round(inverted_height, 2)      # SVG用，0-100数值，同样反转
                    })
        
        return await self.render_card('weekly_report.html', {
            'user_name': user_name,
            'statDate_str': statDate_str,
            'Gained_Price_Str': Gained_Price_Str,
            'consume_Price_Str': consume_Price_Str,
            'rise_Price_Str': rise_Price_Str,
            'profit_str': profit_str,
            'profit': profit,
            'rise_price': rise_price,
            'total_sol_num': total_sol_num,
            'online_time': total_Online_Time_str,
            'total_kill': total_Kill_Player,
            'total_death': total_Death_Count,
            'total_exacuation_num': total_exacuation_num,
            'million_gained': int(GainedPrice_overmillion_num),
            'armed_forces': armed_forces,
            'maps': maps,
            'friend_list': friend_list,
            'chart_data': chart_data
        })
    
    async def render_battle_record(self, data: dict) -> bytes:
        """渲染战绩播报卡片"""
        return await self.render_card('battle_record.html', data)
    
    async def render_ai_comment(self, user_name: str, date_range: str, comment: str, score: Optional[float] = None) -> bytes:
        """渲染AI锐评卡片"""
        return await self.render_card('ai_comment.html', {
            'user_name': user_name,
            'date_range': date_range,
            'comment': comment,
            'score': score
        })


# 全局渲染器实例
_renderer: Optional[CardRenderer] = None


async def get_renderer() -> CardRenderer:
    """获取渲染器实例"""
    global _renderer
    if _renderer is None:
        _renderer = CardRenderer()
        await _renderer.init()
    return _renderer


async def close_renderer():
    """关闭渲染器"""
    global _renderer
    if _renderer:
        await _renderer.close()
        _renderer = None
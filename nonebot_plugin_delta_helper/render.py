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
    
    async def render_weekly_report(self, user_name: str, statDate_str: str, Gained_Price_Str: str, consume_Price_Str: str, rise_Price_Str: str, profit_str: str, total_ArmedForceId_num_list: list, total_mapid_num_list: list, friend_list: list) -> bytes:
        """渲染周报卡片"""
        return await self.render_card('weekly_report.html', {
            'user_name': user_name,
            'statDate_str': statDate_str,
            'Gained_Price_Str': Gained_Price_Str,
            'consume_Price_Str': consume_Price_Str,
            'rise_Price_Str': rise_Price_Str,
            'profit_str': profit_str,
            'total_ArmedForceId_num_list': total_ArmedForceId_num_list,
            'total_mapid_num_list': total_mapid_num_list,
            'friend_list': friend_list
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
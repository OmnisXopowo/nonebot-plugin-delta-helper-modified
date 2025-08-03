#!/usr/bin/env python3
"""
安装卡片渲染所需的依赖
"""
import subprocess
import sys
import os
from pathlib import Path

def run_command(cmd):
    """运行命令并打印输出"""
    print(f"执行命令: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    return result.returncode == 0

def install_deps():
    """安装依赖"""
    current_dir = Path(__file__).parent
    requirements_file = current_dir / "requirements.txt"
    
    print("正在安装Python依赖...")
    if not run_command(f"pip install -r {requirements_file}"):
        print("安装Python依赖失败！")
        return False
    
    print("正在安装Playwright浏览器...")
    if not run_command("playwright install chromium"):
        print("安装Playwright浏览器失败！")
        return False
    
    print("正在安装Playwright系统依赖...")
    if not run_command("playwright install-deps chromium"):
        print("安装Playwright系统依赖失败！")
        return False
    
    print("依赖安装完成！")
    return True

if __name__ == "__main__":
    if install_deps():
        print("✅ 卡片渲染功能依赖安装成功！")
        print("现在可以在配置中启用卡片渲染功能。")
    else:
        print("❌ 依赖安装失败，请检查错误信息。")
        sys.exit(1)
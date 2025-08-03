# 三角洲助手卡片渲染功能

这个插件已添加了卡片式信息输出功能，可以将原本的文本信息以美观的卡片形式展示。

## 功能特点

- 🎨 **美观设计**：现代化的卡片设计，支持渐变色彩和阴影效果
- 📊 **数据可视化**：特勤处进度条、统计图表等可视化元素
- 🔄 **自动降级**：如果卡片渲染失败，自动降级到文本模式
- ⚙️ **可配置**：可以通过配置文件开启或关闭卡片渲染

## 支持的功能

- ✅ 帮助信息卡片
- ✅ 玩家信息卡片
- ✅ 特勤处状态卡片（包含进度条）
- ⏳ 密码门信息卡片
- ⏳ 日报卡片
- ⏳ 周报卡片（包含图表）
- ⏳ 登录成功卡片
- ⏳ 战绩播报卡片

## 安装依赖

1. 运行安装脚本：
```bash
cd /path/to/nonebot_plugin_delta_helper/
python install_deps.py
```

或者手动安装：
```bash
pip install jinja2 playwright
playwright install chromium
playwright install-deps chromium
```

## 配置

在NoneBot的配置文件中添加以下配置：

```python
# 启用卡片渲染（默认为True）
delta_helper_use_card_render = True
```

## 模板自定义

卡片模板位于 `templates/` 目录下，使用Jinja2模板引擎。你可以自定义：

- `base.html` - 基础样式模板
- `help.html` - 帮助信息模板
- `player_info.html` - 玩家信息模板
- `safehouse.html` - 特勤处状态模板
- 其他功能模板...

## 故障排除

### 1. 渲染失败自动降级到文本模式
检查日志中的错误信息，可能的原因：
- Playwright浏览器未安装
- 系统缺少必要的依赖
- 模板文件有语法错误

### 2. 浏览器启动失败
在无头服务器上可能需要额外的系统依赖：
```bash
# Ubuntu/Debian
sudo apt-get install -y libgconf-2-4 libxss1 libgtk-3-0 libxss1 libgconf-2-4 libasound2

# CentOS/RHEL
sudo yum install -y libXcomposite libXcursor libXdamage libXext libXi libXtst cups-libs libXScrnSaver libXrandr alsa-lib
```

### 3. 关闭卡片渲染
如果遇到问题，可以临时关闭卡片渲染：
```python
delta_helper_use_card_render = False
```

## 技术细节

- **模板引擎**：Jinja2
- **渲染引擎**：Playwright (Chromium)
- **输出格式**：PNG图片
- **样式**：CSS + HTML
- **字体**：系统默认字体栈
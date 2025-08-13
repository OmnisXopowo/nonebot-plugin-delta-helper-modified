<div align="center">
  <a href="https://v2.nonebot.dev/store"><img src="https://github.com/A-kirami/nonebot-plugin-template/blob/resources/nbp_logo.png" width="180" height="180" alt="NoneBotPluginLogo"></a>
  <br>
  <p><img src="https://github.com/A-kirami/nonebot-plugin-template/blob/resources/NoneBotPlugin.svg" width="240" alt="NoneBotPluginText"></p>
</div>

<div align="center">

# nonebot-plugin-delta-helper

_✨ 三角洲助手插件 ✨_


<a href="./LICENSE">
    <img src="https://img.shields.io/github/license/BraveCowardp/nonebot-plugin-delta-helper.svg" alt="license">
</a>
<a href="https://pypi.python.org/pypi/nonebot-plugin-delta-helper">
    <img src="https://img.shields.io/pypi/v/nonebot-plugin-delta-helper.svg" alt="pypi">
</a>
<img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="python">

</div>

## 📖 介绍

三角洲助手插件，目前主要是验证打通了登录流程，有登录和自动播报战绩功能，后续功能待开发

欢迎提建议和issue

## 💿 安装

<details open>
<summary>使用 nb-cli 安装(目前还未发布到插件市场)</summary>
在 nonebot2 项目的根目录下打开命令行, 输入以下指令即可安装

    nb plugin install nonebot-plugin-delta-helper

</details>

<details>
<summary>使用包管理器安装</summary>
在 nonebot2 项目的插件目录下, 打开命令行, 根据你使用的包管理器, 输入相应的安装命令

<details>
<summary>pip</summary>

    pip install nonebot-plugin-delta-helper
</details>
<details>
<summary>pdm</summary>

    pdm add nonebot-plugin-delta-helper
</details>
<details>
<summary>poetry</summary>

    poetry add nonebot-plugin-delta-helper
</details>
<details>
<summary>conda</summary>

    conda install nonebot-plugin-delta-helper
</details>

打开 nonebot2 项目根目录下的 `pyproject.toml` 文件, 在 `[tool.nonebot]` 部分追加写入

    plugins = ["nonebot_plugin_delta_helper"]

</details>

## ⚙️ 配置

在 nonebot2 项目的`.env`文件中添加下表中的必填配置

| 配置项 | 必填 | 默认值 | 说明 |
|:-----:|:----:|:----:|:----:|
| delta_helper_ai_api_key | 否 | 空 | AI锐评使用的api key，不填写无法使用ai锐评，不影响其他功能 |
| delta_helper_ai_base_url | 否 | 空 | 调用AI模型的base url |
| delta_helper_ai_model | 否 | 空 | 调用的AI模型名 |
| delta_helper_ai_proxy | 否 | 空 | 调用AI模型使用的代理 |

## 🎉 使用
### 更新数据模型 <font color=#fc8403 >使用必看！！！！！</font>
本插件使用了官方推荐的`nonebot-plugin-orm`插件操作数据库，安装插件或更新插件版本后，在启动机器人前，都需要执行此命令。
```shell
nb orm upgrade
```
手动执行下列命令检查数据库模式是否与模型定义一致。机器人启动前也会自动运行此命令，并在检查失败时阻止启动。
```shell
nb orm check
```
看到`没有检测到新的升级操作`字样时，表明数据库模型已经成功创建或更新。

> [!TIP]
> 如果使用sqlite作为数据库，推荐把日志模式设置为wal模式以提高并发性能
> ```
> pragma journal_mode=WAL;
> ```

### 安装绘图所需依赖
```
playwright install chromium
playwright install-deps chromium
```
更新模型并且安装绘图依赖后，可以启动机器人

### 指令表
| 指令 | 参数 | 权限 | 需要@ | 范围 | 说明 |
|:----|:----|:----|:----|:----|:----|
| 三角洲帮助 | 无 | 群员 | 否 | 群聊/私聊 | 查看帮助 |
| 三角洲登录 | [平台] | 群员 | 否 | 建议群聊 | 通过扫码登录三角洲账号，如果是在群聊，登录后会自动播报百万撤离或百万战损战绩以及战场百杀或分均1000+战绩，平台可选填qq/微信，不填参数默认qq登录 |
| 三角洲信息 | 无 | 群员 | 否 | 群聊/私聊 | 查看三角洲基本信息 |
| 三角洲密码 | 无 | 群员 | 否 | 群聊/私聊 | 查看今日密码门密码 |
| 三角洲特勤处 | 无 | 群员 | 否 | 群聊/私聊 | 查看三角洲特勤处制造状态 |
| 三角洲特勤处提醒开启 | 无 | 群员 | 否 | 群聊/私聊 | 开启特勤处提醒功能，制造完成后提醒玩家 |
| 三角洲特勤处提醒关闭 | 无 | 群员 | 否 | 群聊/私聊 | 关闭特勤处提醒功能 |
| 三角洲日报 | 无 | 群员 | 否 | 群聊/私聊 | 查看三角洲日报 |
| 三角洲周报 | 无 | 群员 | 否 | 群聊/私聊 | 查看三角洲周报 |
| 三角洲AI锐评 | 无 | 群员 | 否 | 群聊/私聊 | 接入AI模型，对个人数据进行辛辣锐评 |
| 三角洲战绩 | [模式] [页码] L[战绩条数上限] | 群员 | 否 | 群聊/私聊 | 查看三角洲战绩，模式可选：烽火/战场，默认烽火，页码可选任意正整数，不指定页码则显示第一页，单页战绩条数上限可选任意正整数，不指定默认50 |
| 三角洲战绩播报 | [操作] | 群员 | 否 | 群聊/私聊 | 用户开启或关闭自己的战绩播报功能，操作可选：开启/关闭 |

## TODO
- [ ] 开发其他功能，有任何想法或需求欢迎提建议和issue、PR
- [ ] 想要做成信息卡片的形式（个人信息、战绩之类），~~但是不了解图片排版和渲染~~用AI做了一版，勉强可以看吧

## 鸣谢
- [NoneBot2](https://github.com/nonebot/nonebot2) - 优秀的机器人框架。
- [DeltaForce API](https://github.com/coolxitech/deltaforce) - 三角洲行动小程序api调用参考。
- [三角洲行动数据API](https://df-api.apifox.cn/) - [浅巷墨黎](https://github.com/dnyo666)整理的三角洲行动小程序api文档

---

<div align="center">

**如果这个项目对你有帮助，请给它一个 ⭐️ 十分感谢！**

</div>
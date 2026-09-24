炼金炉 V2.0.1 macOS 版
===============

启动：双击“炼金炉.app”即可自动启动服务并打开浏览器；也可双击“start_lianjinlu.command”，随后访问 http://127.0.0.1:8765。

应用图标：macOS 应用包使用 `alchemy-furnace.icns` 像素版炼金炉图标。

要求：macOS 已安装 Python 3。程序只使用 Python 标准库，不需要安装第三方 Python 包。

首次使用：
1. 在“AI 服务配置”填写 API 地址和模型名称；
2. 填写 API Key 并保存；
3. 点击“测试连接”。

安全说明：
- API Key 保存在 macOS Keychain 中；
- API Key 不写入 data/settings.json；
- 需求素材、项目和 XML 内容保存在本地 data/ 目录；
- 本压缩包不包含用户历史项目和个人配置。

素材说明：
- 直接提取：Word（.docx）、Markdown、HTML、TXT、XML、JSON、CSV、YAML、Excel（.xlsx/.xlsm）；
- 支持在需求分析页面直接粘贴文本，也支持对文本材料二次编辑；
- 外部框架导入支持 .xlsx/.xlsm/.docx/.md/.txt，导入后自动填充 Markdown Editor 和脑图；
- 脑图支持大型框架紧凑布局、自动适应画布、拖拽平移、滚轮/双指缩放和全屏演示聚焦；
- 旧版 Excel（.xls）请先另存为 .xlsx；
- PDF：需要系统安装 pdftotext；
- CHM：需要系统安装 extract_chmLib；
- 未能提取的文件仍会保存在项目中，可人工查看或后续补充解析工具。

停止：在运行终端按 Ctrl+C。

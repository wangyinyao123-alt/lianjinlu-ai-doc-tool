炼金炉 Windows x64 便携版
===========================

启动：双击“start_lianjinlu.bat”，随后访问 http://127.0.0.1:8765

本版本内置官方 Python 3.12 x64 运行时，不需要单独安装 Python，也不需要联网下载第三方 Python 包。

首次使用：
1. 在“AI 服务配置”填写 API 地址和模型名称；
2. 填写 API Key 并保存；
3. 点击“测试连接”。

安全说明：
- API Key 保存在当前 Windows 用户的 Credential Manager 中；
- API Key 不写入 data/settings.json；
- 需求素材、项目和 XML 内容保存在本地 data/ 目录；
- 本压缩包不包含用户历史项目和个人配置。

素材说明：
- 直接提取：Word（.docx）、Markdown、HTML、TXT、XML、JSON、CSV、YAML；
- PDF：需要系统安装 pdftotext；
- CHM：需要系统安装 extract_chmLib；
- 未能提取的文件仍会保存在项目中，可人工查看或后续补充解析工具。

停止：关闭启动的“炼金炉服务”窗口，或在任务管理器结束该 Python 进程。

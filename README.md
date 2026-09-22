# 炼金炉 V2.0.0

HIK 文档开发工作台的阶段 1 本地原型。

当前已实现：

- 本地项目创建、读取和持久化；
- 项目目录自动创建：`data/projects/<project_id>/materials`、`outputs`、`versions`；
- AI 服务配置：服务类型、API 地址、模型、Temperature、超时；
- macOS Keychain / Windows 用户级 DPAPI 保存 API Key；
- OpenAI 兼容接口、Anthropic 接口连通性测试；
- 本地浏览器工作台界面。
- 素材墙自动读取 `web/assets/editorial` 中的图片，支持替换文件后自动发现；
- 新建项目时默认使用第一张素材作为项目封面，也支持选择素材墙图片或从本地上传封面。
- 首页不展示素材墙，素材仅在新建项目的封面选择器中加载；
- HIK Writing Skill 固定为必选 Skill，支持追加项目/Topic Skill；
- 支持从 0 创建 Concept、Task 和附录类 Concept，生成 XML 初稿并在页面内编辑、保存和校验。
- 需求材料支持上传文件或直接粘贴文本，并可对文本材料二次编辑；
- 支持导入外部 Excel/Word/Markdown/文本框架，自动转换为 Markdown 并同步生成脑图；
- Markdown 框架编辑器支持手动输入、实时同步脑图，以及全新开发、版本更新、Topic 优化三种模式项目筛选。
- 脑图支持大型框架紧凑布局、自动适应画布、拖拽平移、滚轮/双指缩放和全屏演示聚焦，节点数量较多时仍可分层浏览。
- 网页品牌图标、favicon 和项目无封面占位图使用像素版炼金炉形象；Release 同时提供 macOS 应用图标（`.icns`）和 Windows 图标（`.ico`）。

## 启动

macOS 可双击 Release 中的 `炼金炉.app`，也可双击 `启动炼金炉.command`，或在当前目录执行：

```bash
python3 app.py
```

然后打开：<http://127.0.0.1:8765>

停止服务：在终端按 `Ctrl+C`。

## 数据和安全

- 项目元数据和本地文件保存在 `data/`，该目录不应提交到版本库。
- API Key 不写入 `data/settings.json`：macOS 保存到 Keychain，Windows 使用当前用户绑定的 DPAPI 加密后保存到 `data/.api-key.dpapi`，其他 Windows 用户无法解密。
- 当前连通性测试会发送一条最小测试消息“只回复 OK”。
- 需求材料、需求分析、框架生成和 Topic XML 生成均在本地项目工作区内完成；AI 仅在配置服务后调用。

## 阶段 1 后续

1. 持续完善 DOCX、PDF、Markdown、HTML、TXT 和 Excel 的结构化解析；
2. 扩展需求分析表格和历史版本对比能力；
3. 持续补充 HIK Writing Skill 与项目语料库检索能力。

## Windows 便携版

Windows 版本采用免安装便携包，内置官方 Python 运行时，不需要单独安装 Python。

1. 解压 Release 中的 `lianjinlu-windows-x64-v2.0.0.zip` 到本地目录；
2. 双击 `启动炼金炉.bat`；
3. 浏览器打开 <http://127.0.0.1:8765>；
4. 在“AI 服务配置”中填写 API 地址、模型和 API Key。

Windows 下 API Key 使用当前 Windows 用户绑定的 DPAPI 加密保存，项目目录中不保存明文 Key。关闭服务可关闭启动的命令行窗口，或结束对应的 Python 进程。

### 素材格式说明

当前版本支持导入 Word（`.docx`）、PDF、Markdown、HTML、TXT、XML、JSON、CSV、YAML、Excel（`.xlsx/.xlsm`），以及 CHM 原文件保存。框架导入支持 `.xlsx/.xlsm/.docx/.md/.txt`，会自动转换为 Markdown；`.xls` 请先另存为 `.xlsx`。Markdown、HTML、TXT、XML、JSON、CSV、YAML、Excel 和 `.docx` 可直接提取文本；PDF 需要系统安装 `pdftotext`，CHM 需要系统安装 `extract_chmLib`，否则仍会保留原文件，但需要人工阅读或后续补装解析工具。

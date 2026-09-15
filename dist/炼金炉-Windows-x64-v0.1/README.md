# 炼金炉

HIK 文档开发工作台的阶段 1 本地原型。

当前已实现：

- 本地项目创建、读取和持久化；
- 项目目录自动创建：`data/projects/<project_id>/materials`、`outputs`、`versions`；
- AI 服务配置：服务类型、API 地址、模型、Temperature、超时；
- macOS Keychain / Windows Credential Manager 保存 API Key；
- OpenAI 兼容接口、Anthropic 接口连通性测试；
- 本地浏览器工作台界面。
- 素材墙自动读取 `web/assets/editorial` 中的图片，支持替换文件后自动发现；
- 新建项目时默认使用第一张素材作为项目封面，也支持选择素材墙图片或从本地上传封面。
- 首页不展示素材墙，素材仅在新建项目的封面选择器中加载；
- HIK Writing Skill 固定为必选 Skill，支持追加项目/Topic Skill；
- 支持从 0 创建 Concept、Task 和附录类 Concept，生成 XML 初稿并在页面内编辑、保存和校验。

## 启动

macOS 在当前目录执行：

```bash
python3 app.py
```

然后打开：<http://127.0.0.1:8765>

停止服务：在终端按 `Ctrl+C`。

## 数据和安全

- 项目元数据和本地文件保存在 `data/`，该目录不应提交到版本库。
- API Key 不写入 `data/settings.json`：macOS 保存到 Keychain，Windows 保存到 Credential Manager。
- 当前连通性测试会发送一条最小测试消息“只回复 OK”。
- 当前还未接入需求材料上传和 AI 需求分析；Topic XML 已支持本地结构初稿生成，AI 生成接口后续接入。

## 阶段 1 后续

1. 接入 DOCX、PDF、Markdown、HTML、TXT 和 Excel 解析；
2. 建立需求分析工作台；
3. 接入 HIK Writing Skill 和项目 Skill（当前已完成基础配置）；
4. 实现从 0 新建 Concept/Task Topic（当前已完成基础闭环）；
5. 渲染 XML、禁止生成 GUID、使用 `TODO_IMAGE`/`TODO_REF`；
6. 接入 XML 输出校验和导出。

## Windows 便携版

Windows 版本采用免安装便携包，内置官方 Python 运行时，不需要单独安装 Python。

1. 解压 `炼金炉-Windows-x64-v0.1.zip` 到本地目录；
2. 双击 `启动炼金炉.bat`；
3. 浏览器打开 <http://127.0.0.1:8765>；
4. 在“AI 服务配置”中填写 API 地址、模型和 API Key。

Windows 下 API Key 保存在当前 Windows 用户的 Credential Manager 中，项目目录不会保存明文 Key。关闭服务可关闭启动的命令行窗口，或结束对应的 Python 进程。

### 素材格式说明

当前版本支持导入 Word（`.docx`）、PDF、Markdown、HTML、TXT、XML、JSON、CSV、YAML，以及 CHM 原文件保存。Markdown、HTML、TXT、XML、JSON、CSV、YAML 和 `.docx` 可直接提取文本；PDF 需要系统安装 `pdftotext`，CHM 需要系统安装 `extract_chmLib`，否则仍会保留原文件，但需要人工阅读或后续补装解析工具。

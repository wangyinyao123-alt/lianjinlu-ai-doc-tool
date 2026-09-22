# 炼金炉 v2.0.0

## 版本定位

V2.0 是当前阶段的定稿版本，面向 HIK 本地文档开发工作流，覆盖从项目创建、需求材料整理、框架编辑到 Topic XML 审核与导出的完整路径。

## 主要更新

- 首页重构为三种项目模式：全新开发、版本更新、Topic 优化；模式卡片与炼金师角色对应，项目列表按模式筛选展示。
- 新增需求材料直接粘贴和二次编辑，支持 Word、PDF、CHM、Markdown、HTML、TXT、XML、JSON、CSV、YAML 和 Excel 等材料类型。
- 支持导入外部 Excel/Word/Markdown/Text 框架，自动识别框架页签、标题层级并转换为 Markdown；Markdown Editor 与脑图实时同步。
- 框架工作区支持 Markdown 编辑、章节预览、XMind 风格脑图、鱼骨图、主题切换、缩放、适应、全屏演示和节点聚焦。
- 支持从框架节点打开独立 Topic 编辑器，自动继承项目上下文、章节概述、素材、Skill 和提示词。
- Topic 编辑器支持单 Topic 生成、重新生成、人工修改 XML、保存、复制以及 XML/Word/Text/Markdown 下载。
- 支持根据框架批量生成 Topic，提供生成进度、错误状态和单 Topic 重试能力。
- HIK Writing Skill 作为默认必选 Skill；HIK DITA Rule 默认勾选，均支持编辑保存，Skill 支持附件。
- 支持项目级 Skill、Topic 级 Skill 和参考项目语料库，语料库按模式目录树勾选，并实时读取源项目最后保存的框架、XML 和素材。
- 统一明亮米白视觉风格、角色插画、像素炼金炉图标、响应式布局和 Safari 安全区适配。
- 修复 Topic 编辑器偶发点击无响应：节点立即选中、弹窗立即反馈、异步读取可取消且不会被旧请求覆盖。
- XML 生成不输出 GUID，图片和引用使用 `TODO_IMAGE`、`TODO_REF` 占位符。

## 安全与平台

- macOS 和 Windows 均提供独立启动包。
- API Key 不写入普通项目设置：macOS 使用 Keychain，Windows 使用当前用户绑定的 DPAPI。
- 原始材料、项目数据、Skill、框架版本和 XML 内容默认保存在本地。
- macOS 提供 `.app` 应用包和启动脚本；Windows 提供内置 Python 运行时的 x64 便携包。

## 已知限制

- `.xls` 旧版 Excel 需先另存为 `.xlsx`；PDF 和 CHM 的深度文本提取依赖系统工具 `pdftotext`、`extract_chmLib`。
- Reference 类型 Topic 暂不参与需求分析和生成。
- Release 包未包含用户本地 `data/` 项目、API Key 和个人配置。

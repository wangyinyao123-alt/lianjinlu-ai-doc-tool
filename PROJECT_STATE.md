# 项目交接状态

更新时间：2026-11-05（Asia/Taipei，第七轮：仓库根调试版 炼金炉.app 构建完成）
交接编号：PH-20261104-lianjinlu-01（本轮增量见下方"生成链路加固"节）  
源任务编号：未确认  
交接状态：P0 加固 + 第二批协议 + 第三批流水线 + P0 界面导航/任务中心已完成并通过离线测试；尚未创建接手任务
项目目录：`/Users/yinyaowang/Library/Mobile Documents/iCloud~md~obsidian/Documents/Yinyao Wangdesu/HIK/炼金炉`

## 目标与当前版本

炼金炉是用于 HIK 文档工作的本地项目、需求分析、框架和 Topic XML 开发工具。仓库 README 将当前源码标为 **V2.1.0 阶段 1/2 开发版**。当前分支为 `main`，工作区基线显示与 `origin/main` 对齐，但有下述未提交变更；精确 HEAD 提交未记录，接手时请运行 `git rev-parse --short HEAD` 核对。

当前目标是完成并验证这组阶段 1/2 改动，确认功能后再决定是否整理发布说明或打包。用户尚未要求提交、推送或发布。

## 生成链路加固（2026-11-04 第二轮增量）

依据 `docs/生成链路修复清单_v2.1.0.md` 第一、二批，本轮在 `app.py` 新增/修改：

- **finish_reason 截断检查**：`call_ai_messages` 检查 `finish_reason`/`stop_reason`，max_tokens 截断给出明确错误；`max_tokens` 可经 settings 覆盖（`update_settings` 新键：`max_tokens`、`context_char_budget`、`structured_task`）。
- **错误回喂重试**：`generate_with_repair`，解析/校验失败把错误+原输出回喂重试（默认 3 次尝试）；`JobCancelled` 可穿透。框架 JSON、分析 JSON、Topic XML 三条路径均已接入。
- **JSON mode**：框架/分析启用；OpenAI-compatible 加 `response_format`，Anthropic 用 `{` prefill；服务端拒绝 `response_format` 时自动降级重试。
- **全局上下文预算**：`fit_prompt_sections` 瀑布式裁剪（素材 > Skill > 基线/上一版XML > 语料），默认 200k 字符（settings `context_char_budget` 可调）；裁剪明细 `context_report`/`context_summary` 随框架、分析、Topic 结果返回或落盘（topic.json 新字段 `generation_mode`、`unconfirmed`、`context_summary`）。
- **GUID 正则收紧**：仅匹配 `GUID[-=]` + 8-4-4-4-12 十六进制（样例核对自 `XML素材/` 与阶段0文档），不再误伤英文正文。
- **Task 结构化中间稿（原型）**：`settings.structured_task` 默认开。全新/更新的 Task 不再让模型直接写 XML，改为 JSON 中间稿（title/shortdesc/prerequisites/context/steps[{command,info,result}]/overall_result/unconfirmed）→ `render_task_topic_xml` 模板渲染（转义/嵌套/顺序代码保证）→ `validate_topic_xml`。步骤 <2 等规则错误参与回喂。优化模式（带 previous_xml）仍走直接 XML 路径，等结构保留编辑（清单 2.4）落地再切。
- **previous_xml 不再经 sanitize_text**：重生成时上一版 XML 原文送入模型，真实 GUID/conref 引用不被预先破坏（结构保留编辑仍待做）。
- 顺手修：`base64.binascii.Error` → `binascii.Error` 统一。

已验证：`python3 -m py_compile` 通过；`git diff --check` 通过；离线测试 `python3 tools/test_generation_hardening.py` 6 项全过（GUID 正则、预算瀑布+报告、中间稿解析规则错误、XML 渲染转义/顺序/校验、修复循环含回喂消息结构、max_tokens 覆盖）；prompt 构建冒烟测试通过。未验证：配置真实 AI 后的结构化 Task 端到端、JSON mode 在实际模型服务上的兼容性、前端展示（新字段前端暂未消费，不影响现有交互）。

## 第二批协议改造（2026-11-04 第三轮增量）

依据修复清单第二批，全部在 `app.py`：

- **Concept 结构化中间稿**：`CONCEPT_STRUCTURE_INSTRUCTION` + `parse_concept_structure` + `render_concept_topic_xml`。Concept/附录类 Concept 与 Task 一样走 JSON 中间稿 → 模板渲染（section 嵌套层级代码归一化，id `SECTION_x_x` 自动生成）。settings 键升级为 `structured_output`（兼容读取旧 `structured_task`），覆盖 Task + Concept。
- **TODO_CONFIRM 待确认占位**：`CONFIRM_PATTERN` 独立于 IMAGE/REF 计数；`validate_topic_xml` 返回 `confirm_count`，状态归入"需人工处理"；Task/Concept 中间稿 prompt 均要求素材未确认事实登记到 `unconfirmed` 数组并在正文用 TODO_CONFIRM 占位。
- **素材切片 + 段落溯源**：超长素材（> `TOPIC_SLICE_MAX_CHARS`）按 Topic 关键词相关性切片（保留相邻段落上下文），片段带 `［原文 start–end］` 偏移标记；`material_slices`（文件+片段范围）随生成结果返回并落盘 topic.json。
- **缺料聚合接口**：`GET /api/projects/<id>/unconfirmed` → `list_project_unconfirmed`，聚合全部 Topic 的 unconfirmed 事实与 TODO_CONFIRM 计数。
- topic.json 新增落盘字段：`generation_mode`（structured-task/structured-concept/direct-xml）、`unconfirmed`、`material_slices`、`context_summary`。

已验证：离线测试扩至 **10 项全过**（新增：Concept 中间稿解析规则错误、Concept XML 渲染嵌套/转义/TODO_CONFIRM 计数、素材切片偏移溯源、unconfirmed 聚合逻辑）；`py_compile`、`git diff --check` 通过；Concept/Task 结构化 + 直接 XML 三种 prompt 构建冒烟测试通过。未验证：真实 AI 端到端、前端消费新字段（unconfirmed 聚合接口前端暂未接入 UI）。

## 第三批一致性与流水线（2026-11-04 第四轮增量）

依据修复清单第三批（3.3 术语表除外，需配套确认 UI，暂缓），改动在 `app.py` + `web/app.js`：

- **3.1 框架节点稳定 key（弃用行号）**：前端 `frameworkNodeKey(nodes, node)` 按标题路径链（`fw:根 > 父 > 节点`）生成稳定 key，替换全部 3 处 `line:${lineIndex}` 用法（payload 构建、编辑器 Topic 匹配、批量匹配）。框架编辑插入/删除行不再导致 Topic 关联断裂与批量重复生成。旧 Topic 的 `line:` key 保留回退匹配（编辑器打开时新 key → 旧行号 key → 标题+类型三级回退）。
- **3.2 兄弟章节上下文注入**：前端 `frameworkNodeRelatives` 从框架节点树取父章节标题 + 同级节点（标题/类型/概述，最多 30 个），随 payload 传 `parent_title`/`sibling_topics`；后端 `sibling_context_block` 渲染进 Topic prompt，明确"这些内容由其他 Topic 承担，不要展开"——降低多 Topic 生成内容重复。
- **3.5 批量生成下沉后端**：新增 `batch_generate_topics` + `POST /api/projects/<id>/topics/batch-generate-async`。单 Job 顺序生成节点清单：已有相同 `framework_node_key` 的 Topic 原地重生成（保留身份与历史），其余新建；单项失败不中断（逐项记录 status/error）；每项之间检查取消；Job 新增 `progress` 字段（done/total/detail，经 `update_job_progress` 发布并在 `background_job_summary` 返回）。前端 `batchGenerateFrameworkTopics` 从串行 for 循环改为提交一次 + 单 Job 轮询进度，关闭标签页不再中断批量。
- **3.4 跨 Topic 一致性检查（后端）**：`check_topic_consistency` + `GET /api/projects/<id>/consistency`：重复标题、相同 framework_node_key 冲突、缺失关联、GUID 残留、TODO_CONFIRM/unconfirmed 汇总。前端 UI 暂未接入。
- **3.6 材料淘汰明示**：已在第一批由 `fit_prompt_sections` + `context_report` 覆盖，无新增改动。

已验证：离线测试扩至 **13 项全过**（新增：兄弟上下文注入、后端批量生成的 create/update/单项失败隔离、一致性检查各字段）；`py_compile`、`node --check`、`git diff --check` 通过。未验证：真实 AI 端到端、批量生成的前端轮询真机体验、一致性接口 UI。


## 第五轮增量：P0 界面改进（2026-11-05）

范围：修复清单 P0 前端两项——步骤导航 + 任务中心。未删除任何图片/视觉素材。

1. **主流程导航入口**：顶部导航新增“① 框架工作台”（analysis-view）与“② Topic 工作台”（topic-view）两项，主流程不再隐藏在项目卡片后；面包屑文案同步改为“框架工作台 / Topic 工作台”。
2. **右下角任务中心**：新增固定面板 `#job-center`（app.js 新增 jobCenterRegister/Update/Finish/Cancel/renderJobCenter 五个函数），所有 pollJob 通道（框架/Topic/批量）自动登记：
   - 批量任务显示确定性进度条（done/total，来自后端 progress 字段）；单任务显示用时 + 不确定进度动画。
   - 每项带“取消”按钮（POST /api/jobs/<id>/cancel + stopJobPolling）；完成/失败/取消后 6 秒自动消失。
   - 旧的 stopJobPolling 路径（如框架页“取消生成”按钮）也会同步结束任务中心条目，不留僵尸项。
   - Topic 生成条目带动态标签“Topic：<标题>”。
3. 静态资源版本号升至 v=20261105-p0；任务中心样式追加在 app.css 末尾（沿用现有深色主题变量，响应式适配窄屏）。

验证：python 读盘 14 项断言全过（含 4 项图片素材完整性确认——炼金师/模式卡/炼金炉/星空背景均未删）；node --check、离线测试 13 项、git diff --check 通过。未验证：浏览器中任务中心的实际交互（需真机跑一轮批量生成观察）。

注意：web/ 目录在 iCloud 同步卷上，shell grep 偶发读到过期快照，核对文件内容时优先用 Read 工具或 python 读盘。


## 第六轮增量：P1 界面改进（2026-11-05）

1. **框架工作台默认双栏**：state.frameworkPanel 默认 "map"（Markdown + 框架图同屏），boot 时调用 updateFrameworkPanelControls 初始化；说明文案同步更新。
2. **Topic 编辑器改右侧抽屉**：openFrameworkTopicEditor 改为加 is-drawer 类（复用既有 drawer CSS），不再全屏 modal 遮挡框架图；抽屉宽度恢复 860px（原有 1240px 覆盖规则在文件末尾被 override）；关闭抽屉回默认双栏而非收起框架图。
3. **首屏重构**：index.html 中 workspace-grid（我的项目）移到 hero-row 之前；hero 压缩为横幅（标题缩小、间距收紧），**所有图片素材保留**（炼金师/模式卡/炼金炉/星空均未删，仅调布局）。

验证：结构断言（顺序/panel 数/图片/文案）+ node --check + 离线测试 13 项 + git diff --check 全过。未验证：浏览器实际观感（双栏比例、抽屉宽度在窄屏表现）。


## 第七轮增量：调试版 App 打包（2026-11-05）

- 仓库根构建 `炼金炉.app`（Info.plist v2.1.0 + packaging/macos-app 启动器 + 旧版 alchemy-furnace.icns）。
- 特点：PACKAGE_ROOT 指向仓库根，双击直接运行**当前源码**和现有 `data/`，改代码后重开即生效，无需重新打包；启动后自动开浏览器 http://127.0.0.1:8765。
- 冒烟验证通过：/api/health 返回 v2.1.0、首页/CSS 200、/api/projects 正常读到现有项目；验证后服务已停止释放端口。
- 注意：重启后端任务不跨会话；双击前确认没有别的进程占用 8765。
- 发布用自包含包（不含 data）待定版后再打，沿用 dist/炼金炉-macOS-v0.2-latest 的目录结构。


## 第八轮增量：调试包 TCC 修复（2026-11-05）

- 问题：iCloud 目录内的 炼金炉.app 双击时被 macOS TCC 拦截（GUI 启动的进程无 `~/Library/Mobile Documents/` 访问权，报 Errno 1 Operation not permitted；终端直接跑正常）。
- 解决：构建**自包含调试包** `~/Applications/炼金炉/`（app.py + web/ + data/ + 素材 + 炼金炉.app v2.1.0），双击验证通过（health v2.1.0、首页含任务中心、项目数据正常）。
- 新增 `tools/sync_debug_app.sh`：改代码后一键同步到调试包（排除 data/，保留调试包运行数据）。
- 仓库根的 炼金炉.app 已无用（TCC 挡死），可删；iCloud 仓库继续作为开发源码目录。
- 启动器日志固定写到 /tmp/lianjinlu_app.log，双击打不开时先看这里。

## 当前进度（第一轮交接内容，供背景）

- 已实现并写入 README/使用说明：AI 框架、Topic 与批量 Topic 后台任务；框架撤销/重做、历史版本载入和串行保存；JSON 并发保护、原子写入和备份恢复；项目搜索、排序和统计。
- 后台任务状态保存在进程内存中。结果仍写入现有项目文件；重启后不能恢复任务状态。取消只阻止尚未提交的结果写入，已完成提交不会回滚。
- 主要实现位于 `app.py` 和 `web/app.js`；相关控件与样式位于 `web/index.html`、`web/app.css`。
- 当前 `git status` 中 6 个未提交文件：`README.md`、`app.py`、`docs/炼金炉使用说明/炼金炉应用案例与使用说明.md`、`web/app.css`、`web/app.js`、`web/index.html`。这些变更属于当前工作，不要清理或覆盖。
- 已有验证：`git diff --check` 通过；`python3 -m py_compile app.py` 通过。
- 未验证：前后端完整交互、配置 AI 后的真实生成、并发任务与取消边界、Windows/macOS 打包运行。仓库未发现测试目录或明确自动化测试入口。

## 重要文件

- `README.md`：当前功能、运行方式、数据安全和已知边界；版本标为 V2.1.0 阶段 1/2。
- `app.py`：本地 HTTP 服务、项目数据、AI 调用、后台任务和 JSON 存储保护。
- `web/app.js`：工作台交互、后台任务轮询、框架编辑历史与保存。
- `web/index.html`、`web/app.css`：页面结构与样式。
- `docs/炼金炉使用说明/炼金炉应用案例与使用说明.md`：完整使用指南，已同步阶段 1/2 描述。
- `阶段0_XML样例盘点与生成约束.md`、`阶段0_XML样例索引与结构指纹.md`：XML 示例分析与生成约束参考。
- `RELEASE_NOTES_v2.0.1.md`、`README-macOS.txt`、`README-Windows.txt`：仍是 v2.0.1 发布资料；与源码 README 的 v2.1.0 开发状态存在版本差异，发布前需要明确是否更新。
- `data/`：本地项目与设置数据，不应提交；API Key 使用系统凭据存储（Windows 为 DPAPI 文件）。不要在交接中记录密钥。

## 已知边界与未决项

- PDF 文本提取依赖 `pdftotext`，CHM 依赖 `extract_chmLib`；旧版 `.xls` 需先转成 `.xlsx`。
- 后台任务不跨应用重启恢复；版本差异对比和更细粒度 XML 校验仍列为后续方向。
- `README.md` 与打包/发布文档版本不一致；是否将 v2.1.0 定为发布版本尚未确认。
- 未确认本次 6 个文件是否由单一工作流产生，也未做完整浏览器或真实 AI 验收。

## 接手第一步

1. 只读检查 `git status --short --branch`、`git diff --stat` 和 `git rev-parse --short HEAD`，确认未提交改动仍在且没有新的并行修改。
2. 阅读 `README.md`、本文及上述 6 个改动文件的 diff，尤其核验后台任务取消与磁盘提交互斥、失败状态处理、框架跨项目保存顺序。
3. 启动本地服务（`python3 app.py`，默认 `http://127.0.0.1:8765`），在不覆盖现有 `data/` 的前提下验证：项目选择、框架生成/取消/失败状态、撤销重做、版本载入不自动保存、串行保存、Topic 生成。
4. 根据验证结果修复问题并更新本文；若达到阶段验收，再更新发布资料并由用户决定是否打包。

完成标准：关键交互在本地通过；后台任务取消/提交边界和数据恢复行为得到针对性验证；文档的开发版/发布版状态一致；未提交改动与验证结果清楚可审查。

## 可复制的接续开场白

```text
$project-handoff 恢复。项目目录：/Users/yinyaowang/Library/Mobile Documents/iCloud~md~obsidian/Documents/Yinyao Wangdesu/HIK/炼金炉；来源：PROJECT_STATE.md，交接编号 PH-20261104-lianjinlu-01。目标：核验并完成炼金炉 V2.1.0 阶段 1/2 当前未提交改动。限制：保留现有工作区改动和 data/，不提交、不推送、不发布。先只读检查 git 状态、HEAD 和相关 diff，再按文档中的本地功能验收项执行；记录验证结果与发现。完成标准：主要后台任务与框架编辑交互得到验证，文档版本状态一致。
```


## 2026-11-05 独立窗口模式（pywebview）

- 现状：此前双击 .app 是 `open http://127.0.0.1:8765` 弹默认浏览器标签页。
- 改造：`app.py` 拆出 `create_server()`；新增 `window_mode.py` 独立窗口入口，三级降级：pywebview 原生窗口 → Chrome/Edge --app 独立窗口 → 默认浏览器。关闭窗口即退出整个程序。
- 调试包 `~/Applications/炼金炉/` 新增自带 venv（`.venv`，内含 pywebview 6.2.1）；.app 启动脚本优先用 venv + window_mode，日志写入 `data/app.log`。
- 仓库内 `启动炼金炉.command` / `start_lianjinlu.command` / 两个 .bat 均改走 window_mode 入口。
- `tools/sync_debug_app.sh` 新增排除 `.venv` 与 `.chromeprofile`（否则 rsync --delete 会删掉 venv）。
- 冒烟测试通过：health 200；pywebview 窗口打开/关闭正常；13 项离线测试全 PASS。
- 仓库侧未装 pywebview（PEP 668 受保护），仓库 .command 走 Chrome --app 降级；如需原生窗口可在仓库目录自建 venv。


## 2026-11-09 P2 界面改进

- **首页 tab**：hero 封面从 projects-view 挪入新建 #home-view（默认落地页），导航第一位；模式卡片点击后跳项目工作台并筛选；"返回主页"指向首页。素材全部保留仅挪位置。
- **质量巡检面板**（Topic 工作台底部 #quality-panel）：接入后端 /unconfirmed 与 /consistency，显示缺料登记（claim/reason/Topic 标签）与跨 Topic 一致性问题（标题重复/节点重复/GUID 残留/未关联节点），进入视图自动静默巡检 + 手动"运行巡检"按钮。
- **分析命令栏重分组**：改为流程三段式 ①需求材料（含列表/粘贴）→ ②Skill 与提示词 → ③生成/④管理；全部元素 id 不变，新增 .analysis-flow-* / .flow-step-tag 样式。
- **两套 Topic 表单生成逻辑合并**：提取共享 runTopicGenerationJob（禁用按钮→提交异步 Job→轮询→回调结果），generateFrameworkTopic 与 submitTopic 的 AI 分支均走该路径；模板/同步分支保持原样。
- 资源版本 v=20261109-p2；13 项离线测试全 PASS；health 与两个巡检接口实测正常。
- P2 剩余：装饰性英文文案中文化（低优先级）。

## 2026-11-09 P2 收尾（中文化 + 悬浮问号）

- **装饰英文文案中文化**：index.html 全部 section-kicker（如 REGISTRY / PROJECTS → 登记 / 我的项目、SKILL ROUTE → SKILL 约束）、security badge、侧栏与顶部状态、封面区文案改为中文；app.js 动态 kicker（PROJECT DETAIL 等 5 处）与 FISHBONE/MINDMAP PREVIEW 同步中文化。HIK 品牌、SKILL/TOPIC/MARKDOWN 技术词保留。
- **说明性文字收进悬浮问号**：新增 .hint-dot 纯 CSS tooltip（hover/focus 显示，data-tip 存文字，tip-below 变体防顶部裁切）。迁移 19 处：4 个视图头说明段、框架工作台 meta 长说明、2 个编辑器 hint、11 处表单 field-hint、分析辅助信息 panel-note、封面 picker note。JS 动态状态文字（project-mode-hint、材料列表占位）保留原位。
- 资源版本 v=20261109-p3；node --check 通过；已同步重启。
- P2 至此全部完成。

## 2026-11-09 第四批：校验闭环（lint / 生成记录 / 回归集）

- **风格 lint（4.2）**：app.py 新增 lint_topic_xml()，规则代码化：根标签匹配、Task 步骤≥2、shortdesc≤3句且不含 image/xref、concept 必有 conbody、块级容器（conbody/context/prereq/result/section 等）裸文字、点击→单击、半角标点、长句>40字、数字与单位空格、占位符残留。同规则聚合为 count+样例。生成时（AI 与模板路径）lint 结果存入 topic.json 的 lint 字段。
- **生成记录（4.5）**：call_ai_messages 采集 usage（线程局部收集器 begin_ai_call_collection/ai_call_metas，兼容修复重试多轮）；generate_ai_topic 落盘 data/generation_logs/<project>/：模型参数、Skill 内容哈希、prompt 哈希+摘要、usage、attempts、lint 摘要；每项目保留最近 200 条。
- **回归集（4.4）**：capture_regression_case 把项目全部 Topic（生成输入快照+基线 XML+指纹+lint）存 data/regression/case_*.json；topic_structure_fingerprint（根/章节标题/步骤数/shortdesc 句数/标签轮廓）+ fingerprint_similarity（标签路径 Jaccard）；新端点 POST /regression/capture、GET /lint、/generation-logs、/regression；tools/run_regression.py 支持 --list/--offline/--case/--topic/--root（可指向调试包），在线模式重生成对比输出 md+json 报告。
- **质量巡检面板扩展为四块**：风格 lint / 缺料登记 / 一致性 / 生成记录（含 token 累计）；工具栏新增"存为回归基准"按钮。资源版本 20261109-p4。
- 已验证：13 项离线测试 PASS；真实项目（CODESYS手册 2 Topic）lint 命中长句 8 处、半角标点 1 处；基准捕获与离线报告正常。在线对比待配置 API Key 后跑 --case。

## 2026-11-09 书本样式项目卡 + 搜索框修复

- 项目列表卡片改为书本样式（纯 CSS，无新素材）：左侧书脊按模式配色（蓝=全新/紫=更新/绿=优化）、封面图作书封（无封面用像素炉图）、米黄纸质底、右缘内阴影模拟页缘；hover 右移浮起，选中青色描边。renderProjects 卡片加 mode-<mode> 类与 book-cover 结构。
- 搜索框占位文字"搜索项目、产品或阶段"截断，缩短为"搜索项目"。
- 资源版本 20261109-p5，已同步重启。
- 待办新增：借鉴 dsh-synapse（会话画布/分支/并行会话投影）思路，框架定稿后多 agent 并行生成 Topic XML（子 agent 独立 API key 的 profile 机制 + 并行 batch Job + 框架图节点状态徽章），设计已给出待确认实施范围。

## 2026-11-09 多 Agent 并行生成（借鉴 dsh-synapse）

- **Agent 档案**：settings.agent_profiles（最多 8 个，字段 name/provider/base_url/model/temperature/max_tokens/timeout_seconds）；Key 存系统凭据、账户=profile:<id>（KEYCHAIN.get/save/delete 增加 account 参数，Windows 用独立 DPAPI 文件）；档案未配 Key 回退主 Key；call_ai_messages/test_ai_connection 支持 settings["_api_key"] 覆盖。
- **并行引擎**：batch_generate_topics_parallel —— Job 内 N（1-6）个 worker 线程从共享 queue 领节点，worker 各自设 JOB_CONTEXT.job_id（取消/进度机制天然兼容）；progress 含 completed_titles/failed_titles；单节点失败不中断；新端点 POST /topics/batch-generate-parallel-async、GET/POST /api/agent-profiles、POST /api/agent-profiles/<id>/key|delete|test。
- **前端**：设置页新增"Agent 档案"面板（列表/表单/测试/删除）；批量生成 Topic 按钮改为打开"多 Agent 并行生成"弹窗：并行数 + 档案勾选（循环分配）+ 逐节点实时状态清单（○排队 ◐生成中 ●完成 ×失败）；任务可取消，已完成结果保留。
- 资源版本 20261109-p6；13 项离线测试 PASS；档案 CRUD + Key 存取实测通过。在线并行生成待真实 API Key 验收。

## 2026-11-13 b4：新版 UI 包替换（:is() 选择器重排）

- **来源**：`~/Downloads/files (1)/`（app.js / blocks.css / index.html），版本标记实为 `20261112-b2`，即 b2 基线的重新导出，并非在 b3 之上迭代。
- **实际生效变化**：仅两处——① 框架页标题加 `data-en="Framework"`（右侧斜体英文，与其余 4 个视图一致）；② blocks.css 选择器从 `#x#x` 重复 ID 写法统一改写为 `:is(#x):is(#x)`（功能等价，`:has()` 与 `@N` 占位符仍为 0）。app.js 与 b3 完全一致。
- **替换时回补的 b3 内容**（新版丢失，已重新加回）：`topbar-demo-link`「界面演示 ↗」、`regenerate-framework-button`「重新生成」、`capture-regression-case`「存为回归基准」三处删除；`$("#new-project-button")` 改回 `() => openDialog("new")`（防事件对象当 mode 传入）；blocks.css 末尾回补「项目卡片整幅封面 + 渐变透明遮罩 + 纯白卡底」区块（否则卡片会退回彩色块）。
- 资源版本 `v=20261113-b4`；备份 `backups/2026-11-13-pre-b4-native-is-rewrite/`。
- 验证：node --check 通过；CSSOM 解析 269 条规则、`.book-card` 计算背景 #fff / 圆角 26px、按钮 999px、下拉 14px、`.bk-go` absolute；headless 截图首页/项目/框架/Topic/Skill 五视图无错位，控制台无 JS 报错；已同步 `~/Applications/炼金炉/web/` 并重启，health 200。

## 2026-11-17 b5：新设计稿替换（卡片背景系统 + 新建项目弹窗重做）

- **来源**：`~/Downloads/files 2/`（app.js 238KB / blocks.css 55KB / index.html 59KB，版本标记 `20261113-b3`）。与 b4 差异：app.js +418 行、blocks.css 全量重写（55KB，改为 `.bk` 作用域 + `#bk-body`）、index.html +149 行。
- **新版带来的功能**：项目卡片背景系统（卡片颜色 / 自定义图片，存 localStorage `alchemy.cardColor.*` / `alchemy.cardImage.*`，`skinCard` + `drawSwatches` + `#card-look-pop` 浮层）、新建项目弹窗重做（模式选择卡 + 右侧卡片刻预览 + 颜色分组色板 + 12 组配色）。
- **替换时重新回补的 b3/b4 清理**：删除「界面演示 ↗」链接、`regenerate-framework-button`「重新生成」、`capture-regression-case`「存为回归基准」及其 JS 绑定；`$("#new-project-button")` 保持 `() => openDialog("new")`。资源版本 `v=20261117-b6`。
- **排版修复（blocks.css 末尾「b5 排版修复」区块，共 10 条）**：
  1. `#analysis-view/#topic-view/#skills-view/#settings-view` 保留 app.css 的 `margin:0 -42px; padding:0 42px` → 与新版 main-content 内边距不匹配，右侧多出 10~20px 横向滚动条。改为 margin/padding 全 0，内容回到 32px 安全边距。
  2. `.clean-list li` 残留 app.css 的 `grid-template-columns:25px 1fr`，新皮肤又用 `::before` 生成 01/02 大编号 → 正文被挤进 25px 列一字一行。改 `display:block` 并隐藏 HTML 里的冗余 `<span>01</span>`。
  3. 设置页 `.settings-layout` 两列中 `#profiles-panel` 通栏 → 右列留出大片空洞。改为「AI 服务 | 安全边界」并排、Agent 档案通栏。
  4. 框架工作台 `.framework-workbench-head`（app.css `position:sticky;margin:-20px -22px 0`）压住上方 meta 行。改 static + 去掉负上边距（需带上 `#analysis-view` 提升权重，否则被 app.css 的 3 个 ID 规则覆盖）。
  5. 深色 XML 面板的 textarea 占位文字沿用深色 → 看不见。补 `::placeholder` / `.report-empty` 颜色。
  6. `label` 是 flex 列，`<i class="hint-dot">` 被挤到下一行。改为标签右上角绝对定位小图标。
  7. 新建项目弹窗底部黑色操作条是直角，盖住卡片圆角 → 补 `border-radius:0 0 30.5px 30.5px`。
  8. 模式卡说明文字沿用旧 muted 色 #a5928a，在彩色底上对比度不足 → 统一 `var(--bk-ink)`。
  9. 弹窗 `pd-body` 滚动条压住右栏卡片 → `scrollbar-width:thin; scrollbar-gutter:stable`。
  10. app.css 旧书架皮肤的 `.project-card::after` 奶白遮罩（`rgba(255,255,250,.96)` 渐变）仍作用在新卡片上，弹窗预览卡几乎全白、文字不可读 → `content:none`。
- **验证**：node --check 通过；6 个视图控制台无 JS 报错；`docScrollW == clientWidth`（无横向滚动）、控件溢出 0；截图见 `backups/2026-11-17-pre-b5-card-redesign/verify/`。

## 2026-11-17 b7：Topic 画布「子 Agent 边界」改造（按大章节整章增减）

- **问题**：`web/canvas.js` 的 `startRange()` 里，上缘把手只有 `max(140, 卡片宽-216)` 宽（约左半侧），右半侧完全抓不住；且 `avail` 被相邻 Agent 的区间夹住，越过对方的最后一章就被 `blocked` 拦下（提示「相邻章节归其他 Agent 了，先缩小对方的范围才能继续接管」）。用户可感知为「边界无法自由上下移动」。
- **改法（canvas.js）**：
  1. 抓取带贯通整条边：横向树的上/下缘、纵向树的左/右缘都是 `width/height = 卡片全长`，厚 22px、只压进卡片 6px（`INNER=6`），保证卡头「⚙ 配置 / × 删除」仍可点。`widen` 把手补回 `width:24px`（原来靠 CSS 类给宽度，这次一并收敛到行内）。
  2. 去掉相邻 Agent 的区间封锁：`lo/hi` 改为「尾端到末章、首端到首章」，但各留 1 章给自己；拖动可一路接管相邻 Agent 的章节。
  3. `setRange()` 返回「被整段接管后已无章节」的 Agent 并自动移除（同时关闭其配置面板），toast 说明「已接管 X 的全部章节」，不再出现死锁。
  4. 拖动过程实时反馈：卡片外框跟着走、`.tc-sc`/`.tc-nt` 同步显示「第 X–Y 章 / N 个节点」、被纳入章节加 `.preview` 描边、被让出章节 `.dim`、新增 `.tc-badge-range` 黑色胶囊跟随指针显示范围。
- **改法（canvas.css）**：把手常显 84×4 深灰 + 白色描边，悬停时边界线点亮（`::before` 2px）、抓手加深加白光晕；新增 `.tc-badge-range` 样式。
- **交互语义**：大章节（框架里 `##` 级，`framework_node_key` 的第 2 段）是唯一原子单位，拖动一格 = 整章；收缩时让出的章节回「未分配」，不自动送给邻居；接管到邻居清零则移除该 Agent。
- **验证**：`node --check` 通过；用 canvas.js/css + 真实框架数据（VCP 用户手册，6 章 17 节点）做指针事件探针，9 个场景全过——尾端/首端、跨 Agent 接管、整段吃掉（对方移除）、上缘右侧 85% 位置可抓（旧版抓不住）、纵向树左/右缘；命中测试确认上缘全长与下缘全长都落在 `tc-hit` 上而「⚙ 配置」按钮仍是按钮。`tools/test_generation_hardening.py` 14 项全过。
- 资源版本 `v=20261117-b7`；备份 `backups/2026-11-17-pre-b7-canvas-range/`（含 verify 截图与回滚命令），已同步 `~/Applications/炼金炉/web/` 并重启，health 200。

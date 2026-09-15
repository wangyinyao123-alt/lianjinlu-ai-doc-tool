# 阶段 0：XML 样例盘点与生成约束

## 1. 盘点信息

| 项目 | 结果 |
|---|---|
| 样例目录 | `XML素材/` |
| XML 文件数 | 10 个 |
| XML 解析状态 | 10 个均可正常解析 |
| 根元素类型 | `concept` 8 个、`task` 2 个 |
| 特殊场景 | 附录 1 个、Conref 源 1 个 |
| GUID-like Token 总数 | 1125 个 |
| GUID 出现位置 | `id` 属性 764 个、`href` 属性 200 个，另有 XML 文本匹配项 |
| 原始文件处理 | 不修改、不覆盖 |

## 2. 当前样例覆盖情况

| 分类 | 文件数 | 已覆盖结构 |
|---|---:|---|
| Concept 功能说明 | 1 | section、列表、表格、图片、交叉引用、说明内容 |
| Concept 发版说明 | 1 | 多级 section、表格、列表、术语和界面控件 |
| Concept 接口/设备说明 | 1 | 图片、表格、接口说明、合并行 |
| Concept 菜单栏说明 | 1 | 界面控件、菜单级联、参数描述、操作列表 |
| Concept 窗口概览 | 1 | 图片、表格、界面区域说明、交叉引用 |
| Concept 参数说明 | 1 | `parml`、`plentry`、`pt`、`pd`、表格和说明 |
| Task 操作类 | 2 | `prereq`、`steps`、`substeps`、`info`、`postreq`、图片、控件 |
| Conref 源 | 1 | 多级嵌套 `parml`、重复参数、`msgph` |
| 附录类 Concept | 1 | 简单标题和短描述 |

## 3. 当前已识别的主要 XML 结构

### Concept

- `concept`、`title`、`shortdesc`、`conbody`
- `section`、`p`、`ul`、`ol`、`li`
- `table`、`tgroup`、`colspec`、`thead`、`tbody`、`row`、`entry`
- `fig`、`image`
- `note`、`xref`
- `parml`、`plentry`、`pt`、`pd`
- `dl`、`dlentry`、`dt`、`dd`
- `uicontrol`、`msgph`、`parmname`、`codeph`

### Task

- `task`、`title`、`shortdesc`、`taskbody`
- `prereq`、`steps`、`step`、`cmd`
- `substeps`、`substep`
- `info`、`postreq`
- `ul`、`ol`、`li`、`note`
- `fig`、`image`、`xref`
- `uicontrol`、`menucascade`、`userinput`、`cite`
- Task 内嵌参数说明结构

### Conref 与引用

当前已发现 Conref 源文件和大量 `xref`，但还需要确认：

- 是否存在使用这些 Conref 源的正式 Topic 样例；
- 是否使用 `conref`、`conkeyref`、`keyref` 等属性；
- 发布工具对引用目标的具体要求；
- GUID 被移除后，交叉引用和图片引用如何补充目标路径。

## 4. GUID 硬性规则

以下规则由用户确认，作为阶段 0 的强制生成约束：

1. 分析输入时忽略所有 GUID，不将 GUID 的具体值作为结构、风格或命名依据。
2. 生成新 XML 时禁止生成任何 GUID。
3. 生成结果中禁止出现以下形式的 GUID Token：

   ```text
   GUID-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
   GUID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
   ```

4. 禁止在 `id`、`href`、`image/@href`、`xref/@href`、注释、元数据或普通文本中生成 GUID。
5. 不根据输入 GUID 推导、复制或重新组合新的 GUID。
6. 生成前对原始材料进行 GUID 脱敏；生成后对 XML 全文执行 GUID 扫描，命中即判定为不合格。
7. 非 GUID 类型的标识符，例如 `SEC_`、`FIG_`、`IMAGE_`、`TABLE_`、`UL_`、`OL_`，不属于本规则禁止范围，但应按照后续确定的命名规则生成或保留。
8. 已有 Topic 修改时，可以保留非 GUID 标识符；新 Topic 不得生成 GUID 格式的标识符。

建议使用以下检查表达式进行生成后扫描：

```regex
(?i)GUID(?:-|=)[A-Z0-9-]+
```

## 5. GUID 引用的处理策略

当前样例中有大量 `xref/@href` 和 `image/@href` 使用 GUID 作为目标标识。移除 GUID 后不能自动假设新的引用目标，因此默认策略为：

- 不伪造新的 GUID 替代值；
- 不把未知 GUID 转换成随机字符串；
- 对无法解析的交叉引用标记为“待补充引用”，并在校验报告中列出；
- 对图片引用保留图片节点的业务位置，并使用 `href="TODO_IMAGE"` 占位；
- 对交叉引用保留引用节点，并使用 `href="TODO_REF"` 占位；
- 只有用户提供了真实图片路径、Topic 路径或稳定的非 GUID 标识符后，才生成正式引用。

### 已确认的占位符规则

- 图片目标统一使用 `TODO_IMAGE`。
- Topic 或章节交叉引用统一使用 `TODO_REF`。
- 占位符必须在生成结果和校验报告中明确列出。
- XML 中存在 `TODO_IMAGE` 或 `TODO_REF` 时，Topic 状态不能标记为“可发布”。
- 工程师后续手动替换占位符后，重新执行 XML 和引用校验。
- 占位符替换属于人工审核阶段，不由 AI 自动猜测真实路径。

采用占位符可以保持 XML 结构完整，并避免 AI 伪造资源路径。

## 6. Topic 生成模式决策

暂时不使用 `reference` 类型 Topic，也不将其纳入阶段 0 的模板分析和黄金标准集。

当前只保留两个一级生成模式：

### 模式 A：新增 Topic（从 0 编写）

适用场景：没有可复用的上一版本 XML，需要根据需求从头创建 Topic。

输入：

- 已确认的研发需求或产品素材；
- 用户选择的 Topic 类型，目前以 Concept、Task 和附录类 Concept 为主；
- HIK Writing Skill；
- Topic 类型 Skill 或项目专属 Skill；
- 用户补充的 Prompt、术语和约束。

输出：

- Topic 结构建议；
- 正文初稿；
- XML 初稿；
- `TODO_IMAGE`、`TODO_REF` 占位符清单；
- XML 结构和 GUID 禁止规则检查结果。

### 模式 B：Topic 优化

适用场景：已有上一版本 XML，需要根据新需求或优化要求生成新版本。

输入：

- 上一个版本的 XML Code；
- 本次新增需求、修改需求或优化说明；
- 可选的优化 Skill 或优化 Prompt；
- HIK Writing Skill；
- Topic 类型 Skill、项目 Skill 和术语规则。

用户需要选择本次变更类型：

1. **优化版**：基于旧版内容进行修改、重组、补充或删减，保留未变更内容。
2. **功能新增版**：在旧版 Topic 基础上增加新功能、新步骤、新参数或新说明。

输出：

- 变更分析；
- 修改前后差异；
- 优化版或功能新增版 XML；
- 保留、修改、新增和删除内容的标记；
- `TODO_IMAGE`、`TODO_REF` 占位符清单；
- XML 结构、GUID 禁止规则和引用占位符检查结果。

模式 B 的默认规则：

- 旧 XML 中的 GUID 只作为输入中的无效标识，不能复制到输出；
- 非 GUID 标识符在没有结构变化时尽量保留；
- 用户已确认或人工修改的内容不得被自动覆盖；
- AI 不应将普通优化误判为完整重写；
- 生成结果必须支持差异对比和人工回滚。

## 7. 黄金样例集判断

当前 10 个 XML 足以启动第一轮结构提取和模板分析，但还不能代表完整黄金标准集。

当前样例已经较好覆盖：

- Concept 和 Task 两类主要 Topic；
- 操作步骤、参数说明、表格、图片、列表和交叉引用；
- 多级嵌套参数和 Conref 源；
- 简单 Topic、复杂 Topic 和发版说明类 Topic。

建议后续补充以下样例，但暂时不补充 `reference` 类型 Topic：

- 至少 1 个实际使用 Conref/Keyref 的消费方 Topic；
- 至少 1 个包含代码块或较复杂示例的 Topic；
- 至少 2 个功能新增或功能优化前后版本成对样例；
- 至少 1 个无图片、无交叉引用的纯文本简化样例；
- 至少 1 个包含真实资源映射表的 Topic。

## 8. 阶段 0 下一步

1. 为现有 10 个 XML 建立结构指纹和 Topic 类型标签。
2. 对 GUID 做“仅用于分析的脱敏副本”，不改动原始文件。
3. 提取 Concept、Task、参数类和 Conref 类的初版结构模板，不分析 `reference`。
4. 建立新增 Topic 和 Topic 优化两种模式的输入输出数据结构。
5. 建立非 GUID 标识符命名规则。
6. 建立 `TODO_IMAGE`、`TODO_REF` 占位符和生成后 XML 检查规则。
7. 优先验证 GUID 禁止、XML 可解析、基础结构完整性和占位符告警。
8. 补充 Conref 消费方、新增/优化前后样例和真实资源映射样例。
9. 以真实需求材料测试“需求 → Topic 结构 → XML 初稿 → 占位符检查”的最小闭环。

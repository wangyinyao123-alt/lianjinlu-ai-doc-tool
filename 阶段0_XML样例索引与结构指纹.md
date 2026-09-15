# 阶段 0：XML 样例索引与结构指纹

## 1. 样例索引

| 文件 | 分类 | 复杂度 | 主要用途 | 代表结构 |
|---|---|---:|---|---|
| `Concept-功能描述类-抱闸保护功能.xml` | Concept/功能描述 | 高 | 功能说明类 Topic | section、列表、表格、图片、交叉引用、定义列表 |
| `Concept-发版说明-V2.4.0.xml` | Concept/发版说明 | 高 | 版本更新类 Topic | 多级 section、表格、列表、术语、界面控件、交叉引用 |
| `Concept-接口介绍表格类-设备外观和接口介绍.xml` | Concept/接口说明 | 中 | 设备和接口介绍 | 图片、表格、合并行、列表、交叉引用 |
| `Concept-菜单栏介绍.xml` | Concept/界面说明 | 高 | 菜单和控件说明 | `uicontrol`、`menucascade`、参数描述、图片、列表 |
| `Concept-设计窗口概览.xml` | Concept/界面概览 | 中 | 窗口区域说明 | 图片、表格、区域说明、界面控件、交叉引用 |
| `Concept-软件手册参数描述-查看和配置网卡.xml` | Concept/参数说明 | 高 | 参数和状态说明 | `parml`、`plentry`、`pt`、`pd`、定义列表、表格 |
| `Conref源-VM3D模块结果_重复参数引用源.xml` | Concept/Conref 源 | 很高 | 重复参数集中维护 | 多级嵌套 `parml`、重复参数、`msgph` |
| `Task类型-步骤一：新建标定方案（ETH-N图像自动）.xml` | Task/操作步骤 | 高 | 向导式操作 | `steps`、`substeps`、`info`、图片、注意事项、引用 |
| `Task类型-配置N点标定.xml` | Task/操作步骤 | 高 | 带前置条件的操作 | `prereq`、`steps`、`substeps`、参数说明、`postreq` |
| `附录类型-附录C EtherCAT对象字典.xml` | Concept/附录 | 低 | 简单附录入口 | 仅标题和短描述 |

## 2. 结构指纹

### 2.1 Concept 通用骨架

```text
concept
├── title
├── shortdesc
└── conbody
    ├── p / section / list
    ├── table / tgroup / colspec / thead / tbody
    ├── fig / image
    ├── note
    ├── xref
    ├── parml / plentry / pt / pd
    └── dl / dlentry / dt / dd
```

并非每个 Concept 都需要包含全部节点。生成时应根据需求内容选择结构，不能为了匹配样例而强行补齐空节点。

### 2.2 Task 通用骨架

```text
task
├── title
├── shortdesc
└── taskbody
    ├── prereq（可选）
    ├── steps
    │   └── step
    │       ├── cmd
    │       ├── info（可选）
    │       └── substeps（可选）
    └── postreq（可选）
```

Task 生成重点：

- 一步只表达一个主要动作；
- `cmd` 表达动作，`info` 表达补充说明；
- 多个动作需要拆分为多个 `step` 或 `substep`；
- 前置条件放入 `prereq`，完成后的检查或说明放入 `postreq`；
- 图片和注意事项应挂在对应步骤下，不应脱离操作上下文。

### 2.3 参数说明结构

```text
parml
└── plentry
    ├── pt（参数名）
    └── pd（参数说明）
        └── p / parml
```

当前样例中存在以下参数表达特点：

- 一个 `plentry` 可能包含多个 `pt`；
- `pd` 中可能嵌套 `parml`；
- 参数说明中包含 `uicontrol`、`msgph`、`parmname` 等内联元素；
- 部分参数同时通过表格和参数列表表达，需要在生成时避免重复说明。

### 2.4 表格和图片结构

```text
fig
├── title
└── image href="TODO_IMAGE"

table
├── title（可选）
└── tgroup
    ├── colspec × N
    ├── thead
    │   └── row / entry / p
    └── tbody
        └── row / entry / p
```

图片和交叉引用不使用输入样例中的 GUID，统一使用阶段 0 已确认的占位符策略。

### 2.5 Conref 源结构

当前 Conref 样例主要用于集中维护重复参数：

```text
concept
└── conbody
    └── section
        └── parml
            └── plentry
                ├── pt
                └── pd
                    └── parml（可继续嵌套）
```

当前仅分析 Conref 源结构，不推断 GUID 替换后的发布链接，也不将其当作完整的 Topic 输出模板。

## 3. 当前不纳入分析范围

- `reference` 根元素 Topic；
- map、bookmap 和整本手册目录构建；
- 未提供样例的复杂 `keyref`、`conkeyref` 消费方逻辑；
- XML Schema、Schematron 和 DITA-OT 的最终发布校验；
- 真实图片资源路径和跨 Topic 引用映射。

## 4. 结构提取结论

当前 10 个样例可以支撑第一版 Concept、Task、参数说明和 Conref 源的结构模板草案。它们适合用于：

- 生成 Topic 的结构规划；
- 约束 AI 输出的元素类型和嵌套关系；
- 设计 `TODO_IMAGE` 和 `TODO_REF` 的替换位置；
- 建立 GUID 禁止扫描和 XML 可解析性检查。

它们暂时不能支撑：

- Reference 类型 Topic 自动生成；
- 完整 Conref/Keyref 发布关系推断；
- 复杂 XML 发布构建；
- 功能新增和优化模式的准确差异评测。


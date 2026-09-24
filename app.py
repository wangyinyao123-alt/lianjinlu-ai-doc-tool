#!/usr/bin/env python3
"""炼金炉：阶段 1 本地原型服务。

当前范围：
- 本地项目创建、读取和持久化；
- AI 服务配置；
- macOS Keychain / Windows 用户级 DPAPI 中保存 API Key；
- OpenAI 兼容接口 / Anthropic 接口连通性测试；
- 提供浏览器界面，后续可封装为桌面应用。
"""

from __future__ import annotations

import base64
import binascii
import io
import ipaddress
import json
import mimetypes
import posixpath
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile
from xml.sax.saxutils import escape as xml_escape
from urllib.parse import quote, unquote, urlparse


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
PROJECTS_DIR = DATA_DIR / "projects"
SKILLS_DIR = DATA_DIR / "skills"
SETTINGS_FILE = DATA_DIR / "settings.json"
WEB_DIR = ROOT / "web"
EDITORIAL_DIR = WEB_DIR / "assets" / "editorial"
KEYCHAIN_SERVICE = "HIK-炼金炉"
KEYCHAIN_ACCOUNT = "default"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_REQUEST_BYTES = 64 * 1024 * 1024
MAX_MATERIAL_BYTES = 48 * 1024 * 1024
MAX_MATERIAL_TEXT_CHARS = 120_000
MAX_ATTACHMENT_BYTES = 12 * 1024 * 1024
MAX_SKILL_ATTACHMENTS = 20
HIK_SKILL = "HIK Writing Skill"
HIK_DITA_RULE_SKILL = "HIK DITA Rule"
BUILTIN_SKILL_IDS = {"hik-writing", "hik-dita-rule"}
PROJECT_MODES = {"new": "全新开发", "update": "版本更新", "optimize": "Topic 优化"}
TOPIC_TYPES = {"concept": "Concept", "task": "Task", "appendix": "附录类 Concept"}
MATERIAL_TEXT_EXTENSIONS = {
    ".md", ".markdown", ".txt", ".html", ".htm", ".xml", ".json", ".csv", ".yaml", ".yml"
}
MATERIAL_EXTENSIONS = MATERIAL_TEXT_EXTENSIONS | {".doc", ".docx", ".pdf", ".chm", ".xlsx", ".xls"}
GUID_PATTERN = re.compile(r"GUID(?:-|=)[A-Z0-9-]+", re.IGNORECASE)
PLACEHOLDER_PATTERN = re.compile(r"\bTODO_(?:IMAGE|REF)\b")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_dirs() -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def sanitize_text(value: Any) -> str:
    """Keep input content, but never carry GUID-like identifiers into output."""
    text = str(value or "").strip()
    return GUID_PATTERN.sub("TODO_REF", text)


def parse_lines(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = str(value or "").splitlines()
    result: list[str] = []
    for item in raw_items:
        text = sanitize_text(item)
        if text and text not in result:
            result.append(text)
    return result


def parse_outline_items(value: Any) -> list[dict[str, Any]]:
    """Normalize Concept section titles while keeping a small heading tree."""
    raw_items = value if isinstance(value, list) else str(value or "").splitlines()
    result: list[dict[str, Any]] = []
    for item in raw_items:
        if isinstance(item, dict):
            title = sanitize_text(item.get("title", item.get("text", "")))
            raw_level = item.get("level", 1)
        else:
            title = sanitize_text(item)
            raw_level = 1
        if not title:
            continue
        try:
            level = max(1, min(3, int(raw_level)))
        except (TypeError, ValueError):
            level = 1
        result.append({"title": title, "level": level})
    return result


def normalize_skills(value: Any, *, default_dita: bool = False) -> list[str]:
    """Normalize a user-facing Skill selection.

    Writing Skill is always present.  DITA Rule is a default for newly created
    or migrated projects, but it remains removable from an explicit Topic
    override, so it must not be forced here for every request.
    """
    skills = parse_lines(value)
    result = [HIK_SKILL]
    if default_dita or HIK_DITA_RULE_SKILL in skills:
        result.append(HIK_DITA_RULE_SKILL)
    result.extend(skill for skill in skills if skill not in {HIK_SKILL, HIK_DITA_RULE_SKILL})
    return result


def ordered_unique(values: Any) -> list[str]:
    result: list[str] = []
    for value in values if isinstance(values, list) else []:
        name = str(value or "").strip()
        if name and name not in result:
            result.append(name)
    return result


def project_skill_names(project: dict[str, Any], *, default_dita: bool = False) -> list[str]:
    """Return the project-level Skill route in deterministic order."""
    return normalize_skills(project.get("skills", []), default_dita=default_dita)


def resolve_topic_skill_names(
    project: dict[str, Any], selected: Any, inherit_project_skills: bool = True
) -> list[str]:
    """Resolve the effective Skill route for a Topic.

    When inheritance is enabled, the Topic selection is treated as additions
    to the current project route.  This means new project-level Skills flow to
    existing Topics automatically instead of being copied as stale snapshots.
    """
    own = normalize_skills(selected)
    if inherit_project_skills:
        return ordered_unique(project_skill_names(project) + own)
    return own


def topic_skill_overrides(
    project: dict[str, Any], selected: Any, inherit_project_skills: bool = True
) -> list[str]:
    selected_names = [name for name in parse_lines(selected) if name != HIK_SKILL]
    if not inherit_project_skills:
        return [HIK_SKILL] + selected_names
    project_names = set(project_skill_names(project))
    return [name for name in selected_names if name not in project_names]


def skill_usage_snapshot(
    skill_names: Any,
    project: dict[str, Any] | None = None,
    topic_overrides: Any = None,
    inherit_project_skills: bool = True,
) -> list[dict[str, Any]]:
    """Record which Skill version and route contributed to a generation."""
    names = normalize_skills(skill_names)
    project_names = set(project_skill_names(project or {})) if project else set()
    override_names = set(parse_lines(topic_overrides))
    snapshot: list[dict[str, Any]] = []
    for name in names:
        listed = next((item for item in list_skills() if item.get("name") == name), None)
        source = "required" if name == HIK_SKILL else "topic"
        if name != HIK_SKILL and name in project_names:
            source = "project"
        if name in override_names:
            source = "topic"
        snapshot.append(
            {
                "id": listed.get("id") if listed else None,
                "name": name,
                "source": source,
                "inherited": bool(
                    name != HIK_SKILL
                    and inherit_project_skills
                    and name in project_names
                    and name not in override_names
                ),
                "updated_at": listed.get("updated_at") if listed else None,
            }
        )
    return snapshot


DEFAULT_HIK_SKILL_CONTENT = """# HIK Writing Skill

适用于海康机器人中文技术文档和 DITA/XML Topic。生成内容前，先保证业务事实准确，再执行以下规范。

## 1. 通用写作原则

- 从您完成目标出发组织内容，而不是从产品功能出发。
- 默认使用“您”称呼读者，保持客观、中性、技术文档语气。
- 结论先行，中心句放在段落开头。
- 优先使用主动语态，避免双重否定、模糊代词、研发黑话和绝对化表达。
- 句子尽量控制在 40 个字以内。句子过长时拆分。
- 同级标题保持语义结构一致，相关内容按统一标准归类。

## 2. Topic 结构

- Concept 用于功能、原理和背景说明，按“总—分”组织内容。
- Task 用于操作指导，按前置条件、步骤和结果组织内容。
- Reference 用于 FAQ、参数说明和问题排查；当前工具暂不分析 Reference Topic。
- 短描述优先回答 What、When、Why，不重复标题，不放具体步骤、图表、URL 或链接，控制在 3 句以内。
- 前置条件使用“已创建/已执行/已完成 XX”句式，先列必要的先决条件。
- 每个步骤只描述一个操作或决策点。使用“在 XX 位置，单击 XX”的句式。
- Task 步骤至少 2 步，建议不超过 7 步。超过 7 步时按子任务分类。

## 3. 说明和问题排查

- note 用于附加信息、建议或提醒。
- caution 用于可能导致数据丢失或设备损坏的操作。
- danger 仅用于可能造成人员伤亡的高风险场景。
- FAQ 标题使用疑问句并以“？”结尾；一个问题尽量对应一个 Topic。
- 问题排查标题使用陈述句，内容包括问题现象、可能原因和解决方法。解决步骤使用有序列表。

## 4. 界面控件写法

- 鼠标操作统一使用“单击”，不用“点击”；“点击”仅用于移动端触摸操作。
- 窗口写作“进入 XX 窗口”。导航栏直接写导航项名称，不增加“栏目”“界面”等冗余词。
- 页签写作“选择 XX 页签”。文字按钮写作“单击 XX”，不重复“按钮”二字。
- 区域框写作“XX 区域”；下拉列表和复选框直接写名称，不增加“选项”。
- 参数名称全文保持一致。KC/XML 中，按钮、页签、窗口等界面名称使用对应的 `<uicontrol>` 标记。
- 提示信息使用 `<systemoutput>`，用户输入使用 `<userinput>`，参数名称使用 `<parmname>`。

## 5. 标点、数字和单位

- 中文句子使用“。”、“，”、“、”、“；”、“：”和全角括号“（）”。问号“？”仅用于 FAQ。
- 中英文之间通常不额外加空格；数字与计量单位之间空 1 格，例如“25 fps”“8 GB”。
- 使用 × 表示乘法或尺寸，例如“1920 × 1080”；使用 ≤、≥、± 和 ~ 表示范围关系，符号两侧空 1 格。
- 常用单位：帧率 fps，电压 V，速度 m/s，长度 nm/µm/mm/cm/m/km，功率 W/mW，电阻 Ω，电流 mA/A，温度 ℃，内存 TB/GB/MB/KB/B/bit，时间 µs/ms/s/min/h，频率 Hz/kHz，照度 lux，声音强度 dB，色温 K。
- 引用其他章节统一使用“请参见……”。

## 6. DITA/XML 输出约束

- XML 必须保持结构可解析，标签语义不能被随意改写。
- 不生成 GUID、GUID=xxx 或其他 GUID Token。图片使用 `TODO_IMAGE`，引用使用 `TODO_REF`。
- 生成占位符后必须在校验报告中提示，等待人工替换。
- XML 生成后由工程师审核业务准确性、术语一致性、规范合规性和图片引用完整性。

## 7. 输出前自检

- 是否使用“您”，是否统一使用“单击”。
- 是否存在过长句、空泛形容词、绝对化词语或重复标题。
- 是否把操作、说明、结果和注意事项分开组织。
- 是否统一术语、控件名称、标点、数字和单位。
- 是否存在 GUID；是否需要人工替换 `TODO_IMAGE` 或 `TODO_REF`。
"""


DEFAULT_HIK_DITA_RULE_CONTENT = """# HIK DITA Rule

适用于海康 KC（SDL Knowledge Center / Oxygen XML Author）中的 DITA Topic 编写、审核和 XML 生成。生成 XML 前先确认业务事实，再按本规则检查标签语义、嵌套关系和发布约束。

## 1. Topic 类型与基本结构

- Concept 回答“是什么、为什么”，用于功能说明、原理和背景，不写冗长操作步骤。
- Task 回答“怎么做”，必须包含清晰的操作步骤；一个 Task 至少包含 2 个 step。
- Reference 回答“什么值、什么参数或什么调用要求”，用于 FAQ、问题排查和参数参考。当前炼金炉默认不分析 Reference Topic。
- Topic 通常按 `title`、`shortdesc`、正文容器的顺序组织。不要为了补结构而编造产品事实。
- Task 的正文顺序为 `prereq` → `context` → `steps` → `result` → `example` → `postreq`，不能随意调换。

## 2. 文字与段落

- `shortdesc` 位于 `title` 后、正文前，概括 Topic 的用途或主旨；禁止放置 `image` 和 `xref`。
- 块级容器（`note`、`entry`、`li`、`prereq`、`context`、`info`、`result` 等）中的纯文字必须嵌套在 `p` 内。
- 行内标记（`uicontrol`、`parmname`、`userinput`、`sub`、`sup`、`tm`、`cite`、`term`、`xref` 等）应作为句子成分放在 `p` 内，不能脱离段落单独成句。
- 一个 `p` 表达一个中心意思；优先主动语态、结论先行，句子尽量不超过 40 个字。
- 界面文字必须与产品实际显示一致，包括英文大小写；不要擅自改写界面名称。
- 海康文档中鼠标操作统一使用“单击”，读者称呼使用“您”。

## 3. Concept、section 和标题

- Concept 可在 `conbody` 中使用 `section` 分节；`section` 必须包含 `title`，不要把 section 用在 Task 中。
- 有明确子主题、需要复用或链接、内容超过三四个段落时再增加 section；短小连贯的内容不强行拆分。
- Task 标题采用动宾结构，例如“设置校准方案”，避免使用“校准方案设置”。
- 同级标题保持语义和句式一致，避免仅有一个没有必要的子节。

## 4. 常用行内标记

- `uicontrol`：按钮、菜单、页签、导航栏等交互控件，通常与“单击”“选择”搭配。
- `parmname`：参数项或配置项名称，不表示需要单击的对象。
- `userinput`：用户输入的 IP、文件名、命令、参数值等内容。
- `menucascade`：两级及以上的菜单路径，至少包含两个 `uicontrol`。
- `xref`：Topic、section、fig、table 或外部 URL 的交叉引用。优先链接 Topic 层级，并使用“请参见……”引出。
- `codeph`：单行短代码或命令；多行代码使用 `codeblock`；API 名称使用 `apiname`。
- `sup` 和 `sub` 仅用于上标、下标、单位和变量编号；商标使用 `tm`，不要用 `sup` 模拟商标。
- `cite` 只标记资料名称，不承载链接；中文资料的书名号放在 `cite` 内部。
- `term` 仅在术语首次出现或需要重点说明时使用，全文术语保持一致。

## 5. 列表、表格和说明

- 无键值关系的有序内容使用 `ol`，无序内容使用 `ul`；参数与参数说明使用 `parml` 或 `dl`，不要用 `ul` 堆叠 `parmname`。
- `ol`、`ul` 至少包含 2 个 `li`；列表不宜过深，子级列表必须隶属直接父级。
- `note` 用于补充说明、建议或提醒；风险提示使用 `caution` 或 `warning`，高风险场景才使用 `danger`。`note` 内文字必须放在 `p` 中，不写操作步骤，不嵌套 note。
- `table` 的标题放在 `title` 中，内容放在 `tgroup` 中；`entry` 内所有文字必须嵌套 `p`。`colspec` 定义的列数必须与实际列数一致。
- 不建议使用 `simpletable`。跨行使用 `morerows`，跨列使用 `namest` 和 `nameend`。

## 6. Task 步骤

- `steps` 是 Task 的核心容器，每个 `step` 必须包含 `cmd`；`cmd` 只写一个操作动作，不写结果。
- 操作补充信息放在 `info`，单步结果放在 `stepresult`，整个任务结果放在 `result`。
- 步骤一般不超过 7 步；复杂流程用 `substeps` 或拆分 Topic。`substeps` 至少包含 2 个子步骤。
- 前置条件描述用户开始任务前必须满足的状态，不写成操作动作；若必须执行动作，应改为第一个 step。
- 互斥选项使用 `choices`，可选操作使用 `choicetable`；两者都至少包含 2 个选项。

## 7. 图片、引用和 XML 安全

- 图片一般使用 `fig` 包含 `title` 和 `image`；图标可单独使用 `image`。图片须从 KC Repository 引用，不直接加载本地路径。
- 图片使用白色背景，尺寸属性在 `Width`、`Height`、`Scale` 中选择一种。
- 本工具生成的图片使用 `TODO_IMAGE`，引用使用 `TODO_REF`；生成时不写 GUID，校验报告提示人工替换占位符。
- XML 中的 `<`、`>`、`&` 分别转义为 `&lt;`、`&gt;`、`&amp;`。属性值和 ID 必须唯一且符合项目约束。
- 条件内容使用 KC 已配置的 `ishcondition`；不要手动创建不存在的 condition。
- 可复用内容放入 conref 源 Topic，引用前确认源 Topic 已 check in；不要随意修改源 Topic 中其他复用内容。

## 8. 生成后自查

1. 是否包含必要的 `shortdesc`，其中是否误用 `image` 或 `xref`。
2. `note`、`entry`、`info`、`result` 等块级容器中的文字是否正确嵌套 `p`。
3. Topic 类型、标题句式和正文结构是否匹配。
4. Task 是否按固定顺序组织，步骤是否至少 2 步且每步只描述一个动作。
5. 表格列数、列表层级、引用目标和标记对嵌套是否正确。
6. 是否存在 GUID；`TODO_IMAGE` 和 `TODO_REF` 是否已在后续审核中替换。
7. 是否通过 XML 解析、KC 发布规则、术语一致性和业务准确性检查。
"""


def skill_path(skill_id: str) -> Path:
    if "/" in skill_id or "\\" in skill_id or skill_id in {"", ".", ".."}:
        raise ValueError("无效的 Skill ID。")
    return SKILLS_DIR / f"{skill_id}.json"


def skill_attachment_dir(skill_id: str) -> Path:
    skill_path(skill_id)
    directory = SKILLS_DIR / skill_id / "attachments"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def attachment_metadata(skill: dict[str, Any], attachment: dict[str, Any]) -> dict[str, Any]:
    attachment_id = str(attachment.get("id", ""))
    return {
        "id": attachment_id,
        "name": str(attachment.get("name", "附件")),
        "mime_type": str(attachment.get("mime_type", "application/octet-stream")),
        "size": int(attachment.get("size", 0) or 0),
        "created_at": attachment.get("created_at"),
        "download_url": f"/api/skills/{quote(str(skill.get('id', '')))}/attachments/{quote(attachment_id)}",
    }


def decode_attachment(item: dict[str, Any]) -> tuple[str, str, bytes]:
    name = Path(str(item.get("name", "附件"))).name or "附件"
    data_url = str(item.get("data_url", ""))
    prefix, separator, encoded = data_url.partition(",")
    if separator != "," or ";base64" not in prefix:
        raise ValueError(f"附件“{name}”格式无效。")
    mime_type = prefix[5:].split(";", 1)[0].lower() or "application/octet-stream"
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError(f"附件“{name}”无法读取。") from exc
    if not raw:
        raise ValueError(f"附件“{name}”不能为空。")
    if len(raw) > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"附件“{name}”不能超过 {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB。")
    return name[:160], mime_type, raw


def store_skill_attachments(skill: dict[str, Any], requested: Any) -> list[dict[str, Any]]:
    if not isinstance(requested, list):
        raise ValueError("Skill 附件数据格式无效。")
    if len(requested) > MAX_SKILL_ATTACHMENTS:
        raise ValueError(f"每个 Skill 最多支持 {MAX_SKILL_ATTACHMENTS} 个附件。")
    skill_id = str(skill["id"])
    directory = skill_attachment_dir(skill_id)
    existing = {str(item.get("id")): item for item in skill.get("attachments", []) if isinstance(item, dict)}
    kept_ids: set[str] = set()
    stored: list[dict[str, Any]] = []
    total_size = 0
    for item in requested:
        if not isinstance(item, dict):
            continue
        attachment_id = str(item.get("id", ""))
        if attachment_id and attachment_id in existing:
            record = existing[attachment_id]
            file_name = Path(str(record.get("file", ""))).name
            if (directory / file_name).is_file():
                stored.append(record)
                kept_ids.add(attachment_id)
                total_size += int(record.get("size", 0) or 0)
            continue
        name, mime_type, raw = decode_attachment(item)
        attachment_id = f"attachment_{int(time.time())}_{secrets.token_hex(3)}"
        file_name = f"{attachment_id}{Path(name).suffix.lower()}"
        (directory / file_name).write_bytes(raw)
        record = {
            "id": attachment_id,
            "name": name,
            "mime_type": mime_type or mimetypes.guess_type(name)[0] or "application/octet-stream",
            "size": len(raw),
            "file": file_name,
            "created_at": now_iso(),
        }
        stored.append(record)
        kept_ids.add(attachment_id)
        total_size += len(raw)
        if total_size > MAX_SKILL_ATTACHMENTS * MAX_ATTACHMENT_BYTES:
            raise ValueError(f"Skill 附件总大小不能超过 {MAX_SKILL_ATTACHMENTS * MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB。")
    for attachment_id, record in existing.items():
        if attachment_id not in kept_ids:
            old_file = directory / Path(str(record.get("file", ""))).name
            if old_file.is_file():
                old_file.unlink()
    return stored


def builtin_skill_override_path(skill_id: str) -> Path:
    if skill_id not in BUILTIN_SKILL_IDS:
        raise ValueError("无效的内置 Skill ID。")
    return SKILLS_DIR / f"builtin_{skill_id}.json"


def apply_builtin_skill_override(default: dict[str, Any]) -> dict[str, Any]:
    override = read_json(builtin_skill_override_path(str(default["id"])), None)
    if not isinstance(override, dict):
        return default
    merged = {**default, **override}
    merged["id"] = default["id"]
    merged["name"] = default["name"]
    merged["source"] = "builtin"
    merged["required"] = default["required"]
    merged["attachments"] = override.get("attachments", default.get("attachments", []))
    return merged


def builtin_hik_skill() -> dict[str, Any]:
    return apply_builtin_skill_override({
        "id": "hik-writing",
        "name": HIK_SKILL,
        "description": "海康机器人中文技术文档与 DITA/XML 写作规范。",
        "content": DEFAULT_HIK_SKILL_CONTENT,
        "source": "builtin",
        "required": True,
        "enabled": True,
        "attachments": [],
        "created_at": None,
        "updated_at": None,
    })


def builtin_hik_dita_rule_skill() -> dict[str, Any]:
    return apply_builtin_skill_override({
        "id": "hik-dita-rule",
        "name": HIK_DITA_RULE_SKILL,
        "description": "海康 KC / Oxygen XML Author 的 DITA Topic 标记对、结构和发布规则。",
        "content": DEFAULT_HIK_DITA_RULE_CONTENT,
        "source": "builtin",
        "required": False,
        "enabled": True,
        "attachments": [],
        "created_at": None,
        "updated_at": None,
    })


def skill_summary(skill: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(skill.get("id", "")),
        "name": sanitize_text(skill.get("name")),
        "description": sanitize_text(skill.get("description")),
        "content": str(skill.get("content", "")),
        "source": str(skill.get("source", "custom")),
        "required": bool(skill.get("required", False)),
        "enabled": bool(skill.get("enabled", True)),
        "attachments": [attachment_metadata(skill, item) for item in skill.get("attachments", []) if isinstance(item, dict)],
        "created_at": skill.get("created_at"),
        "updated_at": skill.get("updated_at"),
    }


def list_skills() -> list[dict[str, Any]]:
    result = [skill_summary(builtin_hik_skill()), skill_summary(builtin_hik_dita_rule_skill())]
    if SKILLS_DIR.exists():
        for path in sorted(SKILLS_DIR.glob("skill_*.json"), key=lambda item: item.name.lower()):
            skill = read_json(path, None)
            if isinstance(skill, dict) and skill.get("id") and skill.get("name"):
                result.append(skill_summary(skill))
    return result


def get_skill_record(skill_id: str) -> dict[str, Any] | None:
    if skill_id == "hik-writing":
        return builtin_hik_skill()
    if skill_id == "hik-dita-rule":
        return builtin_hik_dita_rule_skill()
    skill = read_json(skill_path(skill_id), None)
    return skill if isinstance(skill, dict) else None


def get_skill_attachment_file(skill_id: str, attachment_id: str) -> tuple[Path, str] | None:
    skill = get_skill_record(skill_id)
    if not skill:
        return None
    for attachment in skill.get("attachments", []):
        if isinstance(attachment, dict) and str(attachment.get("id")) == attachment_id:
            file_name = Path(str(attachment.get("file", ""))).name
            path = skill_attachment_dir(skill_id) / file_name
            return path, str(attachment.get("mime_type", "application/octet-stream"))
    return None


def create_skill(payload: dict[str, Any]) -> dict[str, Any]:
    name = sanitize_text(payload.get("name"))
    content = str(payload.get("content", "")).strip()
    if not name:
        raise ValueError("Skill 名称不能为空。")
    if name == HIK_SKILL:
        raise ValueError("HIK Writing Skill 已内置且为必选 Skill。")
    if not content:
        raise ValueError("Skill 内容不能为空。")
    if any(item["name"].casefold() == name.casefold() for item in list_skills()):
        raise ValueError("已存在同名 Skill，请修改名称。")
    timestamp = now_iso()
    skill = {
        "id": f"skill_{int(time.time())}_{secrets.token_hex(3)}",
        "name": name[:120],
        "description": sanitize_text(payload.get("description"))[:240],
        "content": content[:2_000_000],
        "source": "custom",
        "required": False,
        "enabled": bool(payload.get("enabled", True)),
        "attachments": [],
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    skill["attachments"] = store_skill_attachments(skill, payload.get("attachments", []))
    write_json(skill_path(skill["id"]), skill)
    return skill_summary(skill)


def update_skill(skill_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if skill_id in BUILTIN_SKILL_IDS:
        current = get_skill_record(skill_id)
        if not current:
            raise ValueError("Skill 不存在。")
        content = str(payload.get("content", current.get("content", ""))).strip()
        if not content:
            raise ValueError("Skill 内容不能为空。")
        updated = {
            **current,
            "description": sanitize_text(payload.get("description", current.get("description", "")))[:240],
            "content": content[:2_000_000],
            "enabled": True if current.get("required") else bool(payload.get("enabled", current.get("enabled", True))),
            "updated_at": now_iso(),
        }
        if "attachments" in payload:
            updated["attachments"] = store_skill_attachments(updated, payload["attachments"])
        write_json(builtin_skill_override_path(skill_id), {
            "description": updated["description"],
            "content": updated["content"],
            "enabled": updated["enabled"],
            "attachments": updated.get("attachments", []),
            "updated_at": updated["updated_at"],
        })
        return skill_summary(updated)
    path = skill_path(skill_id)
    skill = read_json(path, None)
    if not isinstance(skill, dict):
        raise ValueError("Skill 不存在。")
    name = sanitize_text(payload.get("name", skill.get("name")))
    content = str(payload.get("content", skill.get("content", ""))).strip()
    if not name or not content:
        raise ValueError("Skill 名称和内容不能为空。")
    if any(
        item["id"] != skill_id and item["name"].casefold() == name.casefold()
        for item in list_skills()
    ):
        raise ValueError("已存在同名 Skill，请修改名称。")
    skill.update(
        {
            "name": name[:120],
            "description": sanitize_text(payload.get("description", skill.get("description")))[:240],
            "content": content[:2_000_000],
            "enabled": bool(payload.get("enabled", skill.get("enabled", True))),
            "updated_at": now_iso(),
        }
    )
    if "attachments" in payload:
        skill["attachments"] = store_skill_attachments(skill, payload["attachments"])
    write_json(path, skill)
    return skill_summary(skill)


def delete_skill(skill_id: str) -> None:
    if skill_id in BUILTIN_SKILL_IDS:
        raise ValueError("内置 Skill 不支持删除。")
    path = skill_path(skill_id)
    if not path.exists():
        raise ValueError("Skill 不存在。")
    path.unlink()


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "_", value).strip("_")
    return cleaned[:48] or "UNTITLED"


def image_content_type(path: Path) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(path.suffix.lower(), "application/octet-stream")


def list_editorial_assets() -> list[dict[str, str]]:
    """Read the current image files so users can replace the material wall freely."""
    if not EDITORIAL_DIR.exists():
        return []
    files = sorted(
        (path for path in EDITORIAL_DIR.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS),
        key=lambda path: (path.stem.lower(), path.name.lower()),
    )
    assets = []
    for index, path in enumerate(files, start=1):
        cache_key = path.stat().st_mtime_ns
        stem = path.stem.replace("-editorial", "").replace("_", " ").strip()
        label = f"MATERIAL {int(stem):02d}" if stem.isdigit() else (stem.upper() or f"MATERIAL {index:02d}")
        assets.append(
            {
                "file": path.name,
                "label": label,
                "note": f"{index:02d} / MATERIAL",
                "url": f"/static/assets/editorial/{quote(path.name)}?v={cache_key}",
            }
        )
    return assets


def default_cover() -> dict[str, str] | None:
    assets = list_editorial_assets()
    if not assets:
        return None
    return {"type": "asset", "file": assets[0]["file"]}


def save_project_cover(payload: Any, directory: Path) -> dict[str, str] | None:
    """Validate a selected material or save a local image as the project cover."""
    cover = payload if isinstance(payload, dict) else None
    cover_type = str(cover.get("type", "asset")) if cover else "asset"
    if cover_type == "asset":
        file_name = Path(str(cover.get("file", ""))).name if cover else ""
        source_path = EDITORIAL_DIR / file_name
        valid_files = {asset["file"] for asset in list_editorial_assets()}
        if file_name not in valid_files or not source_path.is_file():
            fallback = default_cover()
            if not fallback:
                return None
            file_name = fallback["file"]
            source_path = EDITORIAL_DIR / file_name
        stored_file = directory / f"cover{source_path.suffix.lower()}"
        shutil.copy2(source_path, stored_file)
        return {"type": "asset", "file": stored_file.name, "source_file": file_name}

    if cover_type != "upload":
        raise ValueError("不支持的项目封面类型。")
    data_url = str(cover.get("data_url", ""))
    prefix, separator, encoded = data_url.partition(",")
    if separator != "," or ";base64" not in prefix:
        raise ValueError("项目封面格式无效，请重新选择图片。")
    mime_type = prefix[5:].split(";", 1)[0].lower()
    extension = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(mime_type)
    if not extension:
        raise ValueError("项目封面仅支持 JPG、PNG、WEBP 或 GIF 图片。")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError("项目封面数据无法读取，请重新选择图片。") from exc
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("项目封面大小不能超过 8 MB。")
    file_path = directory / f"cover{extension}"
    file_path.write_bytes(raw)
    return {"type": "upload", "file": file_path.name, "name": str(cover.get("name", file_path.name))[:160]}


def default_settings() -> dict[str, Any]:
    return {
        "provider": "openai-compatible",
        "base_url": "",
        "model": "",
        "temperature": 0.2,
        "timeout_seconds": 60,
        "updated_at": None,
    }


def load_settings() -> dict[str, Any]:
    settings = default_settings()
    settings.update(read_json(SETTINGS_FILE, {}))
    return settings


class KeychainStore:
    """Use a native, user-bound credential store on macOS and Windows.

    Windows previously used a hand-written Credential Manager ctypes structure.
    That path can fail on some Python/Windows combinations with the opaque
    ``class must define a 'type' attribute`` error. Windows DPAPI provides the
    same user-bound protection without depending on that structure layout.
    """

    def __init__(self) -> None:
        if sys.platform == "darwin" and shutil.which("security") is not None:
            self.backend = "macOS Keychain"
        elif sys.platform == "win32":
            self.backend = "Windows DPAPI（当前用户）"
        else:
            self.backend = None
        self.available = bool(self.backend)

    @property
    def _windows_secret_path(self) -> Path:
        return DATA_DIR / ".api-key.dpapi"

    def _windows_dpapi_api(self):
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
            ]

        crypt = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
        kernel = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
        crypt.CryptProtectData.argtypes = [
            ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR,
            ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(DATA_BLOB),
        ]
        crypt.CryptProtectData.restype = wintypes.BOOL
        crypt.CryptUnprotectData.argtypes = [
            ctypes.POINTER(DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(DATA_BLOB),
        ]
        crypt.CryptUnprotectData.restype = wintypes.BOOL
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        return ctypes, DATA_BLOB, crypt, kernel

    def _windows_dpapi_protect(self, value: str) -> bytes:
        ctypes, data_blob, crypt, kernel = self._windows_dpapi_api()
        raw = value.encode("utf-8")
        source_buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        source = data_blob(len(raw), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
        protected = data_blob()
        description = "炼金炉 API Key"
        if not crypt.CryptProtectData(ctypes.byref(source), description, None, None, None, 0, ctypes.byref(protected)):
            error = ctypes.get_last_error()
            raise RuntimeError(f"Windows 用户凭据保护失败（错误码 {error}）。")
        try:
            return ctypes.string_at(protected.pbData, protected.cbData)
        finally:
            kernel.LocalFree(protected.pbData)

    def _windows_dpapi_unprotect(self, value: bytes) -> str | None:
        ctypes, data_blob, crypt, kernel = self._windows_dpapi_api()
        if not value:
            return None
        source_buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
        source = data_blob(len(value), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
        unprotected = data_blob()
        if not crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(unprotected)):
            error = ctypes.get_last_error()
            raise RuntimeError(f"Windows 用户凭据读取失败（错误码 {error}）。")
        try:
            raw = ctypes.string_at(unprotected.pbData, unprotected.cbData)
            return raw.decode("utf-8") or None
        finally:
            kernel.LocalFree(unprotected.pbData)

    def _windows_api(self):
        import ctypes
        from ctypes import wintypes

        class CREDENTIALW(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]

        api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
        api.CredReadW.restype = wintypes.BOOL
        api.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
        api.CredWriteW.restype = wintypes.BOOL
        api.CredFree.argtypes = [ctypes.c_void_p]
        api.CredFree.restype = None
        return ctypes, CREDENTIALW, api

    def _windows_target(self) -> str:
        return f"{KEYCHAIN_SERVICE}/{KEYCHAIN_ACCOUNT}"

    def get(self) -> str | None:
        if not self.available:
            return None
        if sys.platform == "win32":
            try:
                path = self._windows_secret_path
                if path.is_file():
                    return self._windows_dpapi_unprotect(path.read_bytes())
            except (OSError, RuntimeError, UnicodeError):
                return None
            # Compatibility read for packages created before the DPAPI change.
            try:
                ctypes, credential_type, api = self._windows_api()
                pointer = ctypes.POINTER(credential_type)()
                if not api.CredReadW(self._windows_target(), 1, 0, ctypes.byref(pointer)):
                    return None
                try:
                    credential = pointer.contents
                    raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
                    return raw.decode("utf-8") or None
                finally:
                    api.CredFree(pointer)
            except (OSError, RuntimeError, UnicodeError):
                return None
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-a",
                KEYCHAIN_ACCOUNT,
                "-s",
                KEYCHAIN_SERVICE,
                "-w",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return None
        value = result.stdout.strip()
        return value or None

    def save(self, value: str) -> None:
        if not self.available:
            raise RuntimeError("当前系统未检测到可用的系统凭据存储，暂不保存 API Key。")
        if sys.platform == "win32":
            protected = self._windows_dpapi_protect(value)
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            temporary = self._windows_secret_path.with_suffix(".dpapi.tmp")
            temporary.write_bytes(protected)
            temporary.replace(self._windows_secret_path)
            return
        result = subprocess.run(
            [
                "security",
                "add-generic-password",
                "-U",
                "-a",
                KEYCHAIN_ACCOUNT,
                "-s",
                KEYCHAIN_SERVICE,
                "-w",
                value,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            message = result.stderr.strip() or "写入 macOS Keychain 失败。"
            raise RuntimeError(message)


KEYCHAIN = KeychainStore()


def public_settings() -> dict[str, Any]:
    settings = load_settings()
    settings["api_key_configured"] = bool(KEYCHAIN.get())
    settings["key_storage"] = KEYCHAIN.backend or "不可用"
    return settings


def new_project_id() -> str:
    # Project IDs intentionally use a local non-GUID format.
    return f"proj_{int(time.time())}_{secrets.token_hex(4)}"


def project_dir(project_id: str) -> Path:
    if "/" in project_id or "\\" in project_id or project_id in {"", ".", ".."}:
        raise ValueError("无效的项目 ID。")
    return PROJECTS_DIR / project_id


def normalize_project_mode(value: Any) -> str:
    mode = str(value or "new").strip().lower()
    return mode if mode in PROJECT_MODES else "new"


def normalize_project_ids(value: Any, exclude: str = "") -> list[str]:
    raw = value if isinstance(value, list) else parse_lines(value)
    result: list[str] = []
    for item in raw:
        project_id = str(item or "").strip()
        if project_id and project_id != exclude and project_id not in result:
            result.append(project_id)
    return result


def topics_dir(project_id: str) -> Path:
    return project_dir(project_id) / "topics"


def topic_dir(project_id: str, topic_id: str) -> Path:
    if "/" in topic_id or "\\" in topic_id or topic_id in {"", ".", ".."}:
        raise ValueError("无效的 Topic ID。")
    return topics_dir(project_id) / topic_id


def material_dir(project_id: str, material_id: str) -> Path:
    if "/" in material_id or "\\" in material_id or material_id in {"", ".", ".."}:
        raise ValueError("无效的材料 ID。")
    return project_dir(project_id) / "materials" / material_id


class PlainTextHTMLParser(HTMLParser):
    """Extract readable text without bringing HTML tags into the AI context."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "template"}:
            self.skip_depth += 1
        elif self.skip_depth == 0 and tag.lower() in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "template"} and self.skip_depth:
            self.skip_depth -= 1
        elif self.skip_depth == 0 and tag.lower() in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth == 0 and data.strip():
            self.parts.append(data)


def compact_extracted_text(value: str) -> tuple[str, bool]:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in str(value or "").splitlines()]
    text = "\n".join(line for line in lines if line)
    truncated = len(text) > MAX_MATERIAL_TEXT_CHARS
    return text[:MAX_MATERIAL_TEXT_CHARS], truncated


def extract_material_text(path: Path) -> tuple[str, str, str]:
    """Return extracted text, status, and a user-facing extraction message."""
    extension = path.suffix.lower()
    try:
        if extension in MATERIAL_TEXT_EXTENSIONS:
            raw = path.read_text(encoding="utf-8", errors="replace")
            if extension in {".html", ".htm"}:
                parser = PlainTextHTMLParser()
                parser.feed(raw)
                raw = "".join(parser.parts)
            text, truncated = compact_extracted_text(raw)
            message = "文本已提取。"
            if truncated:
                message = f"文本已提取，超过 {MAX_MATERIAL_TEXT_CHARS:,} 字符的部分未送入 AI。"
            return text, "success", message

        if extension in {".xlsx", ".xls"}:
            if extension == ".xls":
                return "", "unsupported", "旧版 .xls 暂不支持自动读取，请另存为 .xlsx 后导入。"
            text, sheet_name = extract_xlsx_framework(path.read_bytes())
            if not text:
                return "", "failed", "Excel 中未找到可识别的框架页签或内容。"
            return text, "success", f"已识别 Excel 页签“{sheet_name}”，并转换为 Markdown。"

        if extension == ".docx":
            with ZipFile(path) as archive:
                document_xml = archive.read("word/document.xml")
            root = ET.fromstring(document_xml)
            paragraphs = []
            for node in root.iter():
                if node.tag.endswith("}p"):
                    paragraph = "".join(node.itertext()).strip()
                    if paragraph:
                        paragraphs.append(paragraph)
            text, truncated = compact_extracted_text("\n".join(paragraphs))
            message = "Word 文本已提取。"
            if truncated:
                message = f"Word 文本已提取，超过 {MAX_MATERIAL_TEXT_CHARS:,} 字符的部分未送入 AI。"
            return text, "success", message

        if extension == ".doc":
            executable = shutil.which("textutil")
            if not executable:
                return "", "unsupported", "未检测到 macOS textutil，已保留旧版 Word 原文件，暂未提取文本。"
            result = subprocess.run(
                [executable, "-convert", "txt", "-stdout", str(path)],
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
            if result.returncode != 0:
                return "", "failed", f"旧版 Word 文本提取失败：{result.stderr.strip()[:240]}"
            text, truncated = compact_extracted_text(result.stdout)
            message = "旧版 Word 文本已提取。"
            if truncated:
                message = f"旧版 Word 文本已提取，超过 {MAX_MATERIAL_TEXT_CHARS:,} 字符的部分未送入 AI。"
            return text, "success", message

        if extension == ".pdf":
            executable = shutil.which("pdftotext")
            if not executable:
                return "", "unsupported", "未检测到 pdftotext，已保留 PDF 原文件，暂未提取文本。"
            result = subprocess.run(
                [executable, "-layout", str(path), "-"],
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
            if result.returncode != 0:
                return "", "failed", f"PDF 文本提取失败：{result.stderr.strip()[:240]}"
            text, truncated = compact_extracted_text(result.stdout)
            message = "PDF 文本已提取。"
            if truncated:
                message = f"PDF 文本已提取，超过 {MAX_MATERIAL_TEXT_CHARS:,} 字符的部分未送入 AI。"
            return text, "success", message

        if extension == ".chm":
            executable = shutil.which("extract_chmLib")
            if not executable:
                return "", "unsupported", "未检测到 CHM 解析工具，已保留 CHM 原文件，暂未提取文本。"
            with tempfile.TemporaryDirectory(prefix="lianjinlu_chm_") as temp_dir:
                result = subprocess.run(
                    [executable, str(path), temp_dir],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
                if result.returncode != 0:
                    return "", "failed", f"CHM 文本提取失败：{result.stderr.strip()[:240]}"
                chunks: list[str] = []
                for extracted_path in sorted(Path(temp_dir).rglob("*")):
                    if extracted_path.is_file() and extracted_path.suffix.lower() in {".html", ".htm", ".txt", ".md"}:
                        try:
                            raw = extracted_path.read_text(encoding="utf-8", errors="replace")
                        except OSError:
                            continue
                        if extracted_path.suffix.lower() in {".html", ".htm"}:
                            parser = PlainTextHTMLParser()
                            parser.feed(raw)
                            raw = "".join(parser.parts)
                        if raw.strip():
                            chunks.append(raw)
                text, truncated = compact_extracted_text("\n\n".join(chunks))
                if not text:
                    return "", "failed", "CHM 已解包，但未找到可读取的 HTML 或文本内容。"
                message = "CHM 文本已提取。"
                if truncated:
                    message = f"CHM 文本已提取，超过 {MAX_MATERIAL_TEXT_CHARS:,} 字符的部分未送入 AI。"
                return text, "success", message

        return "", "unsupported", f"暂不支持直接提取 {extension or '该格式'} 文本，已保留原文件。"
    except (OSError, BadZipFile, ET.ParseError, subprocess.TimeoutExpired) as exc:
        return "", "failed", f"材料读取失败：{str(exc)[:240]}"


def excel_column_index(reference: str) -> int:
    """Return a zero-based Excel column index from a cell reference."""
    match = re.match(r"^([A-Z]+)", str(reference or "").upper())
    if not match:
        return 0
    result = 0
    for char in match.group(1):
        result = result * 26 + ord(char) - ord("A") + 1
    return max(0, result - 1)


def normalize_excel_label(value: Any) -> str:
    return re.sub(r"[\s_\-：:（）()\[\]【】]+", "", str(value or "").strip().lower())


def excel_outline_level(title: str) -> int | None:
    """Infer outline depth from common Chinese/Arabic chapter numbering."""
    value = str(title or "").strip()
    if re.match(r"^(第[一二三四五六七八九十百\d]+章|附录(?:[A-Za-z一二三四五六七八九十\d]+)?)", value):
        return 1
    if re.match(r"^[一二三四五六七八九十百]+、", value):
        return 1
    if re.match(r"^[（(][一二三四五六七八九十百]+[）)]", value):
        return 2
    match = re.match(r"^(\d+(?:[.．]\d+)*)(?:[、.．)）]|\s|$)", value)
    if match:
        return min(6, max(1, len(re.split(r"[.．]", match.group(1)))))
    return None


def excel_level_value(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"(?:第\s*)?(\d+|[一二三四五六七八九十百]+)\s*(?:级|层)?", text)
    if not match:
        return None
    token = match.group(1)
    if token.isdigit():
        return min(6, max(1, int(token)))
    chinese = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    return min(6, max(1, chinese.get(token, 1)))


def excel_hierarchy_level(label: Any) -> int | None:
    """Recognize columns such as Map, 一级目录, 二级标题, or Level 3."""
    normalized = normalize_excel_label(label)
    if normalized in {"map", "root", "文档", "文档标题"}:
        return 1
    match = re.match(r"^(\d+|[一二三四五六七八九十百]+)(?:级|层)(?:目录|标题|节点)?$", normalized)
    if not match:
        return None
    token = match.group(1)
    if token.isdigit():
        return min(6, max(1, int(token)))
    chinese = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    return min(6, max(1, chinese.get(token, 1)))


def extract_xlsx_framework(raw: bytes) -> tuple[str, str]:
    """Select the best outline sheet and convert it to a rooted Markdown tree."""
    with ZipFile(io.BytesIO(raw)) as archive:
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
        names = set(archive.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.itertext()).strip() for node in root.findall("m:si", ns)]
        wb = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relmap = {item.attrib.get("Id"): item.attrib.get("Target", "") for item in rels}
        candidates: list[tuple[str, str]] = []
        for sheet in wb.findall("m:sheets/m:sheet", ns):
            name = sheet.attrib.get("name", "")
            target = relmap.get(sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"), "")
            target = posixpath.normpath(posixpath.join("xl", target.lstrip("/")))
            if target in names:
                candidates.append((name, target))

        title_labels = {"标题", "章节标题", "章节名称", "topic", "title", "名称", "目录", "章节", "文档结构", "outline"}
        number_labels = {"序号", "编号", "章节编号", "章节序号", "no", "no.", "id"}
        level_labels = {"层级", "级别", "level", "headinglevel", "标题级别", "层级关系"}
        summary_labels = {"章节概述", "概述", "短描述", "shortdesc", "summary", "说明", "描述", "内容"}
        sheet_results: list[tuple[int, str, list[tuple[str, int, str]]]] = []

        for sheet_order, (name, target) in enumerate(candidates):
            sheet_root = ET.fromstring(archive.read(target))
            rows: list[tuple[dict[int, str], int]] = []
            for row in sheet_root.findall(".//m:sheetData/m:row", ns):
                row_values: dict[int, str] = {}
                next_col = 0
                for cell in row.findall("m:c", ns):
                    col = excel_column_index(cell.attrib.get("r", "")) if cell.attrib.get("r") else next_col
                    value_node = cell.find("m:v", ns)
                    value = "" if value_node is None else value_node.text or ""
                    if cell.attrib.get("t") == "inlineStr":
                        value = "".join(cell.itertext()).strip()
                    elif cell.attrib.get("t") == "s" and value.isdigit() and int(value) < len(shared):
                        value = shared[int(value)]
                    elif cell.attrib.get("t") == "b":
                        value = "是" if value == "1" else "否"
                    value = re.sub(r"\s+", " ", str(value or "").strip())
                    if value:
                        row_values[col] = value
                    next_col = col + 1
                if row_values:
                    row_number = int(row.attrib.get("r", len(rows) + 1))
                    rows.append((row_values, row_number))
            if not rows:
                continue

            header_row_index = -1
            header: dict[str, Any] = {}
            best_header_score = 0
            for index, (row, _) in enumerate(rows[:25]):
                labels = {normalize_excel_label(value): col for col, value in row.items()}
                hierarchy_columns = {col: level for label, col in labels.items() if (level := excel_hierarchy_level(label)) is not None}
                score = sum(1 for label in labels if label in title_labels or label in number_labels or label in level_labels or label in summary_labels) + len(hierarchy_columns)
                if score > best_header_score:
                    best_header_score = score
                    header_row_index = index
                    header = {}
                    if hierarchy_columns:
                        header["hierarchy"] = hierarchy_columns
                    for label, col in labels.items():
                        if label in title_labels and "title" not in header: header["title"] = col
                        elif label in number_labels and "number" not in header: header["number"] = col
                        elif label in level_labels and "level" not in header: header["level"] = col
                        elif label in summary_labels and "summary" not in header: header["summary"] = col

            data_rows = rows[header_row_index + 1:] if header_row_index >= 0 else rows
            entries: list[tuple[str, int, str]] = []
            previous_level = 1
            for row, _ in data_rows:
                hierarchy_columns = header.get("hierarchy", {})
                title_col = header.get("title")
                title = row.get(title_col, "") if title_col is not None else ""
                hierarchy_level = None
                if hierarchy_columns:
                    populated = [(col, row.get(col, ""), level) for col, level in hierarchy_columns.items() if row.get(col, "")]
                    if populated:
                        title_col, title, hierarchy_level = max(populated, key=lambda item: item[0])
                if not title:
                    candidates_text = [(col, value) for col, value in sorted(row.items()) if value and not value.isdigit()]
                    title = candidates_text[0][1] if candidates_text else ""
                    title_col = candidates_text[0][0] if candidates_text else 0
                if not title or normalize_excel_label(title) in title_labels | {"序号", "编号", "no"}:
                    continue

                explicit_level = excel_level_value(row.get(header["level"], "")) if "level" in header else None
                numbered_level = excel_outline_level(title)
                if numbered_level is None and "number" in header:
                    numbered_level = excel_outline_level(row.get(header["number"], ""))
                level = hierarchy_level or explicit_level or numbered_level
                if level is None:
                    nonempty_cols = [col for col, value in row.items() if value]
                    source_col = min(nonempty_cols) if nonempty_cols else int(title_col or 0)
                    base_col = int(title_col or source_col)
                    level = min(6, max(1, source_col - base_col + 1))
                if entries and level > previous_level + 1:
                    level = previous_level + 1
                level = min(6, max(1, level))
                previous_level = level
                summary = row.get(header["summary"], "") if "summary" in header else ""
                if not summary and "summary" in header:
                    summary = next((value for col, value in sorted(row.items()) if col != title_col and value and not value.isdigit()), "")
                entries.append((title, level, summary))

            name_score = 0
            lowered_name = name.lower()
            for keyword, score in (("文档框架", 60), ("需求分析", 55), ("框架", 50), ("目录", 45), ("outline", 45)):
                if keyword.lower() in lowered_name:
                    name_score = max(name_score, score)
            content_score = best_header_score * 25 + min(len(entries), 20) * 2
            if any(excel_outline_level(title) for title, _, _ in entries):
                content_score += 15
            if entries:
                sheet_results.append((name_score + content_score - sheet_order, name, entries))

        if not sheet_results:
            return "", ""
        _, selected_name, entries = max(sheet_results, key=lambda item: item[0])
        lines = [f"# {selected_name or '外部导入框架'}", ""]
        for title, level, summary in entries:
            lines.append(f"{'#' * (level + 1)} {title}")
            if summary:
                lines.append(f"> 章节概述：{summary}")
            lines.append("")
        return "\n".join(lines).strip() + "\n", selected_name


def text_to_framework_markdown(text: str, title: str = "外部导入框架") -> str:
    """Apply the structural-heading rules from doc2md.py to plain/docx text."""
    lines = [f"# {title}", ""]
    for raw in str(text or "").splitlines():
        value = re.sub(r"\s+", " ", raw).strip()
        if not value: continue
        if value.startswith("#"):
            lines.append(value); continue
        match = re.match(r"^(第[一二三四五六七八九十百\d]+章|附录|[一二三四五六七八九十]+、|\d+\.\d+(?:\.\d+)*|\d+[.、])", value)
        if match:
            prefix = match.group(1)
            # The generated document title already occupies level 1. Keep
            # imported chapters beneath it: 1. -> ##, 1.1 -> ###, etc.
            if prefix.startswith(("第", "附录")) or re.match(r"^[一二三四五六七八九十]+、", prefix):
                level = 2
            else:
                numeric_prefix = prefix.rstrip(".、")
                level = min(numeric_prefix.count(".") + 2, 5)
            lines.append(f"{'#' * level} {value}")
        else:
            lines.append(f"> 章节概述：{value}")
    return "\n\n".join(lines)


def material_summary(project_id: str, material: dict[str, Any]) -> dict[str, Any]:
    material_id = str(material.get("id", ""))
    return {
        "id": material_id,
        "project_id": project_id,
        "name": str(material.get("name", "材料")),
        "extension": str(material.get("extension", "")),
        "mime_type": str(material.get("mime_type", "application/octet-stream")),
        "size": int(material.get("size", 0) or 0),
        "extract_status": str(material.get("extract_status", "unsupported")),
        "extract_message": str(material.get("extract_message", "")),
        "text_length": len(str(material.get("extracted_text", ""))),
        "text_truncated": bool(material.get("text_truncated", False)),
        "created_at": material.get("created_at"),
        "download_url": f"/api/projects/{quote(project_id)}/materials/{quote(material_id)}/download",
    }


def list_project_material_records(project_id: str) -> list[dict[str, Any]]:
    directory = project_dir(project_id) / "materials"
    if not directory.exists():
        return []
    result: list[dict[str, Any]] = []
    for item in sorted(directory.iterdir(), key=lambda path: path.name.lower()):
        metadata_path = item / "material.json"
        metadata = read_json(metadata_path, None) if item.is_dir() else None
        if isinstance(metadata, dict) and metadata.get("id"):
            result.append(metadata)
    return sorted(result, key=lambda item: item.get("created_at", ""), reverse=False)


def list_project_materials(project_id: str) -> list[dict[str, Any]]:
    return [material_summary(project_id, item) for item in list_project_material_records(project_id)]


def decode_material(payload: dict[str, Any]) -> tuple[str, str, bytes]:
    name = Path(str(payload.get("name", "材料"))).name or "材料"
    data_url = str(payload.get("data_url", ""))
    prefix, separator, encoded = data_url.partition(",")
    if separator != "," or ";base64" not in prefix:
        raise ValueError(f"材料“{name}”格式无效。")
    mime_type = prefix[5:].split(";", 1)[0].lower() or mimetypes.guess_type(name)[0] or "application/octet-stream"
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError(f"材料“{name}”无法读取。") from exc
    if not raw:
        raise ValueError(f"材料“{name}”不能为空。")
    if len(raw) > MAX_MATERIAL_BYTES:
        raise ValueError(f"材料“{name}”不能超过 {MAX_MATERIAL_BYTES // (1024 * 1024)} MB。")
    return name[:200], mime_type, raw


def save_project_material(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    project = read_json(project_dir(project_id) / "project.json", None)
    if not isinstance(project, dict):
        raise ValueError("项目不存在。")
    name, mime_type, raw = decode_material(payload)
    material_id = f"material_{int(time.time())}_{secrets.token_hex(3)}"
    directory = material_dir(project_id, material_id)
    directory.mkdir(parents=True, exist_ok=True)
    extension = Path(name).suffix.lower()
    source_path = directory / ("source" + (extension if extension else ".bin"))
    source_path.write_bytes(raw)
    extracted_text, extract_status, extract_message = extract_material_text(source_path)
    timestamp = now_iso()
    material = {
        "id": material_id,
        "project_id": project_id,
        "name": name,
        "extension": extension,
        "mime_type": mime_type,
        "size": len(raw),
        "file": source_path.name,
        "extracted_text": extracted_text,
        "extract_status": extract_status,
        "extract_message": extract_message,
        "text_truncated": len(extracted_text) >= MAX_MATERIAL_TEXT_CHARS,
        "created_at": timestamp,
    }
    write_json(directory / "material.json", material)
    project["updated_at"] = timestamp
    write_json(project_dir(project_id) / "project.json", project)
    return material_summary(project_id, material)


def get_project_material(project_id: str, material_id: str) -> dict[str, Any] | None:
    material = read_json(material_dir(project_id, material_id) / "material.json", None)
    return material if isinstance(material, dict) else None


def get_project_material_file(project_id: str, material_id: str) -> tuple[Path, str] | None:
    material = get_project_material(project_id, material_id)
    if not material:
        return None
    file_name = Path(str(material.get("file", ""))).name
    path = material_dir(project_id, material_id) / file_name
    return (path, str(material.get("mime_type", "application/octet-stream"))) if path.is_file() else None


def delete_project_material(project_id: str, material_id: str) -> None:
    directory = material_dir(project_id, material_id)
    if not directory.exists():
        raise ValueError("材料不存在。")
    shutil.rmtree(directory)
    project = read_json(project_dir(project_id) / "project.json", None)
    if isinstance(project, dict):
        project["updated_at"] = now_iso()
        write_json(project_dir(project_id) / "project.json", project)


def update_project_material_text(project_id: str, material_id: str, text: str) -> dict[str, Any]:
    material = get_project_material(project_id, material_id)
    if not material:
        raise ValueError("材料不存在。")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("材料内容不能为空。")
    if len(text) > MAX_MATERIAL_TEXT_CHARS:
        raise ValueError(f"材料内容不能超过 {MAX_MATERIAL_TEXT_CHARS:,} 个字符。")
    directory = material_dir(project_id, material_id)
    source_path = directory / Path(str(material.get("file", "source.txt"))).name
    source_path.write_text(text, encoding="utf-8")
    material["extracted_text"] = text
    material["extract_status"] = "success"
    material["extract_message"] = "文本已编辑并保存。"
    material["size"] = len(text.encode("utf-8"))
    material["mime_type"] = "text/plain"
    write_json(directory / "material.json", material)
    project = read_json(project_dir(project_id) / "project.json", None)
    if isinstance(project, dict):
        project["updated_at"] = now_iso()
        write_json(project_dir(project_id) / "project.json", project)
    return material_summary(project_id, material)


def topic_level(value: Any, default: int = 1) -> int:
    try:
        return max(1, min(3, int(value)))
    except (TypeError, ValueError):
        return default


def validate_topic_xml(xml_text: str) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        ET.fromstring(xml_text)
    except ET.ParseError as exc:
        errors.append(f"XML 不可解析：{exc}")
    guid_count = len(GUID_PATTERN.findall(xml_text))
    placeholder_count = len(PLACEHOLDER_PATTERN.findall(xml_text))
    if guid_count:
        errors.append(f"发现禁止的 GUID Token：{guid_count} 个")
    if placeholder_count:
        warnings.append(f"发现待人工替换占位符：{placeholder_count} 个")
    if errors:
        status = "校验失败"
    elif placeholder_count:
        status = "需人工处理"
    else:
        status = "结构通过"
    return {
        "ok": not errors,
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "guid_count": guid_count,
        "placeholder_count": placeholder_count,
    }


def build_topic_xml(payload: dict[str, Any], topic_id: str) -> str:
    topic_type = str(payload.get("topic_type", "concept"))
    if topic_type not in TOPIC_TYPES:
        raise ValueError("Topic 类型仅支持 Concept、Task 或附录类 Concept。")
    title = sanitize_text(payload.get("title"))
    shortdesc = sanitize_text(payload.get("shortdesc"))
    brief = sanitize_text(payload.get("brief"))
    if not title:
        raise ValueError("Topic 标题不能为空。")
    if not shortdesc:
        raise ValueError("Topic 短描述不能为空。")
    outline = parse_outline_items(payload.get("outline"))
    prerequisites = parse_lines(payload.get("prerequisites"))
    steps = parse_lines(payload.get("steps"))
    include_image = bool(payload.get("include_image_placeholder"))
    include_ref = bool(payload.get("include_ref_placeholder"))
    root_name = "task" if topic_type == "task" else "concept"
    doctype = "task" if root_name == "task" else "concept"
    root_id = f"TOPIC_{slugify(title)}"
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<!DOCTYPE {doctype} PUBLIC "-//OASIS//DTD DITA {doctype.title()}//EN" "{doctype}.dtd"[]>',
        f'<{root_name} id="{xml_escape(root_id)}" xml:lang="zh-CN">',
        f"    <title>{xml_escape(title)}</title>",
        f"    <shortdesc>{xml_escape(shortdesc)}</shortdesc>",
    ]
    if root_name == "concept":
        lines.append("    <conbody>")
        if brief:
            lines.append(f"        <p>{xml_escape(brief)}</p>")
        section_items = outline or [{"title": "功能概述", "level": 1}]
        stack: list[dict[str, Any]] = []
        counters: list[int] = []
        previous_level = 0
        section_count = 0
        for item in section_items:
            level = topic_level(item.get("level"), 1)
            if level > previous_level + 1:
                level = previous_level + 1
            while len(stack) >= level:
                lines.append("    " * (2 + len(stack) - 1) + "</section>")
                stack.pop()
            while len(counters) < level:
                counters.append(0)
            counters[level - 1] += 1
            del counters[level:]
            section_id = "SECTION_" + "_".join(str(value) for value in counters)
            indent = "    " * (2 + len(stack))
            lines.extend(
                [
                    f'{indent}<section id="{section_id}">',
                    f'{indent}    <title>{xml_escape(item["title"])}</title>',
                    f"{indent}    <p>请根据已确认需求补充本节内容。</p>",
                ]
            )
            section_count += 1
            if include_image and section_count == 1:
                lines.extend(
                    [
                        f'{indent}    <fig id="FIG_1">',
                        f"{indent}        <title>相关界面</title>",
                        f'{indent}        <image href="TODO_IMAGE" id="IMAGE_1" />',
                        f"{indent}    </fig>",
                    ]
                )
            if include_ref and section_count == 1:
                lines.append(f'{indent}    <p>详细信息请参见<xref href="TODO_REF" />。</p>')
            stack.append({"level": level})
            previous_level = level
        while stack:
            lines.append("    " * (2 + len(stack) - 1) + "</section>")
            stack.pop()
        lines.append("    </conbody>")
    else:
        lines.append("    <taskbody>")
        if prerequisites:
            lines.append("        <prereq>")
            lines.append("            <ul>")
            for item in prerequisites:
                lines.extend(["                <li>", f"                    <p>{xml_escape(item)}</p>", "                </li>"])
            lines.extend(["            </ul>", "        </prereq>"])
        lines.append("        <steps>")
        for index, step in enumerate(steps or ["请补充操作步骤。"], start=1):
            lines.extend([f'            <step id="STEP_{index}">', f"                <cmd>{xml_escape(step)}</cmd>"])
            if include_image and index == 1:
                lines.extend(
                    [
                        "                <info>",
                        "                    <fig id=\"FIG_1\">",
                        "                        <title>操作界面</title>",
                        '                        <image href="TODO_IMAGE" id="IMAGE_1" />',
                        "                    </fig>",
                        "                </info>",
                    ]
                )
            if include_ref and index == 1:
                lines.append('                <info><p>详细信息请参见<xref href="TODO_REF" />。</p></info>')
            lines.append("            </step>")
        lines.extend(["        </steps>", "    </taskbody>"])
    lines.append(f"</{root_name}>")
    return "\n".join(lines) + "\n"


def topic_summary(project_id: str, topic: dict[str, Any]) -> dict[str, Any]:
    topic_id = topic["id"]
    directory = topic_dir(project_id, topic_id)
    xml_path = directory / f"{topic_id}.xml"
    project = read_json(project_dir(project_id) / "project.json", {})
    project = project if isinstance(project, dict) else {}
    inherit_project_skills = topic.get("inherit_project_skills", True) is not False
    selected_skills = topic.get("skill_overrides")
    if selected_skills is None:
        stored_skills = normalize_skills(topic.get("skills", []))
        selected_skills = [name for name in stored_skills if name not in set(project_skill_names(project))]
    effective_skills = resolve_topic_skill_names(project, selected_skills, inherit_project_skills)
    return {
        **topic,
        "skills": effective_skills,
        "skill_overrides": ordered_unique(selected_skills),
        "inherit_project_skills": inherit_project_skills,
        "skill_snapshot": topic.get("skill_snapshot") or skill_usage_snapshot(
            effective_skills, project, selected_skills, inherit_project_skills
        ),
        "heading_level": topic_level(topic.get("heading_level", topic.get("level", 1))),
        "level": topic_level(topic.get("level", topic.get("heading_level", 1))),
        "order": int(topic.get("order", 0) or 0),
        "parent_id": topic.get("parent_id"),
        "xml": topic.get("xml", xml_path.read_text(encoding="utf-8") if xml_path.exists() else ""),
        "validation": validate_topic_xml(topic.get("xml", xml_path.read_text(encoding="utf-8") if xml_path.exists() else "")),
    }


def list_topics(project_id: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    directory = topics_dir(project_id)
    if not directory.exists():
        return result
    for path in sorted(directory.iterdir()):
        metadata = path / "topic.json"
        if path.is_dir() and metadata.exists():
            topic = read_json(metadata, None)
            if isinstance(topic, dict) and topic.get("id"):
                result.append(topic_summary(project_id, topic))
    return sorted(result, key=lambda item: (int(item.get("order", 0) or 0), item.get("created_at", "")))


def get_topic(project_id: str, topic_id: str) -> dict[str, Any] | None:
    topic = read_json(topic_dir(project_id, topic_id) / "topic.json", None)
    return topic_summary(project_id, topic) if isinstance(topic, dict) else None


def create_topic(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    project = read_json(project_dir(project_id) / "project.json", None)
    if not isinstance(project, dict):
        raise ValueError("项目不存在。")
    title = sanitize_text(payload.get("title"))
    if not title:
        raise ValueError("Topic 标题不能为空。")
    ai_result: dict[str, Any] | None = None
    if bool(payload.get("ai_generate")):
        ai_result = generate_ai_topic(project_id, payload)
    topic_id = f"topic_{int(time.time())}_{secrets.token_hex(2)}"
    directory = topic_dir(project_id, topic_id)
    directory.mkdir(parents=True, exist_ok=True)
    xml_text = str(ai_result["xml"]) if ai_result else build_topic_xml(payload, topic_id)
    validation = validate_topic_xml(xml_text)
    timestamp = now_iso()
    existing_topics = list_topics(project_id)
    heading_level = topic_level(payload.get("heading_level", payload.get("level", 1)))
    inherit_project_skills = payload.get("inherit_project_skills", True) is not False
    selected_skills = payload.get("skills", project.get("skills", []))
    effective_skills = resolve_topic_skill_names(project, selected_skills, inherit_project_skills)
    skill_overrides = topic_skill_overrides(project, selected_skills, inherit_project_skills)
    topic = {
        "id": topic_id,
        "project_id": project_id,
        "title": title,
        "topic_type": str(payload.get("topic_type", "concept")),
        "shortdesc": sanitize_text(payload.get("shortdesc")),
        "brief": sanitize_text(payload.get("brief")),
        "outline": parse_outline_items(payload.get("outline")),
        "prerequisites": parse_lines(payload.get("prerequisites")),
        "steps": parse_lines(payload.get("steps")),
        "skills": effective_skills,
        "skill_overrides": skill_overrides,
        "inherit_project_skills": inherit_project_skills,
        "skill_snapshot": ai_result.get("skill_snapshot") if ai_result else skill_usage_snapshot(effective_skills, project, skill_overrides, inherit_project_skills),
        "skill_snapshot_schema_version": 2,
        "heading_level": heading_level,
        "level": heading_level,
        "order": len(existing_topics),
        "parent_id": None,
        "include_image_placeholder": bool(payload.get("include_image_placeholder")),
        "include_ref_placeholder": bool(payload.get("include_ref_placeholder")),
        "chapter_summary": sanitize_text(payload.get("chapter_summary", payload.get("shortdesc"))),
        "generation_prompt": sanitize_text(payload.get("generation_prompt")),
        "framework_node_key": sanitize_text(payload.get("framework_node_key")),
        "material_ids": parse_lines(payload.get("material_ids")),
        "generation_source": "ai" if ai_result else "template",
        "generation_model": ai_result.get("model") if ai_result else None,
        "xml": xml_text,
        "validation": validation,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    (directory / f"{topic_id}.xml").write_text(xml_text, encoding="utf-8")
    write_json(directory / "topic.json", topic)
    project["updated_at"] = timestamp
    project["topic_count"] = int(project.get("topic_count", 0)) + 1
    write_json(project_dir(project_id) / "project.json", project)
    return topic_summary(project_id, topic)


def regenerate_topic(project_id: str, topic_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Regenerate an existing Topic while preserving its local identity and history metadata."""
    topic_path = topic_dir(project_id, topic_id) / "topic.json"
    topic = read_json(topic_path, None)
    if not isinstance(topic, dict):
        raise ValueError("Topic 不存在。")
    project = read_json(project_dir(project_id) / "project.json", None)
    if not isinstance(project, dict):
        raise ValueError("项目不存在。")

    inherit_project_skills = payload.get("inherit_project_skills", topic.get("inherit_project_skills", True)) is not False
    selected_skills = payload.get("skills", topic.get("skill_overrides", topic.get("skills", project.get("skills", []))))
    merged = {
        **topic,
        **payload,
        "title": payload.get("title", topic.get("title")),
        "shortdesc": payload.get("shortdesc", topic.get("shortdesc")),
        "brief": payload.get("brief", topic.get("brief")),
        "topic_type": payload.get("topic_type", topic.get("topic_type", "concept")),
        "heading_level": payload.get("heading_level", topic.get("heading_level", 1)),
        "skills": selected_skills,
        "inherit_project_skills": inherit_project_skills,
        "previous_xml": topic.get("xml", ""),
        "ai_generate": True,
    }
    ai_result = generate_ai_topic(project_id, merged)
    xml_text = str(ai_result["xml"])
    timestamp = now_iso()
    topic.update(
        {
            "title": sanitize_text(merged.get("title")),
            "topic_type": str(merged.get("topic_type", topic.get("topic_type", "concept"))),
            "shortdesc": sanitize_text(merged.get("shortdesc")),
            "brief": sanitize_text(merged.get("brief")),
            "outline": parse_outline_items(merged.get("outline", topic.get("outline", []))),
            "prerequisites": parse_lines(merged.get("prerequisites", topic.get("prerequisites", []))),
            "steps": parse_lines(merged.get("steps", topic.get("steps", []))),
            "skills": resolve_topic_skill_names(project, merged.get("skills", []), inherit_project_skills),
            "skill_overrides": topic_skill_overrides(project, merged.get("skills", []), inherit_project_skills),
            "inherit_project_skills": inherit_project_skills,
            "skill_snapshot": ai_result.get("skill_snapshot") or skill_usage_snapshot(
                resolve_topic_skill_names(project, merged.get("skills", []), inherit_project_skills),
                project,
                topic_skill_overrides(project, merged.get("skills", []), inherit_project_skills),
                inherit_project_skills,
            ),
            "skill_snapshot_schema_version": 2,
            "heading_level": topic_level(merged.get("heading_level", topic.get("heading_level", 1))),
            "level": topic_level(merged.get("heading_level", topic.get("level", 1))),
            "chapter_summary": sanitize_text(merged.get("chapter_summary", topic.get("chapter_summary", ""))),
            "generation_prompt": sanitize_text(merged.get("generation_prompt", "")),
            "framework_node_key": sanitize_text(merged.get("framework_node_key", topic.get("framework_node_key", ""))),
            "material_ids": parse_lines(merged.get("material_ids", topic.get("material_ids", []))),
            "generation_source": "ai",
            "generation_model": ai_result.get("model"),
            "xml": xml_text,
            "validation": validate_topic_xml(xml_text),
            "updated_at": timestamp,
        }
    )
    (topic_dir(project_id, topic_id) / f"{topic_id}.xml").write_text(xml_text, encoding="utf-8")
    write_json(topic_path, topic)
    project["updated_at"] = timestamp
    project["stage"] = "Topic 生成"
    write_json(project_dir(project_id) / "project.json", project)
    return topic_summary(project_id, topic)


def save_topic_order(project_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_topics = payload.get("topics")
    if not isinstance(raw_topics, list):
        raise ValueError("Topic 排序数据格式无效。")
    existing = {topic["id"]: topic for topic in list_topics(project_id)}
    ordered_ids: list[str] = []
    for item in raw_topics:
        if not isinstance(item, dict):
            continue
        topic_id = str(item.get("id", ""))
        if topic_id in existing and topic_id not in ordered_ids:
            ordered_ids.append(topic_id)
    for topic_id in existing:
        if topic_id not in ordered_ids:
            ordered_ids.append(topic_id)

    normalized: list[dict[str, Any]] = []
    for order, topic_id in enumerate(ordered_ids):
        source = next((item for item in raw_topics if isinstance(item, dict) and str(item.get("id", "")) == topic_id), {})
        requested_level = topic_level(source.get("level", source.get("heading_level", 1)))
        previous_level = normalized[-1]["level"] if normalized else 0
        level = min(requested_level, previous_level + 1) if previous_level else 1
        parent_id = None
        if level > 1:
            parent = next((item["id"] for item in reversed(normalized) if item["level"] == level - 1), None)
            if parent:
                parent_id = parent
            else:
                level = 1
        normalized.append({"id": topic_id, "order": order, "level": level, "parent_id": parent_id})

    timestamp = now_iso()
    for node in normalized:
        path = topic_dir(project_id, node["id"]) / "topic.json"
        topic = read_json(path, None)
        if not isinstance(topic, dict):
            continue
        topic.update(
            {
                "order": node["order"],
                "level": node["level"],
                "heading_level": node["level"],
                "parent_id": node["parent_id"],
                "updated_at": timestamp,
            }
        )
        write_json(path, topic)
    project = read_json(project_dir(project_id) / "project.json", None)
    if isinstance(project, dict):
        project["updated_at"] = timestamp
        write_json(project_dir(project_id) / "project.json", project)
    return list_topics(project_id)


def update_topic_xml(project_id: str, topic_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    topic_path = topic_dir(project_id, topic_id) / "topic.json"
    topic = read_json(topic_path, None)
    if not isinstance(topic, dict):
        raise ValueError("Topic 不存在。")
    xml_text = str(payload.get("xml", ""))
    if not xml_text.strip():
        raise ValueError("XML 内容不能为空。")
    topic["xml"] = xml_text
    topic["validation"] = validate_topic_xml(xml_text)
    topic["updated_at"] = now_iso()
    (topic_dir(project_id, topic_id) / f"{topic_id}.xml").write_text(xml_text, encoding="utf-8")
    write_json(topic_path, topic)
    # A manual XML save is also a project content save. Keep the project
    # timestamp current so corpus pickers and project lists show the latest
    # effective content, while the corpus itself continues to read live files.
    project_path = project_dir(project_id) / "project.json"
    project = read_json(project_path, None)
    if isinstance(project, dict):
        project["updated_at"] = topic["updated_at"]
        project["stage"] = "Topic 生成"
        write_json(project_path, project)
    return topic_summary(project_id, topic)


def copy_project_baseline(source_project_id: str, target_project_id: str, target_directory: Path) -> None:
    """Copy the current framework and Topic XML as a local version baseline."""
    source_directory = project_dir(source_project_id)
    source_project = read_json(source_directory / "project.json", None)
    if not isinstance(source_project, dict):
        raise ValueError("基线项目不存在。")
    source_framework = source_directory / "framework"
    if source_framework.exists():
        shutil.copytree(source_framework, target_directory / "framework", dirs_exist_ok=True)
        framework_path = target_directory / "framework" / "framework.json"
        framework = read_json(framework_path, None)
        if isinstance(framework, dict):
            framework["project_id"] = target_project_id
            framework["source_project_id"] = source_project_id
            write_json(framework_path, framework)
        for version_path in (target_directory / "framework" / "versions").glob("framework_*.json"):
            version = read_json(version_path, None)
            if isinstance(version, dict):
                version["project_id"] = target_project_id
                version["source_project_id"] = source_project_id
                write_json(version_path, version)
    source_topics = source_directory / "topics"
    target_topics = target_directory / "topics"
    if source_topics.exists():
        shutil.copytree(source_topics, target_topics, dirs_exist_ok=True)
        for topic_path in target_topics.glob("*/topic.json"):
            topic = read_json(topic_path, None)
            if isinstance(topic, dict):
                topic["project_id"] = target_project_id
                topic["source_project_id"] = source_project_id
                topic["baseline"] = True
                write_json(topic_path, topic)


def corpus_project_ids(project: dict[str, Any]) -> list[str]:
    return normalize_project_ids(project.get("reference_project_ids", []), str(project.get("id", "")))


def project_corpus_records(project: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for reference_id in corpus_project_ids(project):
        reference = read_json(project_dir(reference_id) / "project.json", None)
        if not isinstance(reference, dict):
            continue
        framework = get_framework(reference_id)
        records.append(
            {
                "id": reference_id,
                "name": reference.get("name", reference_id),
                "version": reference.get("version", ""),
                "mode": normalize_project_mode(reference.get("mode", "new")),
                "framework": framework,
                "topics": list_topics(reference_id),
                "materials": list_project_material_records(reference_id),
            }
        )
    return records


def project_corpus_summary(project: dict[str, Any]) -> dict[str, Any]:
    records = project_corpus_records(project)
    return {
        "project_count": len(records),
        "topic_count": sum(len(item.get("topics", [])) for item in records),
        "material_count": sum(len(item.get("materials", [])) for item in records),
        "projects": [
            {"id": item["id"], "name": item["name"], "version": item.get("version", ""), "mode": item.get("mode", "new")}
            for item in records
        ],
    }


def project_corpus_context(project: dict[str, Any], max_chars: int = 70_000) -> str:
    """Build live context from referenced projects; no static corpus snapshot is stored."""
    blocks: list[str] = []
    used = 0
    for record in project_corpus_records(project):
        header = f"### 参考项目：{record['name']} / {record.get('version') or '未填写版本'}"
        parts = [header]
        framework = record.get("framework") or {}
        markdown = str(framework.get("markdown", "")).strip()
        if markdown:
            parts.append(f"#### 已定稿框架\n{markdown[:24_000]}")
        topics = record.get("topics", [])
        if topics:
            topic_lines = []
            for topic in topics[:80]:
                xml = str(topic.get("xml", "")).strip()
                topic_lines.append(f"- {topic.get('title', '')}\n{xml[:2_500]}")
            parts.append("#### 已定稿 Topic XML\n" + "\n".join(topic_lines))
        materials = record.get("materials", [])
        material_blocks: list[str] = []
        for item in materials[:80]:
            material_text = str(item.get("extracted_text", "")).strip()
            material_block = f"- {item.get('name', '')}（{item.get('extract_status', 'unknown')}，{item.get('text_length', 0)} 字符）"
            if material_text:
                material_block += f"\n{material_text[:8_000]}"
            material_blocks.append(material_block)
        if material_blocks:
            parts.append("#### 参考项目素材\n" + "\n\n".join(material_blocks))
        block = "\n\n".join(parts)
        remaining = max_chars - used
        if remaining <= 0:
            break
        blocks.append(block[:remaining])
        used += len(block)
    return "\n\n".join(blocks)


def project_baseline_context(project: dict[str, Any], max_chars: int = 60_000) -> str:
    """Read the current project's copied baseline for update/optimization prompts."""
    project_id = str(project.get("id", ""))
    framework = get_framework(project_id) or {}
    topics = list_topics(project_id)
    blocks: list[str] = []
    markdown = str(framework.get("markdown", "")).strip()
    if markdown:
        blocks.append(f"#### 当前项目基线框架\n{markdown[:24_000]}")
    topic_blocks: list[str] = []
    for topic in topics[:80]:
        xml = str(topic.get("xml", "")).strip()
        topic_blocks.append(
            f"### 基线 Topic：{topic.get('title', '')}\n"
            f"- 层级：{topic.get('level', topic.get('heading_level', 1))}\n"
            f"- 概述：{topic.get('chapter_summary', topic.get('shortdesc', ''))}\n"
            f"{xml[:3_000]}"
        )
    if topic_blocks:
        blocks.append("#### 当前项目基线 Topic\n" + "\n\n".join(topic_blocks))
    context = "\n\n".join(blocks)
    return context[:max_chars]


def project_summary(project: dict[str, Any]) -> dict[str, Any]:
    project_id = project["id"]
    directory = project_dir(project_id)
    materials = directory / "materials"
    outputs = directory / "outputs"
    topics = directory / "topics"
    cover = project.get("cover") if isinstance(project.get("cover"), dict) else default_cover()
    cover_url = None
    if cover:
        stored_cover = directory / Path(str(cover.get("file", ""))).name
        if stored_cover.exists() and stored_cover.is_file():
            cover_url = f"/api/projects/{quote(project_id)}/cover"
        elif cover.get("type") == "asset":
            asset_file = Path(str(cover.get("source_file", cover.get("file", "")))).name
            if asset_file in {asset["file"] for asset in list_editorial_assets()}:
                cover_url = f"/static/assets/editorial/{quote(asset_file)}"
    return {
        **project,
        "skills": project_skill_names(project),
        "mode": normalize_project_mode(project.get("mode", "new")),
        "mode_label": PROJECT_MODES[normalize_project_mode(project.get("mode", "new"))],
        "reference_project_ids": corpus_project_ids(project),
        "corpus": project_corpus_summary(project),
        "cover": cover,
        "cover_url": cover_url,
        "topic_count": len([p for p in topics.iterdir() if p.is_dir() and (p / "topic.json").exists()])
        if topics.exists()
        else int(project.get("topic_count", 0)),
        "material_count": len(list_project_material_records(project_id)) if materials.exists() else 0,
        "output_count": len([p for p in outputs.iterdir() if p.is_file()])
        if outputs.exists()
        else 0,
    }


def list_projects() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in sorted(PROJECTS_DIR.iterdir()) if PROJECTS_DIR.exists() else []:
        metadata = path / "project.json"
        if path.is_dir() and metadata.exists():
            project = read_json(metadata, None)
            if isinstance(project, dict) and project.get("id"):
                result.append(project_summary(project))
    return sorted(result, key=lambda item: item.get("updated_at", ""), reverse=True)


def create_project(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name", "")).strip()
    if not name:
        raise ValueError("项目名称不能为空。")
    project_id = new_project_id()
    mode = normalize_project_mode(payload.get("mode", "new"))
    base_project_id = str(payload.get("base_project_id", "")).strip()
    if mode in {"update", "optimize"} and base_project_id:
        base_project = read_json(project_dir(base_project_id) / "project.json", None)
        if not isinstance(base_project, dict):
            raise ValueError("所选基线项目不存在。")
    reference_project_ids = normalize_project_ids(payload.get("reference_project_ids", []), project_id)
    for reference_id in reference_project_ids:
        if not isinstance(read_json(project_dir(reference_id) / "project.json", None), dict):
            raise ValueError("参考项目语料库中包含不存在的项目。")
    directory = project_dir(project_id)
    for child in ("materials", "outputs", "versions", "topics"):
        (directory / child).mkdir(parents=True, exist_ok=True)
    if mode in {"update", "optimize"} and base_project_id:
        copy_project_baseline(base_project_id, project_id, directory)
    cover = save_project_cover(payload.get("cover"), directory)
    timestamp = now_iso()
    requested_skills = payload.get("skills")
    project_skills = normalize_skills(
        requested_skills,
        default_dita=requested_skills is None,
    )
    project = {
        "id": project_id,
        "name": name,
        "product": str(payload.get("product", "")).strip(),
        "version": str(payload.get("version", "")).strip(),
        "description": str(payload.get("description", "")).strip(),
        "stage": "需求分析" if mode != "optimize" else "Topic 优化",
        "created_at": timestamp,
        "updated_at": timestamp,
        "skills": project_skills,
        "skill_schema_version": 2,
        "mode": mode,
        "base_project_id": base_project_id or None,
        "reference_project_ids": reference_project_ids,
        "topic_modes": ["new", "optimize"] if mode == "optimize" else ["new"],
        "cover": cover,
    }
    write_json(directory / "project.json", project)
    return project_summary(project)


def get_project(project_id: str) -> dict[str, Any] | None:
    path = project_dir(project_id) / "project.json"
    project = read_json(path, None)
    if not isinstance(project, dict):
        return None
    summary = project_summary(project)
    analyses = list_analysis_records(project_id)
    if analyses:
        latest = analyses[-1]
        summary["latest_analysis"] = {
            "id": latest.get("id"),
            "created_at": latest.get("created_at"),
            "model": latest.get("model"),
            "source": latest.get("source", "ai"),
            "question_count": len(latest.get("questions", [])),
            "missing_count": len(latest.get("missing_materials", [])),
        }
    else:
        summary["latest_analysis"] = None
    return summary


def update_project_metadata(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    path = project_dir(project_id) / "project.json"
    project = read_json(path, None)
    if not isinstance(project, dict):
        raise ValueError("项目不存在。")
    if "reference_project_ids" in payload:
        references = normalize_project_ids(payload.get("reference_project_ids", []), project_id)
        for reference_id in references:
            if not isinstance(read_json(project_dir(reference_id) / "project.json", None), dict):
                raise ValueError("参考项目语料库中包含不存在的项目。")
        project["reference_project_ids"] = references
    if "description" in payload:
        project["description"] = str(payload.get("description", "")).strip()
    if "skills" in payload:
        project["skills"] = normalize_skills(payload.get("skills"))
        project["skill_schema_version"] = 2
    project["updated_at"] = now_iso()
    write_json(path, project)
    return project_summary(project)


def migrate_legacy_projects() -> int:
    """Upgrade projects created before the project/Topic Skill route existed.

    The migration is deliberately local and idempotent.  It adds the default
    DITA Rule to legacy project routes, marks Topics as inheriting by default,
    and keeps any Topic-only Skills as explicit overrides.
    """
    migrated = 0
    if not PROJECTS_DIR.exists():
        return migrated
    for project_path in PROJECTS_DIR.iterdir():
        metadata_path = project_path / "project.json"
        project = read_json(metadata_path, None)
        if not project_path.is_dir() or not isinstance(project, dict) or not project.get("id"):
            continue
        changed = False
        if normalize_project_mode(project.get("mode")) != project.get("mode"):
            project["mode"] = normalize_project_mode(project.get("mode"))
            changed = True
        if int(project.get("skill_schema_version", 0) or 0) < 2:
            project["skills"] = normalize_skills(project.get("skills", []), default_dita=True)
            project["skill_schema_version"] = 2
            changed = True
        else:
            normalized_project_skills = normalize_skills(project.get("skills", []))
            if normalized_project_skills != project.get("skills", []):
                project["skills"] = normalized_project_skills
                changed = True

        project_names = set(project_skill_names(project))
        topics_path = project_path / "topics"
        if topics_path.exists():
            for topic_path in topics_path.glob("*/topic.json"):
                topic = read_json(topic_path, None)
                if not isinstance(topic, dict) or not topic.get("id"):
                    continue
                topic_changed = False
                inherit = topic.get("inherit_project_skills", True) is not False
                if "inherit_project_skills" not in topic:
                    topic["inherit_project_skills"] = True
                    topic_changed = True
                stored_skills = normalize_skills(topic.get("skills", []))
                if "skill_overrides" not in topic:
                    topic["skill_overrides"] = [name for name in stored_skills if name not in project_names]
                    topic_changed = True
                effective = resolve_topic_skill_names(project, topic.get("skill_overrides", []), inherit)
                if topic.get("skills") != effective:
                    topic["skills"] = effective
                    topic_changed = True
                if int(topic.get("skill_snapshot_schema_version", 0) or 0) < 2:
                    topic["skill_snapshot"] = skill_usage_snapshot(
                        effective, project, topic.get("skill_overrides", []), inherit
                    )
                    topic["skill_snapshot_schema_version"] = 2
                    topic_changed = True
                if topic_changed:
                    write_json(topic_path, topic)
                    migrated += 1
                    changed = True
        if changed:
            project["updated_at"] = project.get("updated_at") or now_iso()
            write_json(metadata_path, project)
            migrated += 1
    return migrated


def analysis_version_dir(project_id: str) -> Path:
    return project_dir(project_id) / "versions"


def list_analysis_records(project_id: str) -> list[dict[str, Any]]:
    directory = analysis_version_dir(project_id)
    if not directory.exists():
        return []
    result: list[dict[str, Any]] = []
    for path in sorted(directory.glob("analysis_*.json"), key=lambda item: item.name):
        record = read_json(path, None)
        if isinstance(record, dict) and record.get("id"):
            result.append(record)
    return result


def analysis_record_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record.get("id"),
        "project_id": record.get("project_id"),
        "created_at": record.get("created_at"),
        "source": record.get("source", "ai"),
        "model": record.get("model"),
        "skills": record.get("skills", []),
        "skill_snapshot": record.get("skill_snapshot", []),
        "material_ids": record.get("material_ids", []),
        "summary": record.get("summary", ""),
        "confirmed_items": record.get("confirmed_items", []),
        "missing_materials": record.get("missing_materials", []),
        "questions": record.get("questions", []),
        "topic_outline": record.get("topic_outline", []),
    }


def public_analysis_versions(project_id: str) -> list[dict[str, Any]]:
    return [
        {
            "id": record.get("id"),
            "created_at": record.get("created_at"),
            "source": record.get("source", "ai"),
            "model": record.get("model"),
            "question_count": len(record.get("questions", [])),
            "missing_count": len(record.get("missing_materials", [])),
            "topic_count": len(record.get("topic_outline", [])),
        }
        for record in list_analysis_records(project_id)
    ]


def framework_dir(project_id: str) -> Path:
    directory = project_dir(project_id) / "framework"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def framework_file(project_id: str) -> Path:
    return framework_dir(project_id) / "framework.json"


def framework_version_dir(project_id: str) -> Path:
    directory = framework_dir(project_id) / "versions"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def framework_record_summary(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    return {
        "id": record.get("id"),
        "project_id": record.get("project_id"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "source": record.get("source", "manual"),
        "model": record.get("model"),
        "skills": record.get("skills", []),
        "skill_snapshot": record.get("skill_snapshot", []),
        "material_ids": record.get("material_ids", []),
        "analysis_id": record.get("analysis_id"),
        "markdown": record.get("markdown", ""),
        "layout": record.get("layout", "mindmap"),
        "node_count": int(record.get("node_count", 0) or 0),
        "supporting_analysis": record.get("supporting_analysis"),
    }


def get_framework(project_id: str) -> dict[str, Any] | None:
    project = read_json(project_dir(project_id) / "project.json", None)
    if not isinstance(project, dict):
        return None
    record = read_json(framework_file(project_id), None)
    if not isinstance(record, dict):
        return {
            "project_id": project_id,
            "markdown": "",
            "layout": "mindmap",
            "source": "empty",
            "node_count": 0,
            "versions": [],
        }
    versions = []
    for path in sorted(framework_version_dir(project_id).glob("framework_*.json"), key=lambda item: item.name):
        item = read_json(path, None)
        if isinstance(item, dict) and item.get("id"):
            versions.append({
                "id": item.get("id"),
                "created_at": item.get("created_at"),
                "source": item.get("source", "manual"),
                "model": item.get("model"),
                "node_count": int(item.get("node_count", 0) or 0),
            })
    result = framework_record_summary(record) or {}
    result["versions"] = versions
    return result


def save_framework(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    project = read_json(project_dir(project_id) / "project.json", None)
    if not isinstance(project, dict):
        raise ValueError("项目不存在。")
    markdown = str(payload.get("markdown", ""))
    if len(markdown) > MAX_MATERIAL_TEXT_CHARS:
        raise ValueError(f"框架内容不能超过 {MAX_MATERIAL_TEXT_CHARS:,} 个字符。")
    layout = str(payload.get("layout", "mindmap"))
    if layout not in {"mindmap", "fishbone"}:
        layout = "mindmap"
    timestamp = now_iso()
    framework_id = f"framework_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(2)}"
    record = {
        "id": framework_id,
        "project_id": project_id,
        "created_at": timestamp,
        "updated_at": timestamp,
        "source": str(payload.get("source", "manual")),
        "model": str(payload.get("model", "")),
        "skills": normalize_skills(payload.get("skills")),
        "skill_snapshot": skill_usage_snapshot(normalize_skills(payload.get("skills")), project),
        "material_ids": parse_lines(payload.get("material_ids")),
        "analysis_id": str(payload.get("analysis_id", "")),
        "markdown": markdown,
        "layout": layout,
        "node_count": int(payload.get("node_count", 0) or 0),
        "supporting_analysis": payload.get("supporting_analysis") if isinstance(payload.get("supporting_analysis"), dict) else None,
    }
    if str(payload.get("source", "manual")) != "autosave":
        write_json(framework_version_dir(project_id) / f"{framework_id}.json", record)
    write_json(framework_file(project_id), record)
    project["updated_at"] = timestamp
    project["stage"] = "框架编辑"
    write_json(project_dir(project_id) / "project.json", project)
    result = framework_record_summary(record) or {}
    result["versions"] = [
        {"id": item.get("id"), "created_at": item.get("created_at"), "source": item.get("source", "manual"), "model": item.get("model"), "node_count": item.get("node_count", 0)}
        for item in sorted((read_json(path, {}) for path in framework_version_dir(project_id).glob("framework_*.json")), key=lambda item: str(item.get("created_at", "")))
        if isinstance(item, dict) and item.get("id")
    ]
    return result


def framework_markdown_from_outline(project: dict[str, Any], outline: Any) -> str:
    lines = [f"# {sanitize_text(project.get('name')) or '文档'}", ""]
    if not isinstance(outline, list) or not outline:
        return "\n".join(lines).strip() + "\n"
    for item in outline:
        if not isinstance(item, dict):
            continue
        title = sanitize_text(item.get("title"))
        if not title:
            continue
        level = max(1, min(5, int(item.get("level", 1) or 1)))
        topic_type = " [task]" if str(item.get("type", "")).lower() == "task" else ""
        lines.append(f"{'#' * (level + 1)} {title}{topic_type}")
        summary = sanitize_text(item.get("shortdesc"))
        if summary:
            lines.extend(["", f"> 章节概述：{summary}"])
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_framework_ai_messages(
    project: dict[str, Any], payload: dict[str, Any], materials: list[dict[str, Any]]
) -> tuple[str, str, list[str]]:
    records = selected_skill_records(payload.get("skills") or project.get("skills", []))
    skill_names = [str(item["name"]) for item in records]
    skill_blocks: list[str] = []
    for skill in records:
        block = f"## Skill：{skill['name']}\n{skill.get('content', '')}"
        attachments = text_attachment_context(skill)
        if attachments:
            block += f"\n\n## Skill 附件上下文\n{attachments}"
        skill_blocks.append(block)
    material_blocks: list[str] = []
    material_budget = 180_000
    used = 0
    for material in materials:
        text = str(material.get("extracted_text", "")).strip()
        message = str(material.get("extract_message", ""))
        if text:
            remaining = max(0, material_budget - used)
            if remaining <= 0:
                material_blocks.append(f"### 材料：{material.get('name', '未命名')}\n- 文本未送入 AI：已达到本次分析上下文上限。")
                continue
            text = text[:remaining]
            used += len(text)
            material_blocks.append(f"### 材料：{material.get('name', '未命名')}\n{text}")
        else:
            material_blocks.append(f"### 材料：{material.get('name', '未命名')}\n- 暂无可读取文本。{message}")
    corpus_context = project_corpus_context(project)
    mode = normalize_project_mode(project.get("mode", "new"))
    baseline_context = project_baseline_context(project) if mode != "new" else ""
    mode_instruction = {
        "new": "这是全新开发项目，请从输入材料组织全新的文档框架。",
        "update": "这是版本更新项目。项目中已有的框架和 Topic 是上版本基线，请结合本次材料识别新增、修改、废弃、未变化内容，并在 topic_outline 中填写 change_status。",
        "optimize": "这是 Topic 优化项目。基线框架仅用于定位上下文，除非材料明确要求，不要因为语言优化而重排文档结构。",
    }[mode]
    system = """你是 HIK 文档开发工具中的文档框架设计器。请严格遵守已选 Skill，只根据输入材料生成新的文档框架，不得补造业务事实。

只返回一个有效 JSON 对象，不要返回 Markdown 代码围栏或解释。字段必须包含：
- summary：本次框架的简要说明；
- markdown：完整 Markdown 文档框架；
- confirmed_items：材料中已经确认的信息，元素包含 item、evidence、confidence、source_materials；
- missing_materials：生成框架仍缺少的材料，元素包含 item、reason、suggestion、source_materials；
- questions：需要研发或产品确认的问题，元素包含 question、reason、owner、priority、source_materials。

Markdown 规则：
1. 第一行使用一个文档总标题，例如 # 产品用户手册。
2. 使用 # 到 ###### 表示层级，同级标题表达同一层级的内容。
3. 每个可独立编写的 Topic 都必须是一个标题；操作类 Topic 在标题末尾添加 [task]，说明类 Topic 不添加标记。
4. 每个 Topic 标题后可紧跟一行 `> 章节概述：...`，概述说明该章节要解决什么问题，不要编造材料中不存在的细节。
5. 框架只输出标题和章节概述，不写完整正文，不生成 XML，不生成 GUID。
6. 优先按照用户目标、产品结构和操作任务组织目录，避免重复标题。当前不生成 Reference Topic。
7. 版本更新时，topic_outline 中每个元素增加 change_status，可取 unchanged、modified、added、deprecated、review；全新项目默认 added，优化项目默认 review。
"""
    user = f"""请根据以下项目材料，生成一份可编辑的文档框架。

## 项目信息
- 项目：{project.get('name', '')}
- 产品/模块：{project.get('product', '') or '未提供'}
- 版本：{project.get('version', '') or '未提供'}
- 本次生成提示词：{sanitize_text(payload.get('analysis_note')) or '无'}
- 项目模式：{PROJECT_MODES[mode]}
- 模式处理要求：{mode_instruction}

## 已选 Skill
{chr(10).join(skill_blocks)}

## 原始材料提取内容
{chr(10).join(material_blocks)}

## 当前项目基线（版本更新或 Topic 优化项目）
{baseline_context or '无当前项目基线。'}

## 参考项目实时语料库
以下内容来自用户选择的参考项目，生成时读取其当前定稿框架、Topic XML 和素材元数据。只能将其作为风格、结构和术语参考，不得把参考项目中的业务事实直接套用到当前项目；若没有参考项目，以下为空。
{corpus_context or '暂无参考项目语料。'}

只返回 JSON。"""
    return system, user, skill_names


def generate_framework(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    project = read_json(project_dir(project_id) / "project.json", None)
    if not isinstance(project, dict):
        raise ValueError("项目不存在。")
    materials = list_project_material_records(project_id)
    if not materials:
        raise ValueError("请先上传至少一份需求材料。")
    readable = [item for item in materials if str(item.get("extracted_text", "")).strip()]
    if not readable:
        raise ValueError("当前材料均未成功提取文本，暂时无法生成框架。请补充 Markdown、Word 或可提取文本的 PDF。")
    system, user, skill_names = build_framework_ai_messages(project, payload, materials)
    raw_text, model = call_ai_text(load_settings(), system, user, max_tokens=9000)
    try:
        parsed = json.loads(clean_ai_json(raw_text))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AI 返回的框架不是有效 JSON：{str(exc)[:240]}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("AI 返回的框架不是 JSON 对象。")
    markdown = str(parsed.get("markdown", parsed.get("framework", ""))).strip()
    if not markdown:
        normalized = normalize_analysis_result(parsed)
        markdown = framework_markdown_from_outline(project, normalized.get("topic_outline", []))
    if not re.search(r"^#{1,6}\s+.+", markdown, re.MULTILINE):
        raise RuntimeError("AI 未返回可识别的 Markdown 标题层级。")
    supporting = normalize_analysis_result(parsed)
    return save_framework(
        project_id,
        {
            "markdown": markdown + ("\n" if not markdown.endswith("\n") else ""),
            "layout": payload.get("layout", "mindmap"),
            "source": "ai",
            "model": model,
            "skills": skill_names,
            "material_ids": [str(item.get("id")) for item in materials],
            "analysis_id": "",
            "node_count": len(re.findall(r"^#{1,6}\s+.+", markdown, re.MULTILINE)),
            "supporting_analysis": supporting,
        },
    )


def update_settings(payload: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    allowed = {"provider", "base_url", "model", "temperature", "timeout_seconds"}
    for key in allowed:
        if key in payload:
            settings[key] = payload[key]
    if "api_key" in payload and str(payload["api_key"]).strip():
        KEYCHAIN.save(str(payload["api_key"]).strip())
    settings["updated_at"] = now_iso()
    write_json(SETTINGS_FILE, settings)
    return public_settings()


def endpoint_for(settings: dict[str, Any]) -> str:
    base_url = str(settings.get("base_url", "")).strip().rstrip("/")
    if not base_url:
        raise ValueError("请先填写 API 地址。")
    if base_url.endswith("/chat/completions") or base_url.endswith("/messages"):
        return base_url
    provider = settings.get("provider")
    if provider == "anthropic":
        return base_url + "/v1/messages"
    return base_url + "/chat/completions"


def is_private_endpoint(endpoint: str) -> bool:
    """Do not send LAN/local model requests through the macOS system proxy."""
    try:
        hostname = urlparse(endpoint).hostname
        if not hostname:
            return False
        if hostname.casefold() in {"localhost", "localhost.localdomain"}:
            return True
        return ipaddress.ip_address(hostname).is_private or ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def open_ai_request(request: urllib.request.Request, endpoint: str, timeout: int):
    if is_private_endpoint(endpoint):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(request, timeout=timeout)
    return urllib.request.urlopen(request, timeout=timeout)


def test_ai_connection() -> dict[str, Any]:
    settings = load_settings()
    provider = settings.get("provider", "openai-compatible")
    model = str(settings.get("model", "")).strip()
    if not model and provider != "local":
        raise ValueError("请先填写模型名称。")
    endpoint = endpoint_for(settings)
    api_key = KEYCHAIN.get()
    if provider != "local" and not api_key:
        raise ValueError("尚未配置 API Key。")

    if provider == "anthropic":
        body = {
            "model": model,
            "max_tokens": 8,
            "messages": [{"role": "user", "content": "只回复 OK"}],
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key or "",
            "anthropic-version": "2023-06-01",
        }
    else:
        body = {
            "model": model,
            "temperature": 0,
            "max_tokens": 8,
            "messages": [{"role": "user", "content": "只回复 OK"}],
        }
        headers = {
            "Content-Type": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    timeout = int(settings.get("timeout_seconds", 60))
    try:
        with open_ai_request(request, endpoint, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"服务返回 HTTP {exc.code}（请求地址：{endpoint}）：{raw[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"网络连接失败（请求地址：{endpoint}）：{exc.reason}") from exc
    except ConnectionRefusedError as exc:
        raise RuntimeError(f"模型地址拒绝连接：{endpoint}") from exc
    except TimeoutError as exc:
        raise RuntimeError("请求超时，请检查地址或超时设置。") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {}
    return {
        "success": 200 <= status < 300,
        "status": status,
        "endpoint": endpoint,
        "model": model or "本地模型",
        "response_preview": raw[:300],
        "response": data,
    }


def ai_response_text(data: dict[str, Any], provider: str) -> str:
    """Extract text from the common OpenAI-compatible and Anthropic shapes."""
    if provider == "anthropic":
        blocks = data.get("content", [])
        if isinstance(blocks, list):
            return "\n".join(str(block.get("text", "")) for block in blocks if isinstance(block, dict))
        return str(blocks or "")
    choices = data.get("choices", [])
    if isinstance(choices, list) and choices:
        message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        content = message.get("content", "") if isinstance(message, dict) else ""
        if isinstance(content, list):
            return "\n".join(
                str(item.get("text", "")) if isinstance(item, dict) else str(item)
                for item in content
            )
        return str(content or "")
    return str(data.get("text", "") or data.get("output", ""))


def clean_ai_xml(raw_text: str) -> str:
    """Remove common markdown/JSON wrappers without changing XML semantics."""
    text = str(raw_text or "").strip()
    if text.startswith("{"):
        try:
            value = json.loads(text)
            if isinstance(value, dict):
                text = str(value.get("xml", value.get("content", value.get("output", text))))
        except json.JSONDecodeError:
            pass
    fenced = re.search(r"```(?:xml|dita)?\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    starts = [index for index in (text.find("<?xml"), text.find("<!DOCTYPE"), text.find("<concept"), text.find("<task")) if index >= 0]
    if starts:
        text = text[min(starts):]
    return text.strip() + ("\n" if text.strip() else "")


def clean_ai_json(raw_text: str) -> str:
    """Remove common markdown wrappers and keep the outer JSON object."""
    text = str(raw_text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    return text[start : end + 1].strip() if start >= 0 and end > start else text


def text_attachment_context(skill: dict[str, Any]) -> str:
    """Read small text attachments as prompt context; keep binary attachments local."""
    text_suffixes = {".md", ".markdown", ".txt", ".xml", ".html", ".htm", ".json", ".csv", ".yaml", ".yml"}
    chunks: list[str] = []
    total = 0
    for attachment in skill.get("attachments", []):
        if not isinstance(attachment, dict):
            continue
        name = str(attachment.get("name", "附件"))
        path = skill_attachment_dir(str(skill["id"])) / Path(str(attachment.get("file", ""))).name
        if path.suffix.lower() not in text_suffixes or not path.is_file():
            chunks.append(f"- {name}（本地附件，未直接读取二进制内容）")
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")[:24000]
        except OSError:
            chunks.append(f"- {name}（本地附件，读取失败）")
            continue
        remaining = max(0, 60000 - total)
        if not remaining:
            chunks.append(f"- {name}（文本内容已达到上下文上限）")
            continue
        content = content[:remaining]
        total += len(content)
        chunks.append(f"### 附件：{name}\n{content}")
    return "\n\n".join(chunks)


def selected_skill_records(skill_names: Any) -> list[dict[str, Any]]:
    names = normalize_skills(skill_names)
    records: list[dict[str, Any]] = []
    for name in names:
        listed = next((item for item in list_skills() if item.get("name") == name), None)
        skill = get_skill_record(str(listed.get("id"))) if listed else None
        if not skill:
            continue
        if not skill.get("required") and not skill.get("enabled", True):
            continue
        records.append(skill)
    if not any(item.get("name") == HIK_SKILL for item in records):
        records.insert(0, builtin_hik_skill())
    return records


def build_topic_ai_messages(project: dict[str, Any], payload: dict[str, Any]) -> tuple[str, str, list[str]]:
    topic_type = str(payload.get("topic_type", "concept"))
    type_name = TOPIC_TYPES.get(topic_type, "Concept")
    inherit_project_skills = payload.get("inherit_project_skills", True) is not False
    selected_skills = payload.get("skills", project.get("skills", []))
    effective_skills = resolve_topic_skill_names(project, selected_skills, inherit_project_skills)
    records = selected_skill_records(effective_skills)
    skill_names = [str(item["name"]) for item in records]
    skill_blocks: list[str] = []
    for skill in records:
        block = f"## Skill：{skill['name']}\n{skill.get('content', '')}"
        attachments = text_attachment_context(skill)
        if attachments:
            block += f"\n\n## Skill 附件上下文\n{attachments}"
        skill_blocks.append(block)
    skill_context = "\n\n".join(skill_blocks)
    corpus_context = project_corpus_context(project)
    selected_material_ids = set(parse_lines(payload.get("material_ids")))
    project_materials = list_project_material_records(str(project.get("id", "")))
    selected_materials = [item for item in project_materials if str(item.get("id")) in selected_material_ids]
    material_context = "\n\n".join(
        f"### 研发素材：{item.get('name', '未命名')}\n{str(item.get('extracted_text', '')).strip()[:40_000]}"
        for item in selected_materials
        if str(item.get("extracted_text", "")).strip()
    ) or "暂无本次选择的研发素材。"
    generation_mode = str(payload.get("generation_mode", "new")).strip().lower()
    if generation_mode == "optimize":
        mode_instruction = "这是 Topic 优化：只优化语言、结构、术语一致性和表达清晰度，不改变业务事实，不擅自新增功能，尽量保留原 XML 标签结构。"
    elif normalize_project_mode(project.get("mode", "new")) == "update":
        mode_instruction = "这是版本更新：基于上一版 Topic 和本次输入材料更新内容，允许新增、删除或调整必要的 XML 结构，但不得编造事实。"
    else:
        mode_instruction = "这是全新 Topic：根据当前已确认材料从零编写。"
    system = f"""你是 HIK 文档开发工具中的 Topic/XML 生成器。你必须严格遵守用户提供的 Skill。

输出要求：
1. 只输出一个可解析的 DITA XML 文档，不输出解释、Markdown 代码围栏或前后说明。
2. Topic 类型只能是 Concept 或 Task。Reference 当前不生成。
3. 不生成 GUID、GUID=xxx、GUID-xxx 或任何 GUID Token。XML id 使用稳定、可读且非 GUID 的英文或拼音标识。
4. 图片引用使用 TODO_IMAGE，交叉引用使用 TODO_REF。保留占位符，供工程师后续手动替换。
5. 事实不足时不要编造具体参数、按钮、数值或业务行为；使用“请根据已确认需求补充”或在正文中明确标注待确认内容。
6. Concept 使用 conbody 和 section；Task 使用 taskbody、prereq、steps。每个操作步骤只包含一个动作。
7. 文案遵守海康写作规范：使用“您”、使用“单击”、保持术语一致，数字和单位规范。
8. {mode_instruction}
"""
    outline = parse_outline_items(payload.get("outline"))
    user = f"""请基于以下信息生成 {type_name} Topic XML。

## 项目信息
- 项目：{project.get('name', '')}
- 产品/模块：{project.get('product', '') or '未提供'}
- 版本：{project.get('version', '') or '未提供'}

## Topic 信息
- 标题：{sanitize_text(payload.get('title'))}
- 短描述：{sanitize_text(payload.get('shortdesc'))}
- 标题层级：{topic_level(payload.get('heading_level', 1))} 级
- 章节概述：{sanitize_text(payload.get('chapter_summary')) or '未提供'}
- 需求/正文要点：{sanitize_text(payload.get('brief')) or '未提供'}
- 本次生成提示词：{sanitize_text(payload.get('generation_prompt')) or '无'}
- 章节标题：{json.dumps(outline, ensure_ascii=False)}
- 前置条件：{json.dumps(parse_lines(payload.get('prerequisites')), ensure_ascii=False)}
- 操作步骤：{json.dumps(parse_lines(payload.get('steps')), ensure_ascii=False)}
- 是否需要图片占位符：{'是' if payload.get('include_image_placeholder') else '否'}
- 是否需要引用占位符：{'是' if payload.get('include_ref_placeholder') else '否'}
- 本次生成模式：{generation_mode}

## 已选 Skill
{skill_context}

## 本次选择的研发素材
{material_context}

## 上一版 XML（仅在重生成时提供）
{sanitize_text(payload.get('previous_xml'))[:60000] or '无'}

## 参考项目实时语料库
以下内容仅作为术语、结构和表达参考，不能替代当前项目材料，也不能直接引入其中未被当前需求确认的业务事实。
{corpus_context or '暂无参考项目语料。'}

请只返回最终 XML。"""
    return system, user, skill_names


def call_ai_text(settings: dict[str, Any], system: str, user: str, max_tokens: int = 6000) -> tuple[str, str]:
    provider = str(settings.get("provider", "openai-compatible"))
    model = str(settings.get("model", "")).strip()
    if not model and provider != "local":
        raise ValueError("请先填写模型名称。")
    endpoint = endpoint_for(settings)
    api_key = KEYCHAIN.get()
    if provider != "local" and not api_key:
        raise ValueError("尚未配置 API Key，请先在“AI 服务配置”中保存。")
    if provider == "anthropic":
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": float(settings.get("temperature", 0.2)),
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {"Content-Type": "application/json", "x-api-key": api_key or "", "anthropic-version": "2023-06-01"}
    else:
        body = {
            "model": model,
            "temperature": float(settings.get("temperature", 0.2)),
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(endpoint, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
    try:
        with open_ai_request(request, endpoint, timeout=int(settings.get("timeout_seconds", 60))) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"AI 服务返回 HTTP {exc.code}（请求地址：{endpoint}）：{message[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"AI 服务连接失败（请求地址：{endpoint}）：{exc.reason}") from exc
    except ConnectionRefusedError as exc:
        raise RuntimeError(f"模型地址拒绝连接：{endpoint}") from exc
    except TimeoutError as exc:
        raise RuntimeError("AI 生成请求超时，请检查地址或超时设置。") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("AI 服务返回的内容不是有效 JSON。") from exc
    text = ai_response_text(data, provider).strip()
    if not text:
        raise RuntimeError("AI 服务未返回文本内容。")
    return text, model or "本地模型"


def call_ai_generation(settings: dict[str, Any], system: str, user: str) -> tuple[str, str]:
    text, model = call_ai_text(settings, system, user, max_tokens=6000)
    xml_text = clean_ai_xml(text)
    if not xml_text:
        raise RuntimeError("AI 服务未返回 XML 内容。")
    return xml_text, model


def generate_ai_topic(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    project = read_json(project_dir(project_id) / "project.json", None)
    if not isinstance(project, dict):
        raise ValueError("项目不存在。")
    topic_type = str(payload.get("topic_type", "concept"))
    if topic_type not in TOPIC_TYPES:
        raise ValueError("Topic 类型仅支持 Concept、Task 或附录类 Concept。")
    title = sanitize_text(payload.get("title"))
    if not title:
        raise ValueError("Topic 标题不能为空。")
    system, user, skill_names = build_topic_ai_messages(project, payload)
    xml_text, model = call_ai_generation(load_settings(), system, user)
    validation = validate_topic_xml(xml_text)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(f"AI 返回的 XML 无法解析：{exc}") from exc
    expected_root = "task" if topic_type == "task" else "concept"
    if root.tag != expected_root:
        raise RuntimeError(f"AI 返回的根标签为 <{root.tag}>，预期为 <{expected_root}>。")
    inherit_project_skills = payload.get("inherit_project_skills", True) is not False
    overrides = topic_skill_overrides(project, payload.get("skills", project.get("skills", [])), inherit_project_skills)
    return {
        "xml": xml_text,
        "validation": validation,
        "skills": skill_names,
        "skill_snapshot": skill_usage_snapshot(skill_names, project),
        "skill_snapshot": skill_usage_snapshot(skill_names, project, overrides, inherit_project_skills),
        "model": model,
        "source": "ai",
        "generated_at": now_iso(),
    }


def normalize_analysis_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError("AI 返回的需求分析不是 JSON 对象。")
    if isinstance(value.get("analysis"), dict):
        value = value["analysis"]

    def text_value(item: Any, key: str, default: str = "") -> str:
        return sanitize_text(item.get(key, default)) if isinstance(item, dict) else default

    def source_values(item: Any) -> list[str]:
        if not isinstance(item, dict):
            return []
        sources = item.get("source_materials", item.get("sources", []))
        if isinstance(sources, str):
            return parse_lines(sources)
        return parse_lines(sources) if isinstance(sources, list) else []

    def object_list(key: str, fields: list[str]) -> list[dict[str, Any]]:
        raw_items = value.get(key, [])
        if not isinstance(raw_items, list):
            return []
        result: list[dict[str, Any]] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            item = {field: text_value(raw_item, field) for field in fields}
            item["source_materials"] = source_values(raw_item)
            result.append(item)
        return result[:100]

    raw_outline = value.get("topic_outline", value.get("outline", []))
    outline: list[dict[str, Any]] = []
    if isinstance(raw_outline, list):
        for raw_item in raw_outline[:100]:
            if not isinstance(raw_item, dict):
                continue
            raw_type = str(raw_item.get("type", "concept")).lower()
            topic_type = "task" if raw_type == "task" else "concept"
            outline.append(
                {
                    "title": text_value(raw_item, "title"),
                    "type": topic_type,
                    "level": topic_level(raw_item.get("level", 1)),
                    "shortdesc": text_value(raw_item, "shortdesc"),
                    "basis": text_value(raw_item, "basis", raw_item.get("reason", "")),
                    "change_status": text_value(raw_item, "change_status", "added"),
                    "source_materials": source_values(raw_item),
                }
            )
    return {
        "summary": sanitize_text(value.get("summary", value.get("需求摘要", ""))),
        "confirmed_items": object_list("confirmed_items", ["item", "evidence", "confidence"]),
        "missing_materials": object_list("missing_materials", ["item", "reason", "suggestion"]),
        "questions": object_list("questions", ["question", "reason", "owner", "priority"]),
        "topic_outline": [item for item in outline if item["title"]],
    }


def build_requirements_analysis_messages(
    project: dict[str, Any], payload: dict[str, Any], materials: list[dict[str, Any]]
) -> tuple[str, str, list[str]]:
    records = selected_skill_records(payload.get("skills") or project.get("skills", []))
    skill_names = [str(item["name"]) for item in records]
    skill_blocks: list[str] = []
    for skill in records:
        block = f"## Skill：{skill['name']}\n{skill.get('content', '')}"
        attachments = text_attachment_context(skill)
        if attachments:
            block += f"\n\n## Skill 附件上下文\n{attachments}"
        skill_blocks.append(block)

    material_blocks: list[str] = []
    material_budget = 180_000
    for material in materials:
        text = str(material.get("extracted_text", "")).strip()
        status = str(material.get("extract_status", "unsupported"))
        message = str(material.get("extract_message", ""))
        if text:
            remaining = max(0, material_budget - sum(len(block) for block in material_blocks))
            if remaining <= 0:
                material_blocks.append(f"### 材料：{material.get('name', '未命名')}\n- 文本未送入 AI：已达到本次分析上下文上限。")
                continue
            text = text[:remaining]
            material_blocks.append(
                f"### 材料：{material.get('name', '未命名')}\n"
                f"- 提取状态：{status}\n{text}"
            )
        else:
            material_blocks.append(
                f"### 材料：{material.get('name', '未命名')}\n"
                f"- 提取状态：{status}\n- 处理说明：{message or '暂无可读取文本'}"
            )
    material_context = "\n\n".join(material_blocks)
    corpus_context = project_corpus_context(project)
    mode = normalize_project_mode(project.get("mode", "new"))
    mode_instruction = {
        "new": "从零梳理当前需求，输出全新文档框架。",
        "update": "结合复制进来的上版本框架和 Topic，识别新增、修改、废弃、未变化项，并在 topic_outline 中填写 change_status。",
        "optimize": "重点分析目标 Topic 的语言和结构问题，不因为优化表达而擅自改变业务范围。",
    }[mode]
    baseline_context = project_baseline_context(project) if mode != "new" else ""
    system = f"""你是 HIK 文档开发工具中的需求分析器。请严格遵守已选 Skill，并且只根据输入材料分析，不得补造业务事实。

输出要求：
1. 只输出一个有效 JSON 对象，不输出 Markdown 代码围栏、解释或前后说明。
2. 必须包含 summary、confirmed_items、missing_materials、questions、topic_outline 五个字段。
3. confirmed_items 的元素包含 item、evidence、confidence、source_materials。
4. missing_materials 的元素包含 item、reason、suggestion、source_materials。
5. questions 的元素包含 question、reason、owner、priority、source_materials。
6. topic_outline 的元素包含 title、type、level、shortdesc、basis、source_materials。type 只能是 concept 或 task，当前不要生成 Reference。
7. 无法从材料确认的信息放入 questions 或 missing_materials，不要放入 confirmed_items；不得编造参数、按钮、数值、版本行为或 XML 属性。
8. 需求分析和 Topic 初稿都遵守 HIK Writing Skill：使用“您”、使用“单击”、概念和操作结构清晰、术语保持一致。
9. {mode_instruction}
"""
    user = f"""请分析以下项目材料，并输出可供文档工程师审核的需求分析结果。

## 项目信息
- 项目：{project.get('name', '')}
- 产品/模块：{project.get('product', '') or '未提供'}
- 版本：{project.get('version', '') or '未提供'}
- 分析补充要求：{sanitize_text(payload.get('analysis_note')) or '无'}
- 项目模式：{PROJECT_MODES[mode]}

## 已选 Skill
{chr(10).join(skill_blocks)}

## 原始材料提取内容
{material_context}

## 当前项目基线（版本更新或 Topic 优化项目）
{baseline_context or '无当前项目基线。'}

## 参考项目实时语料库
仅作为结构、术语和写作风格参考，不得将参考项目中未被当前材料确认的事实当作当前项目结论。
{corpus_context or '暂无参考项目语料。'}

请保留证据来源，优先使用材料文件名作为 source_materials。只返回 JSON。"""
    return system, user, skill_names


def generate_requirements_analysis(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    project = read_json(project_dir(project_id) / "project.json", None)
    if not isinstance(project, dict):
        raise ValueError("项目不存在。")
    records = list_project_material_records(project_id)
    if not records:
        raise ValueError("请先上传至少一份需求材料。")
    readable_records = [item for item in records if str(item.get("extracted_text", "")).strip()]
    if not readable_records:
        raise ValueError("当前材料均未成功提取文本，暂时无法开始 AI 分析。请补充 Markdown、Word 或可提取文本的 PDF。")
    system, user, skill_names = build_requirements_analysis_messages(project, payload, records)
    raw_text, model = call_ai_text(load_settings(), system, user, max_tokens=7000)
    try:
        parsed = json.loads(clean_ai_json(raw_text))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AI 返回的需求分析不是有效 JSON：{str(exc)[:240]}") from exc
    result = normalize_analysis_result(parsed)
    created_at = now_iso()
    analysis_id = f"analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(2)}"
    record = {
        "id": analysis_id,
        "project_id": project_id,
        "created_at": created_at,
        "source": "ai",
        "model": model,
        "skills": skill_names,
        "material_ids": [str(item.get("id")) for item in records],
        **result,
    }
    write_json(analysis_version_dir(project_id) / f"{analysis_id}.json", record)
    project["updated_at"] = created_at
    project["stage"] = "需求分析"
    write_json(project_dir(project_id) / "project.json", project)
    return analysis_record_summary(record)


class AppHandler(BaseHTTPRequestHandler):
    server_version = "LianJinLu/2.0.1"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{now_iso()}] {format % args}")

    def send_json(self, status: int, payload: Any) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_file(self, path: Path, content_type: str) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        if content_type.startswith("text/") and "charset=" not in content_type:
            content_type += "; charset=utf-8"
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_REQUEST_BYTES:
            raise ValueError("请求内容过大。")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("请求体必须是 JSON 对象。")
        return payload

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/ui-demos":
            self.send_file(WEB_DIR / "ui-demos.html", "text/html; charset=utf-8")
            return
        if path == "/main-demo":
            self.send_file(WEB_DIR / "main-demo.html", "text/html; charset=utf-8")
            return
        if path == "/":
            self.send_file(WEB_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path.startswith("/static/"):
            static_path = (WEB_DIR / unquote(path.removeprefix("/static/")).lstrip("/")).resolve()
            try:
                static_path.relative_to(WEB_DIR.resolve())
            except ValueError:
                self.send_error(404)
                return
            content_type = "text/plain; charset=utf-8"
            if static_path.suffix == ".css":
                content_type = "text/css; charset=utf-8"
            elif static_path.suffix == ".js":
                content_type = "text/javascript; charset=utf-8"
            elif static_path.suffix.lower() in IMAGE_EXTENSIONS:
                content_type = image_content_type(static_path)
            self.send_file(static_path, content_type)
            return
        try:
            if path == "/api/health":
                self.send_json(200, {"ok": True, "app": "炼金炉", "version": "2.0.1"})
            elif path == "/api/assets":
                self.send_json(200, {"assets": list_editorial_assets()})
            elif path == "/api/settings":
                self.send_json(200, public_settings())
            elif path == "/api/skills":
                self.send_json(200, {"skills": list_skills()})
            elif path == "/api/projects":
                self.send_json(200, {"projects": list_projects()})
            elif path.startswith("/api/skills/"):
                parts = [unquote(item) for item in path.removeprefix("/api/skills/").split("/") if item]
                skill_id = parts[0] if parts else ""
                if len(parts) == 3 and parts[1] == "attachments":
                    attachment = get_skill_attachment_file(skill_id, parts[2])
                    if attachment:
                        self.send_file(*attachment)
                    else:
                        self.send_error(404)
                else:
                    skill = next((item for item in list_skills() if item["id"] == skill_id), None)
                    self.send_json(200 if skill else 404, skill or {"error": "Skill 不存在。"})
            elif path.startswith("/api/projects/"):
                parts = [unquote(item) for item in path.removeprefix("/api/projects/").split("/") if item]
                project_id = parts[0] if parts else ""
                if len(parts) == 2 and parts[1] == "cover":
                    project = read_json(project_dir(project_id) / "project.json", None)
                    cover = project.get("cover") if isinstance(project, dict) else None
                    cover_path = project_dir(project_id) / Path(str(cover.get("file", ""))).name if isinstance(cover, dict) else None
                    if isinstance(cover_path, Path) and cover_path.exists() and cover_path.is_file():
                        self.send_file(cover_path, image_content_type(cover_path))
                    else:
                        self.send_error(404)
                elif len(parts) == 2 and parts[1] == "materials":
                    self.send_json(200, {"materials": list_project_materials(project_id)})
                elif len(parts) == 4 and parts[1] == "materials" and parts[3] == "download":
                    material_file = get_project_material_file(project_id, parts[2])
                    if material_file:
                        self.send_file(*material_file)
                    else:
                        self.send_error(404)
                elif len(parts) == 4 and parts[1] == "materials" and parts[3] == "content":
                    material = get_project_material(project_id, parts[2])
                    self.send_json(200 if material else 404, {"text": str(material.get("extracted_text", ""))} if material else {"error": "材料不存在。"})
                elif len(parts) == 2 and parts[1] == "analysis":
                    records = list_analysis_records(project_id)
                    latest = analysis_record_summary(records[-1]) if records else None
                    self.send_json(200, {"latest": latest, "versions": public_analysis_versions(project_id)})
                elif len(parts) == 2 and parts[1] == "corpus":
                    project = read_json(project_dir(project_id) / "project.json", None)
                    if not isinstance(project, dict):
                        self.send_json(404, {"error": "项目不存在。"})
                    else:
                        self.send_json(200, project_corpus_summary(project))
                elif len(parts) == 2 and parts[1] == "framework":
                    framework = get_framework(project_id)
                    self.send_json(200 if framework else 404, framework or {"error": "项目不存在。"})
                elif len(parts) == 3 and parts[1] == "analysis":
                    record = read_json(analysis_version_dir(project_id) / f"{Path(parts[2]).name}.json", None)
                    self.send_json(200 if isinstance(record, dict) else 404, analysis_record_summary(record) if isinstance(record, dict) else {"error": "分析记录不存在。"})
                elif len(parts) == 2 and parts[1] == "topics":
                    self.send_json(200, {"topics": list_topics(project_id)})
                elif len(parts) == 3 and parts[1] == "topics":
                    topic = get_topic(project_id, parts[2])
                    self.send_json(200 if topic else 404, topic or {"error": "Topic 不存在。"})
                else:
                    project = get_project(project_id)
                    self.send_json(200 if project else 404, project or {"error": "项目不存在。"})
            else:
                self.send_json(404, {"error": "接口不存在。"})
        except Exception as exc:  # pragma: no cover - boundary guard
            self.send_json(500, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/projects":
                self.send_json(201, create_project(self.read_body()))
            elif path == "/api/skills":
                self.send_json(201, create_skill(self.read_body()))
            elif path.startswith("/api/projects/") and path.endswith("/materials"):
                project_id = unquote(path.removeprefix("/api/projects/").removesuffix("/materials").strip("/"))
                self.send_json(201, save_project_material(project_id, self.read_body()))
            elif path.startswith("/api/projects/") and path.endswith("/framework/import-excel"):
                project_id = unquote(path.removeprefix("/api/projects/").removesuffix("/framework/import-excel").strip("/"))
                project = get_project(project_id)
                if not project: raise ValueError("项目不存在。")
                name, _, raw = decode_material(self.read_body())
                extension = Path(name).suffix.lower()
                if extension == ".xls": raise ValueError("旧版 .xls 暂不支持，请另存为 .xlsx。")
                if extension in {".xlsx", ".xlsm"}:
                    markdown, sheet_name = extract_xlsx_framework(raw)
                elif extension in {".docx", ".txt", ".md", ".markdown"}:
                    temp_path = Path(tempfile.mkdtemp(prefix="lianjinlu_import_")) / name
                    temp_path.write_bytes(raw)
                    extracted, status, message = extract_material_text(temp_path)
                    if status != "success": raise ValueError(message)
                    markdown, sheet_name = text_to_framework_markdown(extracted, Path(name).stem), Path(name).name
                else:
                    raise ValueError("框架导入支持 .xlsx、.docx、.md、.txt；旧版 .xls 请先另存为 .xlsx。")
                if not markdown: raise ValueError("未找到可识别的框架页签或内容。")
                self.send_json(200, {"markdown": markdown, "sheet_name": sheet_name})
            elif path.startswith("/api/projects/") and path.endswith("/framework/generate"):
                project_id = unquote(path.removeprefix("/api/projects/").removesuffix("/framework/generate").strip("/"))
                self.send_json(201, generate_framework(project_id, self.read_body()))
            elif path.startswith("/api/projects/") and path.endswith("/topics/generate"):
                project_id = unquote(path.removeprefix("/api/projects/").removesuffix("/topics/generate").strip("/"))
                self.send_json(201, create_topic(project_id, self.read_body()))
            elif path.startswith("/api/projects/") and path.endswith("/generate") and "/topics/" in path:
                raw = path.removeprefix("/api/projects/").split("/topics/", 1)
                project_id = unquote(raw[0])
                topic_id = unquote(raw[1].removesuffix("/generate").strip("/"))
                self.send_json(200, regenerate_topic(project_id, topic_id, self.read_body()))
            elif path.startswith("/api/projects/") and path.endswith("/analysis"):
                project_id = unquote(path.removeprefix("/api/projects/").removesuffix("/analysis").strip("/"))
                self.send_json(201, generate_requirements_analysis(project_id, self.read_body()))
            elif path.startswith("/api/projects/") and path.endswith("/topics"):
                project_id = unquote(path.removeprefix("/api/projects/").removesuffix("/topics").strip("/"))
                self.send_json(201, create_topic(project_id, self.read_body()))
            elif path == "/api/settings/test":
                self.send_json(200, test_ai_connection())
            else:
                self.send_json(404, {"error": "接口不存在。"})
        except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:  # pragma: no cover - boundary guard
            self.send_json(500, {"error": str(exc)})

    def do_PUT(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/settings":
                self.send_json(200, update_settings(self.read_body()))
            elif path.startswith("/api/skills/"):
                skill_id = unquote(path.removeprefix("/api/skills/").strip("/"))
                self.send_json(200, update_skill(skill_id, self.read_body()))
            elif path.startswith("/api/projects/"):
                parts = [unquote(item) for item in path.removeprefix("/api/projects/").split("/") if item]
                if len(parts) == 3 and parts[1] == "topics" and parts[2] == "order":
                    self.send_json(200, {"topics": save_topic_order(parts[0], self.read_body())})
                elif len(parts) == 3 and parts[1] == "topics":
                    self.send_json(200, update_topic_xml(parts[0], parts[2], self.read_body()))
                elif len(parts) == 3 and parts[1] == "materials":
                    payload = self.read_body()
                    self.send_json(200, update_project_material_text(parts[0], parts[2], str(payload.get("text", ""))))
                elif len(parts) == 2 and parts[1] == "framework":
                    self.send_json(200, save_framework(parts[0], self.read_body()))
                elif len(parts) == 1:
                    self.send_json(200, update_project_metadata(parts[0], self.read_body()))
                else:
                    self.send_json(404, {"error": "接口不存在。"})
            else:
                self.send_json(404, {"error": "接口不存在。"})
        except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:  # pragma: no cover - boundary guard
            self.send_json(500, {"error": str(exc)})

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path.startswith("/api/projects/"):
                parts = [unquote(item) for item in path.removeprefix("/api/projects/").split("/") if item]
                if len(parts) == 3 and parts[1] == "materials":
                    delete_project_material(parts[0], parts[2])
                    self.send_json(200, {"ok": True})
                else:
                    self.send_json(404, {"error": "接口不存在。"})
            elif path.startswith("/api/skills/"):
                skill_id = unquote(path.removeprefix("/api/skills/").strip("/"))
                delete_skill(skill_id)
                self.send_json(200, {"ok": True})
            else:
                self.send_json(404, {"error": "接口不存在。"})
        except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:  # pragma: no cover - boundary guard
            self.send_json(500, {"error": str(exc)})


def main() -> None:
    ensure_dirs()
    migrated = migrate_legacy_projects()
    if migrated:
        print(f"已迁移旧项目 Skill 配置：{migrated} 项记录")
    host = "127.0.0.1"
    port = 8765
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"炼金炉已启动：http://{host}:{port}")
    print(f"数据目录：{DATA_DIR}")
    if not KEYCHAIN.available:
        print("警告：当前未检测到可用的系统凭据存储，API Key 保存功能不可用。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n炼金炉已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

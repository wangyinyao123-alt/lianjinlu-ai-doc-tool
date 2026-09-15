#!/usr/bin/env python3
"""炼金炉：阶段 1 本地原型服务。

当前范围：
- 本地项目创建、读取和持久化；
- AI 服务配置；
- macOS Keychain / Windows Credential Manager 中保存 API Key；
- OpenAI 兼容接口 / Anthropic 接口连通性测试；
- 提供浏览器界面，后续可封装为桌面应用。
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import mimetypes
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
TOPIC_TYPES = {"concept": "Concept", "task": "Task", "appendix": "附录类 Concept"}
MATERIAL_TEXT_EXTENSIONS = {
    ".md", ".markdown", ".txt", ".html", ".htm", ".xml", ".json", ".csv", ".yaml", ".yml"
}
MATERIAL_EXTENSIONS = MATERIAL_TEXT_EXTENSIONS | {".doc", ".docx", ".pdf", ".chm"}
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


def normalize_skills(value: Any) -> list[str]:
    skills = parse_lines(value)
    return [HIK_SKILL] + [skill for skill in skills if skill != HIK_SKILL]


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


def builtin_hik_skill() -> dict[str, Any]:
    return {
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
    }


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
    result = [builtin_hik_skill()]
    if SKILLS_DIR.exists():
        for path in sorted(SKILLS_DIR.glob("skill_*.json"), key=lambda item: item.name.lower()):
            skill = read_json(path, None)
            if isinstance(skill, dict) and skill.get("id") and skill.get("name"):
                result.append(skill_summary(skill))
    return result


def get_skill_record(skill_id: str) -> dict[str, Any] | None:
    if skill_id == "hik-writing":
        return builtin_hik_skill()
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
    if skill_id == "hik-writing":
        raise ValueError("HIK Writing Skill 为内置必选 Skill，不支持编辑。")
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
    if skill_id == "hik-writing":
        raise ValueError("HIK Writing Skill 为内置必选 Skill，不支持删除。")
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
    """Use the native credential store on macOS and Windows."""

    def __init__(self) -> None:
        if sys.platform == "darwin" and shutil.which("security") is not None:
            self.backend = "macOS Keychain"
        elif sys.platform == "win32":
            self.backend = "Windows Credential Manager"
        else:
            self.backend = None
        self.available = bool(self.backend)

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
            ctypes, _credential_type, api = self._windows_api()
            pointer = ctypes.POINTER(_credential_type)()
            if not api.CredReadW(self._windows_target(), 1, 0, ctypes.byref(pointer)):
                return None
            try:
                credential = pointer.contents
                raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
                return raw.decode("utf-8") or None
            finally:
                api.CredFree(pointer)
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
            ctypes, credential_type, api = self._windows_api()
            raw = value.encode("utf-8")
            buffer = ctypes.create_string_buffer(raw)
            credential = credential_type()
            credential.Type = 1  # CRED_TYPE_GENERIC
            credential.TargetName = self._windows_target()
            credential.CredentialBlobSize = len(raw)
            credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
            credential.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
            credential.UserName = KEYCHAIN_ACCOUNT
            if not api.CredWriteW(ctypes.byref(credential), 0):
                error = ctypes.get_last_error()
                raise RuntimeError(f"写入 Windows Credential Manager 失败（错误码 {error}）。")
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
    return {
        **topic,
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
        "skills": normalize_skills(payload.get("skills") or project.get("skills", [])),
        "heading_level": heading_level,
        "level": heading_level,
        "order": len(existing_topics),
        "parent_id": None,
        "include_image_placeholder": bool(payload.get("include_image_placeholder")),
        "include_ref_placeholder": bool(payload.get("include_ref_placeholder")),
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
    return topic_summary(project_id, topic)


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
    directory = project_dir(project_id)
    for child in ("materials", "outputs", "versions", "topics"):
        (directory / child).mkdir(parents=True, exist_ok=True)
    cover = save_project_cover(payload.get("cover"), directory)
    timestamp = now_iso()
    project = {
        "id": project_id,
        "name": name,
        "product": str(payload.get("product", "")).strip(),
        "version": str(payload.get("version", "")).strip(),
        "description": str(payload.get("description", "")).strip(),
        "stage": "需求分析",
        "created_at": timestamp,
        "updated_at": timestamp,
        "skills": normalize_skills(payload.get("skills")),
        "topic_modes": ["new"],
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
    records = selected_skill_records(payload.get("skills") or project.get("skills", []))
    skill_names = [str(item["name"]) for item in records]
    skill_blocks: list[str] = []
    for skill in records:
        block = f"## Skill：{skill['name']}\n{skill.get('content', '')}"
        attachments = text_attachment_context(skill)
        if attachments:
            block += f"\n\n## Skill 附件上下文\n{attachments}"
        skill_blocks.append(block)
    skill_context = "\n\n".join(skill_blocks)
    system = """你是 HIK 文档开发工具中的 Topic/XML 生成器。你必须严格遵守用户提供的 Skill。

输出要求：
1. 只输出一个可解析的 DITA XML 文档，不输出解释、Markdown 代码围栏或前后说明。
2. Topic 类型只能是 Concept 或 Task。Reference 当前不生成。
3. 不生成 GUID、GUID=xxx、GUID-xxx 或任何 GUID Token。XML id 使用稳定、可读且非 GUID 的英文或拼音标识。
4. 图片引用使用 TODO_IMAGE，交叉引用使用 TODO_REF。保留占位符，供工程师后续手动替换。
5. 事实不足时不要编造具体参数、按钮、数值或业务行为；使用“请根据已确认需求补充”或在正文中明确标注待确认内容。
6. Concept 使用 conbody 和 section；Task 使用 taskbody、prereq、steps。每个操作步骤只包含一个动作。
7. 文案遵守海康写作规范：使用“您”、使用“单击”、保持术语一致，数字和单位规范。
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
- 需求/正文要点：{sanitize_text(payload.get('brief')) or '未提供'}
- 章节标题：{json.dumps(outline, ensure_ascii=False)}
- 前置条件：{json.dumps(parse_lines(payload.get('prerequisites')), ensure_ascii=False)}
- 操作步骤：{json.dumps(parse_lines(payload.get('steps')), ensure_ascii=False)}
- 是否需要图片占位符：{'是' if payload.get('include_image_placeholder') else '否'}
- 是否需要引用占位符：{'是' if payload.get('include_ref_placeholder') else '否'}

## 已选 Skill
{skill_context}

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
    return {"xml": xml_text, "validation": validation, "skills": skill_names, "model": model, "source": "ai", "generated_at": now_iso()}


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
    system = """你是 HIK 文档开发工具中的需求分析器。请严格遵守已选 Skill，并且只根据输入材料分析，不得补造业务事实。

输出要求：
1. 只输出一个有效 JSON 对象，不输出 Markdown 代码围栏、解释或前后说明。
2. 必须包含 summary、confirmed_items、missing_materials、questions、topic_outline 五个字段。
3. confirmed_items 的元素包含 item、evidence、confidence、source_materials。
4. missing_materials 的元素包含 item、reason、suggestion、source_materials。
5. questions 的元素包含 question、reason、owner、priority、source_materials。
6. topic_outline 的元素包含 title、type、level、shortdesc、basis、source_materials。type 只能是 concept 或 task，当前不要生成 Reference。
7. 无法从材料确认的信息放入 questions 或 missing_materials，不要放入 confirmed_items；不得编造参数、按钮、数值、版本行为或 XML 属性。
8. 需求分析和 Topic 初稿都遵守 HIK Writing Skill：使用“您”、使用“单击”、概念和操作结构清晰、术语保持一致。
"""
    user = f"""请分析以下项目材料，并输出可供文档工程师审核的需求分析结果。

## 项目信息
- 项目：{project.get('name', '')}
- 产品/模块：{project.get('product', '') or '未提供'}
- 版本：{project.get('version', '') or '未提供'}
- 分析补充要求：{sanitize_text(payload.get('analysis_note')) or '无'}

## 已选 Skill
{chr(10).join(skill_blocks)}

## 原始材料提取内容
{material_context}

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
    server_version = "LianJinLu/0.1"

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
                self.send_json(200, {"ok": True, "app": "炼金炉", "version": "0.1"})
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
                elif len(parts) == 2 and parts[1] == "analysis":
                    records = list_analysis_records(project_id)
                    latest = analysis_record_summary(records[-1]) if records else None
                    self.send_json(200, {"latest": latest, "versions": public_analysis_versions(project_id)})
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

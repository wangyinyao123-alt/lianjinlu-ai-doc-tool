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
import hashlib
import io
import ipaddress
import json
import mimetypes
import os
import posixpath
import queue
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from contextlib import contextmanager
from functools import wraps
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile
from xml.sax.saxutils import escape as xml_escape
from urllib.parse import parse_qs, quote, unquote, urlparse


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
# 目录导入：单次最多勘察/导入的文件数，以及扫描时跳过的目录名
DIR_IMPORT_MAX_FILES = 500
DIR_IMPORT_SKIP_DIRS = {
    "node_modules", "__pycache__", ".git", ".svn", ".hg", ".venv", "venv", "env",
    "dist", "build", "target", ".idea", ".vscode", ".cache", "site-packages",
}
MAX_ATTACHMENT_BYTES = 12 * 1024 * 1024
MAX_SKILL_ATTACHMENTS = 20
# Global prompt budget (characters, incl. CJK). Roughly fits a 128k-token model.
DEFAULT_CONTEXT_CHAR_BUDGET = 200_000
DEFAULT_FRAMEWORK_MAX_TOKENS = 9000
DEFAULT_TOPIC_MAX_TOKENS = 6000
DEFAULT_ANALYSIS_MAX_TOKENS = 7000
HIK_SKILL = "HIK Writing Skill"
HIK_DITA_RULE_SKILL = "HIK DITA Rule"
BUILTIN_SKILL_IDS = {"hik-writing", "hik-dita-rule"}
PROJECT_MODES = {"new": "全新开发", "update": "版本更新", "optimize": "Topic 优化"}
# 项目封面循环色板（B11 薄荷芭乐主题）：deepmint / rose / guava / lime / cocoa
PROJECT_COLOR_PALETTE = ["deepmint", "rose", "guava", "lime", "cocoa"]
TOPIC_TYPES = {"concept": "Concept", "task": "Task", "appendix": "附录类 Concept"}
MATERIAL_TEXT_EXTENSIONS = {
    ".md", ".markdown", ".txt", ".html", ".htm", ".xml", ".json", ".csv", ".yaml", ".yml",
    ".rst", ".tex", ".log", ".diff", ".patch",
    # 代码与配置：需求交底、样例脚本、参数文件在工程里常以这些形式存在
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue", ".svelte",
    ".java", ".kt", ".scala", ".go", ".rs", ".rb", ".php", ".cs", ".swift", ".m", ".mm",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".lua", ".pl", ".r", ".jl", ".dart",
    ".sql", ".sh", ".bash", ".zsh", ".bat", ".cmd", ".ps1",
    ".ini", ".toml", ".conf", ".cfg", ".properties",
    ".css", ".scss", ".less", ".gradle", ".cmake",
}
MATERIAL_EXTENSIONS = MATERIAL_TEXT_EXTENSIONS | {".doc", ".docx", ".pdf", ".chm", ".xlsx", ".xls"}
# zip 容器 + XML 的文档格式：直接读包内正文（pptx/odt/epub/xmind…）
ZIP_TEXT_EXTENSIONS = {
    ".pptx", ".pptm", ".ppsx", ".potx", ".odt", ".odp", ".ods", ".epub", ".xmind",
    ".pages", ".numbers", ".key", ".sketch", ".kth", ".krz",
}
# 确实读不出文字的格式（图片/音视频/字体/可执行/压缩包），按类型给出原因
NO_TEXT_EXTENSIONS = {
    **{ext: "图片格式，取不到文字" for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".ico", ".heic", ".heif", ".raw", ".cr2", ".nef", ".psd", ".ai", ".eps")},
    **{ext: "音视频格式，取不到文字" for ext in (".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".webm", ".amr")},
    **{ext: "字体文件，取不到正文" for ext in (".ttf", ".otf", ".woff", ".woff2", ".eot")},
    **{ext: "可执行/二进制文件，取不到文字" for ext in (".exe", ".dll", ".so", ".dylib", ".bin", ".iso", ".dmg", ".pkg", ".msi", ".class", ".pyc", ".o", ".a", ".lib", ".jar", ".apk", ".ipa")},
    **{ext: "压缩包，请解压后再导入目录" for ext in (".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".cab")},
}
# KC GUID 样例：GUID-0007E23C-6BE9-4DB4-A8AB-233CE6EA1815（阶段0 文档确认）。
# 收紧为 8-4-4-4-12 十六进制段，避免误伤 "GUID-based" 这类英文正文。
GUID_PATTERN = re.compile(r"GUID[-=][0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}")
PLACEHOLDER_PATTERN = re.compile(r"\bTODO_(?:IMAGE|REF)\b")
CONFIRM_PATTERN = re.compile(r"\bTODO_CONFIRM\b")
# 超过该长度的单份素材在 Topic 生成时按主题相关性切片（含原文偏移，便于溯源）。
TOPIC_SLICE_MAX_CHARS = 40_000
DATA_LOCK = threading.RLock()
BACKGROUND_JOBS: dict[str, dict[str, Any]] = {}
BACKGROUND_JOBS_LOCK = threading.RLock()
JOB_CONTEXT = threading.local()
# 线程级配置覆盖：并行子 Agent 在各自线程里用档案配置替换主配置，
# 让下游 load_settings() 自然读到本 Agent 的模型/地址/Key，而不必改所有函数签名。
SETTINGS_CONTEXT = threading.local()
GENERATION_SLOT_COUNT = 2
GENERATION_SLOTS = threading.BoundedSemaphore(GENERATION_SLOT_COUNT)
# 429/5xx 退避重试：第 n 次重试等待 BACKOFF[n] 秒（有 Retry-After 时以响应头为准）。
AI_RETRY_BACKOFF = (2.0, 5.0, 10.0)
AI_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_PARALLEL_DEFAULT = 6
BATCH_CHUNK_DEFAULT = 20
JOB_HISTORY_KEEP = 20


class AdaptiveLimiter:
    """AI 请求闸门：正常时按上限放行，遇到 429 逐步收缩并发，安静一段时间后回升。

    单批最多 6 个线程，但中转站往往扛不住 6 路持续打满。收缩而不是硬失败，
    能显著降低「跑一半全变 failed」的概率。
    """

    def __init__(self, limit: int, floor: int = 1) -> None:
        self._cond = threading.Condition()
        self.ceiling = max(floor, limit)
        self.floor = floor
        self.limit = self.ceiling
        self.active = 0
        self._calm_at = 0.0

    @contextmanager
    def slot(self):
        with self._cond:
            while self.active >= self.limit:
                # 带上限的等待：即使 limit 被收缩到低于 active，也不会永久卡死。
                self._cond.wait(5.0)
            self.active += 1
        try:
            yield
        finally:
            with self._cond:
                self.active = max(0, self.active - 1)
                self._cond.notify()

    def on_rate_limited(self) -> int:
        with self._cond:
            self.limit = max(self.floor, self.limit - 1)
            self._calm_at = time.time() + 20.0
            return self.limit

    def allow(self, width: int) -> None:
        """配置允许更大的并行时抬高闸门，否则闸门会悄悄把并发压回 6。"""
        with self._cond:
            if width > self.ceiling:
                self.ceiling = width
                self.limit = max(self.limit, width)
                self._cond.notify_all()

    def on_success(self) -> None:
        with self._cond:
            if self.limit < self.ceiling and time.time() >= self._calm_at:
                self.limit += 1
                self._cond.notify()


AI_REQUEST_GATE = AdaptiveLimiter(MAX_PARALLEL_DEFAULT)


def max_parallel_workers(settings: dict[str, Any] | None = None) -> int:
    settings = settings if isinstance(settings, dict) else load_settings()
    try:
        value = int(settings.get("max_parallel_workers") or MAX_PARALLEL_DEFAULT)
    except (TypeError, ValueError):
        value = MAX_PARALLEL_DEFAULT
    return max(1, min(value, 12))


def batch_chunk_size(settings: dict[str, Any] | None = None, override: Any = None) -> int:
    raw = override if override not in (None, "") else (settings or load_settings()).get("batch_chunk_size")
    try:
        value = int(raw or BATCH_CHUNK_DEFAULT)
    except (TypeError, ValueError):
        value = BATCH_CHUNK_DEFAULT
    return max(1, min(value, 100))


def retry_after_seconds(exc: urllib.error.HTTPError, attempt: int) -> float:
    """优先用服务端 Retry-After，其次按指数退避。"""
    header = ""
    try:
        header = str((exc.headers or {}).get("Retry-After", "") or "").strip()
    except Exception:
        header = ""
    if header:
        try:
            return max(1.0, min(float(header), 30.0))
        except ValueError:
            pass
    index = min(attempt, len(AI_RETRY_BACKOFF) - 1)
    return AI_RETRY_BACKOFF[index]


class JobCancelled(RuntimeError):
    pass


def check_job_cancelled() -> None:
    job_id = getattr(JOB_CONTEXT, 'job_id', None)
    with BACKGROUND_JOBS_LOCK:
        if job_id and BACKGROUND_JOBS.get(job_id, {}).get('status') == 'cancelled':
            raise JobCancelled('任务已取消，生成结果不会写入项目。')


@contextmanager
def generation_commit():
    # Never hold these locks during an AI request. Cancellation and a short
    # disk commit are mutually exclusive; completed commits cannot be cancelled.
    with DATA_LOCK, BACKGROUND_JOBS_LOCK:
        check_job_cancelled()
        yield
        job = BACKGROUND_JOBS.get(getattr(JOB_CONTEXT, 'job_id', None))
        if job is not None:
            job['committed'] = True


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_job_id() -> str:
    return f"job_{int(time.time())}_{secrets.token_hex(5)}"


def prune_background_jobs(keep: int = JOB_HISTORY_KEEP) -> None:
    """任务表只保留最近 keep 条，避免长时间会话里结果越攒越多。

    仍在排队/运行的任务永不删除；只从最旧的已完成任务开始淘汰。
    """
    with BACKGROUND_JOBS_LOCK:
        if len(BACKGROUND_JOBS) <= keep:
            return
        ordered = sorted(BACKGROUND_JOBS.items(), key=lambda item: str(item[1].get("created_at", "")))
        for job_id, job in ordered:
            if len(BACKGROUND_JOBS) <= keep:
                break
            if job.get("status") in {"success", "failed", "cancelled"}:
                BACKGROUND_JOBS.pop(job_id, None)


def start_background_job(operation: str, callback) -> str:
    """Run an AI operation outside the HTTP request thread.

    The local app keeps the job registry in memory. Generated results are still
    written to the normal project version files by the existing callbacks, so a
    browser refresh does not lose completed work.
    """
    job_id = new_job_id()
    prune_background_jobs()
    with BACKGROUND_JOBS_LOCK:
        BACKGROUND_JOBS[job_id] = {
            "id": job_id,
            "operation": operation,
            "status": "queued",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "result": None,
            "error": None,
        }

    def worker() -> None:
        JOB_CONTEXT.job_id = job_id
        try:
            with GENERATION_SLOTS:
                with BACKGROUND_JOBS_LOCK:
                    check_job_cancelled()
                    job = BACKGROUND_JOBS[job_id]
                    job["status"] = "running"
                    job["updated_at"] = now_iso()
                result = callback()
                with BACKGROUND_JOBS_LOCK:
                    job = BACKGROUND_JOBS.get(job_id)
                    if job and job.get("status") != "cancelled":
                        job["status"] = "success"
                        job["result"] = result
                        job["updated_at"] = now_iso()
        except Exception as exc:  # pragma: no cover - worker boundary
            with BACKGROUND_JOBS_LOCK:
                job = BACKGROUND_JOBS.get(job_id)
                if job and job.get("status") != "cancelled":
                    job["status"] = "failed"
                    job["error"] = str(exc)
                    job["updated_at"] = now_iso()
        finally:
            del JOB_CONTEXT.job_id

    threading.Thread(target=worker, name=f"lianjinlu-{operation}", daemon=True).start()
    return job_id


def background_job_summary(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job.get("id"),
        "operation": job.get("operation"),
        "status": job.get("status"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "progress": job.get("progress"),
        "result": job.get("result") if job.get("status") == "success" else None,
        "error": job.get("error") if job.get("status") in {"failed", "cancelled"} else None,
    }


def update_job_progress(done: int, total: int, detail: str = "") -> None:
    """Publish coarse progress for long-running jobs (best effort, read-only UI)."""
    job_id = getattr(JOB_CONTEXT, "job_id", None)
    if not job_id:
        return
    with BACKGROUND_JOBS_LOCK:
        job = BACKGROUND_JOBS.get(job_id)
        if job is not None:
            job["progress"] = {"done": done, "total": total, "detail": detail, "updated_at": now_iso()}


def get_background_job(job_id: str) -> dict[str, Any] | None:
    with BACKGROUND_JOBS_LOCK:
        job = BACKGROUND_JOBS.get(job_id)
        if job is None:
            return None
        summary = background_job_summary(job)
        if job.get("status") == "queued":
            created = str(job.get("created_at", ""))
            ahead = 0
            for other_id, other in BACKGROUND_JOBS.items():
                if other_id == job_id:
                    continue
                status = other.get("status")
                if status == "running":
                    ahead += 1
                elif status == "queued" and str(other.get("created_at", "")) < created:
                    ahead += 1
            summary["queue"] = {
                "position": ahead + 1,
                "ahead": ahead,
                "slots": GENERATION_SLOT_COUNT,
            }
        return summary


def cancel_background_job(job_id: str) -> bool:
    with BACKGROUND_JOBS_LOCK:
        job = BACKGROUND_JOBS.get(job_id)
        if not job or job.get("committed") or job.get("status") in {"success", "failed", "cancelled"}:
            return False
        job["status"] = "cancelled"
        job["updated_at"] = now_iso()
        job["error"] = "任务已取消。"
        return True


def ensure_dirs() -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any) -> Any:
    with DATA_LOCK:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            corrupt = path.with_name(f"{path.name}.corrupt.{time.time_ns()}")
            shutil.copy2(path, corrupt)
            try:
                raw = path.with_suffix(path.suffix + '.bak').read_text(encoding='utf-8')
                restored = json.loads(raw)
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                raise ValueError(f'本地数据 {path.name} 损坏且无可用备份，已保留损坏副本，请恢复备份后重试。') from exc
            temporary = path.with_suffix(path.suffix + '.restore.tmp')
            temporary.write_text(raw, encoding='utf-8')
            temporary.replace(path)
            print(f'已从备份恢复 {path.name}；损坏副本：{corrupt.name}')
            return restored
        except OSError:
            return default


def write_json(path: Path, value: Any) -> None:
    with DATA_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            with temporary.open('w', encoding='utf-8') as stream:
                stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            if path.exists():
                read_json(path, None)
                backup_tmp = path.with_suffix(path.suffix + '.bak.tmp')
                shutil.copy2(path, backup_tmp)
                backup_tmp.replace(path.with_suffix(path.suffix + '.bak'))
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def synchronized(func):
    """Serialize small read/modify/write operations in the local store."""
    @wraps(func)
    def wrapped(*args, **kwargs):
        with DATA_LOCK:
            return func(*args, **kwargs)
    return wrapped


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


class PromptSection:
    """One labelled block of prompt context with a trim priority (1 = keep longest)."""

    def __init__(self, key: str, title: str, priority: int, text: str):
        self.key = key
        self.title = title
        self.priority = max(1, int(priority))
        self.text = str(text or "")


def context_char_budget(settings: dict[str, Any] | None = None) -> int:
    """Total character budget shared by all context sections of one AI prompt."""
    source = settings if isinstance(settings, dict) else load_settings()
    try:
        value = int(source.get("context_char_budget") or 0)
    except (TypeError, ValueError):
        value = 0
    return value if value >= 40_000 else DEFAULT_CONTEXT_CHAR_BUDGET


def fit_prompt_sections(sections: list[PromptSection], budget: int) -> tuple[list[PromptSection], list[dict[str, Any]]]:
    """Waterfall-trim sections by priority so their total length fits the budget.

    Returns the sections (original order, texts trimmed in place) plus a report
    listing every section that was truncated or dropped, for UI transparency.
    """
    remaining = max(0, budget)
    kept: dict[str, str] = {}
    report: list[dict[str, Any]] = []
    for section in sorted(sections, key=lambda item: (item.priority, item.key)):
        total = len(section.text)
        if remaining <= 0:
            kept[section.key] = ""
            report.append({"key": section.key, "title": section.title, "total_chars": total, "kept_chars": 0, "dropped": True})
            continue
        if total <= remaining:
            kept[section.key] = section.text
            remaining -= total
            continue
        kept[section.key] = section.text[:remaining]
        report.append(
            {
                "key": section.key,
                "title": section.title,
                "total_chars": total,
                "kept_chars": remaining,
                "dropped": False,
                "truncated": True,
            }
        )
        remaining = 0
    trimmed: list[PromptSection] = []
    for section in sections:
        section.text = kept.get(section.key, "")
        trimmed.append(section)
    return trimmed, report


def context_report_summary(report: list[dict[str, Any]]) -> str:
    """Human-readable one-line summary of budget trimming for generation results."""
    if not report:
        return ""
    parts = []
    for item in report:
        state = "未送入 AI" if item.get("dropped") else f"截断至 {item.get('kept_chars', 0):,} 字符"
        parts.append(f"{item.get('title', item.get('key', ''))}（{item.get('total_chars', 0):,} 字符）{state}")
    return "；".join(parts)


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
    # 连同附件目录一起清掉，避免 data/skills/<id>/ 残留孤儿目录。
    skill_folder = SKILLS_DIR / skill_id
    if skill_folder.is_dir():
        shutil.rmtree(skill_folder, ignore_errors=True)


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
        # 内置素材封面只存引用、不再复制原图到项目目录：
        # 列表/详情统一走 /static 共享资源（浏览器只缓存一份），展示用缩略图。
        return {"type": "asset", "file": file_name, "source_file": file_name}

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
    except (ValueError, binascii.Error) as exc:
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
        "max_parallel_workers": MAX_PARALLEL_DEFAULT,
        "batch_chunk_size": BATCH_CHUNK_DEFAULT,
        "updated_at": None,
    }


def load_settings() -> dict[str, Any]:
    override = getattr(SETTINGS_CONTEXT, "settings", None)
    if isinstance(override, dict):
        return dict(override)
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

    def _windows_target(self, account: str | None = None) -> str:
        return f"{KEYCHAIN_SERVICE}/{account or KEYCHAIN_ACCOUNT}"

    def get(self, account: str | None = None) -> str | None:
        account = account or KEYCHAIN_ACCOUNT
        if not self.available:
            return None
        if sys.platform == "win32":
            if account != KEYCHAIN_ACCOUNT:
                path = self._windows_profile_secret_path(account)
                if not path.is_file():
                    return None
                try:
                    return self._windows_dpapi_unprotect(path.read_bytes())
                except (OSError, RuntimeError, UnicodeError):
                    return None
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
                account,
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

    def save(self, value: str, account: str | None = None) -> None:
        account = account or KEYCHAIN_ACCOUNT
        if not self.available:
            raise RuntimeError("当前系统未检测到可用的系统凭据存储，暂不保存 API Key。")
        if sys.platform == "win32":
            protected = self._windows_dpapi_protect(value)
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            if account == KEYCHAIN_ACCOUNT:
                path = self._windows_secret_path
            else:
                path = self._windows_profile_secret_path(account)
            temporary = path.with_suffix(".dpapi.tmp")
            temporary.write_bytes(protected)
            temporary.replace(path)
            return
        result = subprocess.run(
            [
                "security",
                "add-generic-password",
                "-U",
                "-a",
                account,
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

    def delete(self, account: str | None = None) -> bool:
        account = account or KEYCHAIN_ACCOUNT
        if not self.available:
            return False
        if sys.platform == "win32":
            path = self._windows_secret_path if account == KEYCHAIN_ACCOUNT else self._windows_profile_secret_path(account)
            try:
                path.unlink()
                return True
            except FileNotFoundError:
                return False
        result = subprocess.run(
            ["security", "delete-generic-password", "-a", account, "-s", KEYCHAIN_SERVICE],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0

    def _windows_profile_secret_path(self, account: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", account)[:64] or "profile"
        return DATA_DIR / f".api-key-{safe}.dpapi"


KEYCHAIN = KeychainStore()


def public_settings() -> dict[str, Any]:
    settings = load_settings()
    settings["api_key_configured"] = bool(KEYCHAIN.get())
    settings["key_storage"] = KEYCHAIN.backend or "不可用"
    settings["agent_profiles"] = [agent_profile_public(item) for item in settings.get("agent_profiles", [])]
    return settings


# =========================================================================
# Agent 档案（多 Agent 并行生成）：每个档案独立的模型配置与 API Key。
# =========================================================================

PROFILE_FIELDS = {"name", "provider", "base_url", "model", "temperature", "max_tokens", "timeout_seconds"}


def agent_profile_key_account(profile_id: str) -> str:
    return f"profile:{profile_id}"


def agent_profile_public(profile: dict[str, Any]) -> dict[str, Any]:
    profile_id = str(profile.get("id", ""))
    own_key = bool(KEYCHAIN.get(agent_profile_key_account(profile_id)))
    account_key = bool(KEYCHAIN.get())
    if own_key:
        key_source = "custom"
    elif account_key:
        key_source = "fallback"
    else:
        key_source = "none"
    origin = profile.get("key_origin") if profile.get("key_origin") in {"account", "custom"} else ("custom" if own_key else "")
    return {
        "id": profile_id,
        "name": profile.get("name", ""),
        "provider": profile.get("provider", "openai-compatible"),
        "base_url": profile.get("base_url", ""),
        "model": profile.get("model", ""),
        "temperature": profile.get("temperature", 0.2),
        "max_tokens": profile.get("max_tokens"),
        "timeout_seconds": profile.get("timeout_seconds", 60),
        "key_configured": own_key,
        "account_key_configured": account_key,
        "key_source": key_source,
        "key_origin": origin,
        "last_test": profile.get("last_test") if isinstance(profile.get("last_test"), dict) else None,
    }


def record_agent_profile_test(profile_id: str, ok: bool, message: str) -> None:
    """把最近一次「测试连接」的结果写回档案，供列表页状态点展示。"""
    settings = load_settings()
    profiles = settings.get("agent_profiles") or []
    changed = False
    for item in profiles:
        if isinstance(item, dict) and item.get("id") == profile_id:
            item["last_test"] = {"ok": bool(ok), "at": now_iso(), "message": str(message)[:200]}
            changed = True
    if changed:
        settings["agent_profiles"] = profiles
        settings["updated_at"] = now_iso()
        write_json(SETTINGS_FILE, settings)


def normalize_agent_profile(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = sanitize_text(raw.get("name"))
    if not name:
        raise ValueError("Agent 档案名称不能为空。")
    profile_id = sanitize_text(raw.get("id")) or f"profile_{secrets.token_hex(3)}"
    profile = {"id": profile_id, "name": name}
    if raw.get("provider") in {"openai-compatible", "anthropic", "local"}:
        profile["provider"] = raw["provider"]
    for field in ("base_url", "model"):
        profile[field] = sanitize_text(raw.get(field))
    for field in ("temperature", "timeout_seconds"):
        raw_value = raw.get(field)
        if raw_value in (None, ""):
            profile[field] = None
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            profile[field] = None
            continue
        if field == "timeout_seconds":
            # 超时 0/负数等于不设限，按未设置处理，沿用主配置。
            profile[field] = value if value > 0 else None
        else:
            profile[field] = value if value >= 0 else None
    try:
        tokens = int(raw.get("max_tokens") or 0)
    except (TypeError, ValueError):
        tokens = 0
    profile["max_tokens"] = tokens if tokens >= 256 else None
    return profile


def save_agent_profile(payload: dict[str, Any]) -> dict[str, Any]:
    profile = normalize_agent_profile(payload)
    assert profile is not None
    profile_id = profile["id"]
    settings = load_settings()
    profiles = [item for item in settings.get("agent_profiles", []) if isinstance(item, dict)]
    previous = next((item for item in profiles if item.get("id") == profile_id), None)

    # Key 处理：填了就用这个子 Agent 自己的 Key；没填且它还没有 Key 时，
    # 默认把本账号主 Key 复制过来，让子 Agent 开箱可用（之后可单独替换）。
    api_key = str(payload.get("api_key") or "").strip()
    own_key = KEYCHAIN.get(agent_profile_key_account(profile_id))
    if api_key:
        KEYCHAIN.save(api_key, agent_profile_key_account(profile_id))
        profile["key_origin"] = "custom"
    elif own_key:
        profile["key_origin"] = (previous or {}).get("key_origin") or "custom"
    else:
        master_key = KEYCHAIN.get()
        if master_key:
            KEYCHAIN.save(master_key, agent_profile_key_account(profile_id))
            profile["key_origin"] = "account"
        else:
            profile["key_origin"] = "custom"

    replaced = False
    for index, item in enumerate(profiles):
        if item.get("id") == profile_id:
            profiles[index] = profile
            replaced = True
            break
    if not replaced:
        if len(profiles) >= 8:
            raise ValueError("Agent 档案最多 8 个。")
        profiles.append(profile)
    settings["agent_profiles"] = profiles
    settings["updated_at"] = now_iso()
    write_json(SETTINGS_FILE, settings)
    return agent_profile_public(profile)


def copy_account_key_to_profile(profile_id: str) -> dict[str, Any]:
    """把「AI 服务」里的本账号主 Key 复制成某个子 Agent 的独立 Key。"""
    settings = load_settings()
    profile = next((item for item in settings.get("agent_profiles", []) if isinstance(item, dict) and item.get("id") == profile_id), None)
    if profile is None:
        raise ValueError("Agent 档案不存在。")
    master_key = KEYCHAIN.get()
    if not master_key:
        raise ValueError("设置页还没有保存主 API Key，请先在「AI 服务」里保存。")
    KEYCHAIN.save(master_key, agent_profile_key_account(profile_id))
    profile["key_origin"] = "account"
    settings["updated_at"] = now_iso()
    write_json(SETTINGS_FILE, settings)
    return agent_profile_public(profile)


def delete_agent_profile(profile_id: str) -> dict[str, Any]:
    settings = load_settings()
    profiles = [item for item in settings.get("agent_profiles", []) if isinstance(item, dict) and item.get("id") != profile_id]
    settings["agent_profiles"] = profiles
    settings["updated_at"] = now_iso()
    write_json(SETTINGS_FILE, settings)
    KEYCHAIN.delete(agent_profile_key_account(profile_id))
    return {"ok": True, "id": profile_id}


def save_agent_profile_key(profile_id: str, api_key: str) -> dict[str, Any]:
    settings = load_settings()
    profile = next((item for item in settings.get("agent_profiles", []) if isinstance(item, dict) and item.get("id") == profile_id), None)
    if profile is None:
        raise ValueError("Agent 档案不存在。")
    if not str(api_key or "").strip():
        raise ValueError("API Key 不能为空。")
    KEYCHAIN.save(str(api_key).strip(), agent_profile_key_account(profile_id))
    return {"ok": True, "id": profile_id, "key_configured": True}


def resolve_agent_profile_settings(profile_id: str) -> dict[str, Any] | None:
    """把档案字段合并进主配置；档案没有自己的 Key 时回退主 Key。"""
    settings = load_settings()
    profile = next((item for item in settings.get("agent_profiles", []) if isinstance(item, dict) and item.get("id") == profile_id), None)
    if profile is None:
        return None
    merged = dict(settings)
    for field in PROFILE_FIELDS:
        if profile.get(field) not in (None, ""):
            merged[field] = profile[field]
    profile_key = KEYCHAIN.get(agent_profile_key_account(profile_id))
    merged["_api_key"] = profile_key or KEYCHAIN.get()
    return merged


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


def decode_text_bytes(raw: bytes) -> str | None:
    """把字节按常见编码解成文本；明显是二进制则返回 None。"""
    if not raw:
        return None
    if b"\x00" in raw[:8192]:
        for encoding in ("utf-16", "utf-16-le", "utf-16-be"):
            try:
                text = raw.decode(encoding)
            except (UnicodeDecodeError, UnicodeError):
                continue
            printable = sum(1 for ch in text if ch.isprintable() or ch in "\n\r\t")
            if text and printable >= len(text) * 0.9:
                return text
        return None
    for encoding in ("utf-8", "gb18030", "utf-16"):
        try:
            text = raw.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
        printable = sum(1 for ch in text if ch.isprintable() or ch in "\n\r\t")
        if text and printable >= len(text) * 0.9:
            return text
    return None


def looks_like_text(raw: bytes) -> bool:
    """只看文件头判断是否文本（扫描目录时用，避免逐个整文件解码）。"""
    sample = raw[:8192]
    if not sample:
        return False
    for encoding in ("utf-8", "gb18030"):
        try:
            text = sample.decode(encoding, errors="replace")
        except LookupError:
            continue
        if not text:
            continue
        bad = sum(1 for ch in text if ch == "\ufffd" or (not ch.isprintable() and ch not in "\n\r\t"))
        if bad <= len(text) * 0.1:
            return True
    return False


def text_from_zip(raw: bytes) -> str:
    """从 zip 容器里抽取文本：pptx/odt/odp/ods/epub/xmind 等本质都是 zip + XML。"""
    chunks: list[str] = []
    try:
        with ZipFile(io.BytesIO(raw)) as archive:
            names = [
                name
                for name in archive.namelist()
                if name.lower().endswith((".xml", ".html", ".htm", ".txt", ".md", ".json", ".csv"))
                and "/theme/" not in name.lower()
                and not name.lower().endswith(".rels")
            ]
            for name in names[:300]:
                try:
                    data = archive.read(name)
                except (KeyError, OSError, RuntimeError):
                    continue
                if not data or len(data) > 8 * 1024 * 1024:
                    continue
                text = decode_text_bytes(data)
                if not text:
                    continue
                if name.lower().endswith((".html", ".htm", ".xml")):
                    parser = PlainTextHTMLParser()
                    parser.feed(text)
                    text = "".join(parser.parts) or re.sub(r"<[^>]+>", " ", text)
                if text.strip():
                    chunks.append(text)
    except (BadZipFile, OSError):
        return ""
    return "\n\n".join(chunks)


def text_from_rtf(raw: bytes) -> str:
    source = raw.decode("latin-1", errors="replace")
    source = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), source)
    source = re.sub(r"\\u(-?\d+)\??", lambda m: chr(int(m.group(1)) % 65536), source)
    source = re.sub(r"\\par[d]?\b", "\n", source)
    source = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", source)
    source = source.replace("{", "").replace("}", "")
    return source.replace("\\", "")


def system_text_extract(path: Path) -> tuple[str, str]:
    """系统自带工具兜底（macOS: textutil 转文本 / Spotlight 已索引正文）。"""
    commands: list[list[str]] = []
    textutil = shutil.which("textutil")
    if textutil:
        commands.append([textutil, "-convert", "txt", "-stdout", str(path)])
    mdls = shutil.which("mdls")
    if mdls:
        commands.append([mdls, "-raw", "-name", "kMDItemTextContent", str(path)])
    for command in commands:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=45, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode != 0:
            continue
        output = result.stdout or ""
        if output.strip() in {"", "(null)", "null"}:
            continue
        return output, Path(command[0]).name
    return "", ""


def has_system_text_tool(extension: str) -> bool:
    """本机是否有能读取该扩展名的系统工具（用于目录扫描时预判）。"""
    if extension in {".doc", ".docx", ".rtf", ".rtfd", ".html", ".htm", ".odt", ".wordml", ".webarchive"}:
        return bool(shutil.which("textutil"))
    if extension in {".pdf", ".xls", ".chm", ".pptx", ".ppt", ".pages", ".numbers", ".key", ".sketch", ".xmind"}:
        return bool(shutil.which("mdls"))
    return bool(shutil.which("textutil") or shutil.which("mdls"))


def zip_has_text_entries(path: Path) -> bool:
    """压缩包里是否有可以直接读的文本/XML 条目（决定 .zip 能不能当材料）。"""
    try:
        with ZipFile(path) as archive:
            for name in archive.namelist()[:300]:
                if name.lower().endswith((".xml", ".html", ".htm", ".txt", ".md", ".json", ".csv", ".yaml", ".yml")):
                    return True
    except (BadZipFile, OSError, RuntimeError):
        return False
    return False


def material_readability(path: Path, size: int) -> tuple[bool, str]:
    """判断这份文件能否读出文字（供目录扫描打标）。"""
    extension = path.suffix.lower()
    if size <= 0:
        return False, "空文件"
    if size > MAX_MATERIAL_BYTES:
        return False, f"超过 {MAX_MATERIAL_BYTES // (1024 * 1024)} MB"
    if extension in NO_TEXT_EXTENSIONS:
        return False, NO_TEXT_EXTENSIONS[extension]
    if extension in MATERIAL_TEXT_EXTENSIONS or extension in ZIP_TEXT_EXTENSIONS:
        return True, ""
    if extension in {".doc", ".docx", ".pdf", ".chm", ".xlsx", ".xls", ".rtf", ".rtfd"}:
        return True, ""
    try:
        with path.open("rb") as handle:
            head = handle.read(8192)
    except OSError:
        return False, "无法读取"
    if looks_like_text(head):
        return True, "按文本读取"
    if head[:2] == b"PK":
        if zip_has_text_entries(path):
            return True, "按压缩包内文档读取"
        return False, "压缩包里没有可读的文本文件"
    if has_system_text_tool(extension):
        return True, "由系统工具尝试读取"
    return False, "本机缺少可读取该格式的工具"


def extract_material_text(path: Path) -> tuple[str, str, str]:
    """Return extracted text, status, and a user-facing extraction message."""
    extension = path.suffix.lower()
    try:
        if extension in MATERIAL_TEXT_EXTENSIONS:
            raw_bytes = path.read_bytes()
            raw = decode_text_bytes(raw_bytes) or raw_bytes.decode("utf-8", errors="replace")
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
                output, tool = system_text_extract(path)
                if output.strip():
                    fallback_text, fallback_truncated = compact_extracted_text(output)
                    if fallback_text:
                        fallback_message = f"已用系统工具 {tool} 读取旧版 Excel 文本。"
                        if fallback_truncated:
                            fallback_message += f"（超过 {MAX_MATERIAL_TEXT_CHARS:,} 字符的部分未送入 AI）"
                        return fallback_text, "success", fallback_message
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
                output, tool = system_text_extract(path)
                if output.strip():
                    fallback_text, fallback_truncated = compact_extracted_text(output)
                    if fallback_text:
                        fallback_message = f"未检测到 pdftotext，已用系统工具 {tool} 读取 PDF 文本。"
                        if fallback_truncated:
                            fallback_message += f"（超过 {MAX_MATERIAL_TEXT_CHARS:,} 字符的部分未送入 AI）"
                        return fallback_text, "success", fallback_message
                return "", "unsupported", "未检测到 pdftotext，且系统工具读不出该 PDF 文本，已保留原文件。"
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

        # ---------- 通用兜底：不认识的格式也尽量读出来 ----------
        raw_bytes = path.read_bytes()
        if raw_bytes[:5] == b"{\\rtf" or extension in {".rtf", ".rtfd"}:
            text, truncated = compact_extracted_text(text_from_rtf(raw_bytes))
            if text:
                message = "RTF 文本已提取。"
                if truncated:
                    message += f"（超过 {MAX_MATERIAL_TEXT_CHARS:,} 字符的部分未送入 AI）"
                return text, "success", message

        if raw_bytes[:2] == b"PK":
            text, truncated = compact_extracted_text(text_from_zip(raw_bytes))
            if text:
                message = f"{extension or '压缩文档'} 内部文本已提取。"
                if truncated:
                    message += f"（超过 {MAX_MATERIAL_TEXT_CHARS:,} 字符的部分未送入 AI）"
                return text, "success", message

        decoded = decode_text_bytes(raw_bytes)
        if decoded:
            text, truncated = compact_extracted_text(decoded)
            if text:
                message = "按文本读取成功。"
                if truncated:
                    message += f"（超过 {MAX_MATERIAL_TEXT_CHARS:,} 字符的部分未送入 AI）"
                return text, "success", message

        output, tool = system_text_extract(path)
        if output.strip():
            text, truncated = compact_extracted_text(output)
            if text:
                message = f"已用系统工具 {tool} 读取文本。"
                if truncated:
                    message += f"（超过 {MAX_MATERIAL_TEXT_CHARS:,} 字符的部分未送入 AI）"
                return text, "success", message

        reason = NO_TEXT_EXTENSIONS.get(extension)
        if reason:
            return "", "unsupported", f"{reason}，已保留原文件。"
        return "", "unsupported", f"本机没有可读取 {extension or '该格式'} 文本的工具，已保留原文件。"
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
        "origin": str(material.get("origin", "")),
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


def persist_project_material(
    project_id: str,
    name: str,
    mime_type: str,
    raw: bytes,
    origin: str = "",
) -> dict[str, Any]:
    """把一份材料字节流落盘并提取文本（上传与目录导入共用）。"""
    project = read_json(project_dir(project_id) / "project.json", None)
    if not isinstance(project, dict):
        raise ValueError("项目不存在。")
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
    if origin:
        material["origin"] = origin
    write_json(directory / "material.json", material)
    project["updated_at"] = timestamp
    write_json(project_dir(project_id) / "project.json", project)
    return material_summary(project_id, material)


def save_project_material(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(read_json(project_dir(project_id) / "project.json", None), dict):
        raise ValueError("项目不存在。")
    name, mime_type, raw = decode_material(payload)
    return persist_project_material(project_id, name, mime_type, raw, str(payload.get("origin", "")) or "")


def resolve_local_directory(raw: str) -> Path:
    """把用户输入的目录字符串解析成可访问的绝对目录。"""
    spec = str(raw or "").strip().strip('"').strip("'").strip()
    if not spec:
        raise ValueError("请先填写目录路径，或点「浏览」选择文件夹。")
    path = Path(os.path.expanduser(spec))
    if not path.is_absolute():
        raise ValueError("请填写完整路径（以 / 或盘符开头），例如 ~/Documents/需求文档。")
    try:
        path = path.resolve()
    except OSError as exc:
        raise ValueError(f"目录无法访问：{exc}") from exc
    if not path.exists():
        raise ValueError("目录不存在，请检查路径是否正确。")
    if not path.is_dir():
        raise ValueError("该路径不是目录，请选择文件夹。")
    return path


def scan_directory_files(raw_path: str, recursive: bool = True) -> dict[str, Any]:
    """列出目录下的文件（不读取内容），并标注是否可作为材料导入。"""
    directory = resolve_local_directory(raw_path)
    files: list[dict[str, Any]] = []
    truncated = False
    walker = directory.rglob("*") if recursive else directory.glob("*")
    try:
        for item in walker:
            if len(files) >= DIR_IMPORT_MAX_FILES:
                truncated = True
                break
            try:
                relative_parts = item.relative_to(directory).parts
            except ValueError:
                continue
            if any(part.startswith(".") or part in DIR_IMPORT_SKIP_DIRS for part in relative_parts[:-1]):
                continue
            name = item.name
            if name.startswith(".") or name.startswith("~$"):
                continue
            try:
                if not item.is_file():
                    continue
                size = item.stat().st_size
            except OSError:
                continue
            extension = item.suffix.lower()
            readable, note = material_readability(item, size)
            files.append(
                {
                    "path": str(item),
                    "name": name,
                    "relative": "/".join(relative_parts),
                    "extension": extension,
                    "size": size,
                    "supported": readable,
                    "reason": "" if readable else note,
                    "note": note if readable else "",
                }
            )
    except PermissionError as exc:
        raise ValueError(f"没有权限读取该目录：{exc.filename or directory}") from exc
    files.sort(key=lambda entry: str(entry["relative"]).lower())
    supported = [item for item in files if item["supported"]]
    total_bytes = sum(int(item["size"]) for item in supported)
    return {
        "directory": str(directory),
        "name": directory.name or str(directory),
        "recursive": recursive,
        "files": files,
        "supported_count": len(supported),
        "supported_bytes": total_bytes,
        "truncated": truncated,
        "max_files": DIR_IMPORT_MAX_FILES,
    }


# ---------------------------------------------------------------- 项目工作区
# 工作区 = 用户指定的本地目录。项目不再把目录里的文件复制成材料，而是在生成框架 /
# Topic 时由后端直接读取目录内容（按主题相关性挑文件），并附上完整文件清单。
WORKSPACE_MAX_FILES = 1200
WORKSPACE_TOPIC_FILES = 6
WORKSPACE_FRAMEWORK_FILES = 12
WORKSPACE_INDEX_TTL_SECONDS = 30
WORKSPACE_CACHE_VERSION = 1
WORKSPACE_EXTENSION_PRIORITY = {".md": 4, ".docx": 4, ".pdf": 3, ".txt": 3, ".xlsx": 2, ".pptx": 2, ".pptm": 2}
_WORKSPACE_INDEX_CACHE: dict[str, dict[str, Any]] = {}
_WORKSPACE_LOCK = threading.Lock()


def format_bytes_cn(size: int) -> str:
    value = float(size or 0)
    for unit in ("B", "KB", "MB"):
        if value < 1024:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def workspace_cache_dir(project_id: str) -> Path:
    return project_dir(project_id) / "workspace-cache"


def project_workspace(project: dict[str, Any]) -> dict[str, Any] | None:
    raw = project.get("workspace")
    if not isinstance(raw, dict):
        return None
    path = str(raw.get("path", "")).strip()
    if not path:
        return None
    return {
        "path": path,
        "name": str(raw.get("name", "")).strip() or Path(path).name or path,
        "recursive": raw.get("recursive", True) is not False,
        "registered_at": str(raw.get("registered_at", "") or ""),
        "updated_at": str(raw.get("updated_at", "") or ""),
    }


def resolve_workspace_directory(project: dict[str, Any]) -> tuple[Path | None, str]:
    """校验工作区目录当前是否可访问，返回 (目录, 问题说明)。"""
    workspace = project_workspace(project)
    if not workspace:
        return None, "尚未设置工作区目录。"
    path = Path(os.path.expanduser(workspace["path"]))
    if not path.is_absolute():
        return None, "工作区路径必须是完整路径。"
    try:
        path = path.resolve()
    except OSError:
        return None, "工作区路径无法解析，请重新设置。"
    if not path.exists():
        return None, "工作区目录不存在（可能被移动或删除），请重新设置。"
    if not path.is_dir():
        return None, "工作区路径不是目录，请重新设置。"
    return path, ""


def _walk_workspace(root: Path, recursive: bool) -> tuple[list[dict[str, Any]], bool]:
    files: list[dict[str, Any]] = []
    truncated = False
    walker = root.rglob("*") if recursive else root.glob("*")
    try:
        for item in walker:
            if len(files) >= WORKSPACE_MAX_FILES:
                truncated = True
                break
            try:
                relative_parts = item.relative_to(root).parts
            except ValueError:
                continue
            if any(part.startswith(".") or part in DIR_IMPORT_SKIP_DIRS for part in relative_parts[:-1]):
                continue
            name = item.name
            if name.startswith(".") or name.startswith("~$"):
                continue
            try:
                if not item.is_file():
                    continue
                stat = item.stat()
            except OSError:
                continue
            readable, note = material_readability(item, stat.st_size)
            files.append(
                {
                    "path": str(item),
                    "relative": "/".join(relative_parts),
                    "name": name,
                    "extension": item.suffix.lower(),
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                    "readable": readable,
                    "reason": "" if readable else note,
                }
            )
    except PermissionError as exc:
        raise ValueError(f"没有权限读取工作区目录：{exc.filename or root}") from exc
    files.sort(key=lambda entry: str(entry["relative"]).lower())
    return files, truncated


def workspace_index(project_id: str, project: dict[str, Any], refresh: bool = False) -> dict[str, Any]:
    """实时遍历工作区（只读元数据），30 秒内复用上一次结果，避免批量生成时反复扫描。"""
    workspace = project_workspace(project)
    root, problem = resolve_workspace_directory(project)
    if root is None:
        return {
            "workspace": workspace,
            "exists": False,
            "problem": problem,
            "directory": str((workspace or {}).get("path", "")),
            "files": [],
            "truncated": False,
            "scanned_at": now_iso(),
        }
    key = f"{project_id}|{root}|{bool((workspace or {}).get('recursive', True))}"
    now_ts = time.time()
    with _WORKSPACE_LOCK:
        cached = _WORKSPACE_INDEX_CACHE.get(key)
        if cached and not refresh and now_ts - float(cached.get("scanned_ts", 0)) < WORKSPACE_INDEX_TTL_SECONDS:
            return cached
    files, truncated = _walk_workspace(root, bool((workspace or {}).get("recursive", True)))
    result = {
        "workspace": workspace,
        "exists": True,
        "problem": "",
        "directory": str(root),
        "name": (workspace or {}).get("name") or root.name or str(root),
        "files": files,
        "truncated": truncated,
        "scanned_at": now_iso(),
        "scanned_ts": now_ts,
    }
    with _WORKSPACE_LOCK:
        if len(_WORKSPACE_INDEX_CACHE) > 24:
            _WORKSPACE_INDEX_CACHE.clear()
        _WORKSPACE_INDEX_CACHE[key] = result
    return result


def workspace_state(project_id: str, project: dict[str, Any] | None = None, refresh: bool = False) -> dict[str, Any]:
    """给前端的完整工作区状态：目录信息 + 文件清单（可读性标注）。"""
    project = project if isinstance(project, dict) else read_json(project_dir(project_id) / "project.json", None)
    if not isinstance(project, dict):
        raise ValueError("项目不存在。")
    try:
        index = workspace_index(project_id, project, refresh=refresh)
    except ValueError as exc:
        workspace = project_workspace(project) or {}
        return {
            "workspace": workspace,
            "configured": bool(workspace),
            "exists": False,
            "problem": str(exc),
            "directory": str(workspace.get("path", "")),
            "name": workspace.get("name", ""),
            "recursive": bool(workspace.get("recursive", True)),
            "files": [],
            "file_count": 0,
            "readable_count": 0,
            "readable_bytes": 0,
            "truncated": False,
            "max_files": WORKSPACE_MAX_FILES,
            "scanned_at": now_iso(),
            "limits": {"topic_files": WORKSPACE_TOPIC_FILES, "framework_files": WORKSPACE_FRAMEWORK_FILES},
        }
    files = index.get("files") or []
    readable = [item for item in files if item.get("readable")]
    workspace = index.get("workspace") or {}
    return {
        "workspace": workspace,
        "configured": bool(workspace),
        "exists": bool(index.get("exists")),
        "problem": index.get("problem", ""),
        "directory": index.get("directory", ""),
        "name": index.get("name", ""),
        "recursive": bool(workspace.get("recursive", True)),
        "files": [
            {
                "relative": item["relative"],
                "name": item["name"],
                "extension": item["extension"],
                "size": item["size"],
                "readable": bool(item["readable"]),
                "reason": item.get("reason", ""),
            }
            for item in files[:400]
        ],
        "file_count": len(files),
        "readable_count": len(readable),
        "readable_bytes": sum(int(item.get("size", 0) or 0) for item in readable),
        "truncated": bool(index.get("truncated")),
        "max_files": WORKSPACE_MAX_FILES,
        "scanned_at": index.get("scanned_at", ""),
        "limits": {"topic_files": WORKSPACE_TOPIC_FILES, "framework_files": WORKSPACE_FRAMEWORK_FILES},
    }


def workspace_has_readable(project_id: str, project: dict[str, Any]) -> bool:
    try:
        index = workspace_index(project_id, project)
    except ValueError:
        return False
    if not index.get("exists"):
        return False
    return any(item.get("readable") for item in index.get("files") or [])


def workspace_text(project_id: str, path: Path, relative: str) -> tuple[str, str, str]:
    """读工作区里某份文件的文本，(mtime, size) 未变时复用磁盘缓存。"""
    try:
        stat = path.stat()
    except OSError as exc:
        return "", "failed", f"无法读取：{exc}"
    cache_file = workspace_cache_dir(project_id) / f"{hashlib.sha1(relative.encode('utf-8')).hexdigest()[:16]}.json"
    cached = read_json(cache_file, None)
    if (
        isinstance(cached, dict)
        and cached.get("version") == WORKSPACE_CACHE_VERSION
        and cached.get("mtime") == stat.st_mtime
        and cached.get("size") == stat.st_size
    ):
        return str(cached.get("text", "")), str(cached.get("status", "success")), str(cached.get("message", ""))
    text, status, message = extract_material_text(path)
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        write_json(
            cache_file,
            {
                "version": WORKSPACE_CACHE_VERSION,
                "relative": relative,
                "mtime": stat.st_mtime,
                "size": stat.st_size,
                "text": text,
                "status": status,
                "message": message,
            },
        )
    except OSError:
        pass
    return text, status, message


def workspace_query_terms(*sources: Any) -> list[str]:
    """从项目信息 / Topic 描述里抽关键词，用于挑选工作区里最相关的文件。"""
    terms: list[str] = []
    for source in sources:
        for token in re.findall(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,6}", str(source or "")):
            token = token.strip()
            if len(token) >= 2 and token not in terms:
                terms.append(token)
    return terms[:60]


def workspace_prompt_context(
    project: dict[str, Any],
    terms: list[str],
    *,
    limit: int,
    per_file_chars: int,
    max_chars: int,
) -> tuple[str, list[dict[str, Any]]]:
    """把工作区做成提示词上下文：完整文件清单 + 相关文件正文（实时读取）。

    返回 (上下文文本, 实际读取的文件报告)。文件清单始终给出，让模型知道工作区范围；
    正文按关键词命中数挑选，避免把整个目录塞进提示词。
    """
    project_id = str(project.get("id", ""))
    index = workspace_index(project_id, project)
    if not index.get("exists"):
        return "", []
    files = index.get("files") or []
    readable = [item for item in files if item.get("readable")]
    inventory_lines = [f"- {item['relative']}（{format_bytes_cn(item['size'])}）" for item in files[:300]]
    if len(files) > 300:
        inventory_lines.append(f"- …（其余 {len(files) - 300} 个文件未列出）")
    header = [
        f"### 工作区目录：{index.get('name') or index.get('directory', '')}",
        f"- 路径：{index.get('directory', '')}",
        f"- 文件：{len(files)} 个，其中 {len(readable)} 个可读取文本"
        + ("（文件过多，仅索引前 %d 个）" % WORKSPACE_MAX_FILES if index.get("truncated") else ""),
        "",
        "#### 文件清单",
        *(inventory_lines or ["- （空目录）"]),
    ]
    if not readable:
        header.append("")
        header.append("（该目录下没有可读取文字的文档；请确认文件格式，或换一个目录。）")
        return "\n".join(header)[:max_chars], []

    lowered_terms = [term.lower() for term in terms if len(term) >= 2]
    scored: list[tuple[int, int, float, dict[str, Any]]] = []
    for item in readable:
        haystack = item["relative"].lower()
        name = item["name"].lower()
        score = 0
        for term in lowered_terms:
            if term in name:
                score += 8
            elif term in haystack:
                score += 4
        scored.append((score, WORKSPACE_EXTENSION_PRIORITY.get(item["extension"], 0), item["mtime"], item))
    scored.sort(key=lambda entry: (-entry[0], -entry[1], -entry[2], entry[3]["relative"]))
    candidates = scored[: max(limit * 3, limit + 6)]

    loaded: list[tuple[int, dict[str, Any], str, str]] = []
    for score, bonus, _, item in candidates:
        text, status, message = workspace_text(project_id, Path(item["path"]), item["relative"])
        if status != "success" or not text.strip():
            continue
        hits = 0
        lowered_text = text.lower()
        for term in lowered_terms[:40]:
            if term in lowered_text:
                hits += min(lowered_text.count(term), 5)
        loaded.append((score + bonus + min(hits, 60), item, text, message))
    loaded.sort(key=lambda entry: -entry[0])
    selected = loaded[:limit]

    blocks: list[str] = []
    report: list[dict[str, Any]] = []
    used = len("\n".join(header))
    for score, item, text, message in selected:
        body = text[:per_file_chars]
        block = f"#### 文件：{item['relative']}（{len(text):,} 字符{'，已截取前 %d 字符' % per_file_chars if len(text) > per_file_chars else ''}）\n{body}"
        if used + len(block) > max_chars:
            break
        blocks.append(block)
        used += len(block)
        report.append(
            {
                "relative": item["relative"],
                "name": item["name"],
                "size": item["size"],
                "chars": len(text),
                "used_chars": len(body),
                "message": message,
                "score": score,
            }
        )
    if blocks:
        header.extend(["", "#### 已读取的文件内容", *blocks])
    else:
        header.extend(["", "（本次没有文件被读入提示词，请参考上面的文件清单。）"])
    return "\n".join(header)[:max_chars], report


def save_project_workspace(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """把本地目录登记为项目工作区（不复制任何文件）。"""
    path = project_dir(project_id) / "project.json"
    project = read_json(path, None)
    if not isinstance(project, dict):
        raise ValueError("项目不存在。")
    root = resolve_local_directory(str(payload.get("path", "")))
    recursive = payload.get("recursive", True) is not False
    timestamp = now_iso()
    previous = project_workspace(project) or {}
    project["workspace"] = {
        "path": str(root),
        "name": root.name or str(root),
        "recursive": recursive,
        "registered_at": previous.get("registered_at") or timestamp,
        "updated_at": timestamp,
    }
    project["updated_at"] = timestamp
    write_json(path, project)
    with _WORKSPACE_LOCK:
        _WORKSPACE_INDEX_CACHE.clear()
    return workspace_state(project_id, project, refresh=True)


def clear_project_workspace(project_id: str) -> dict[str, Any]:
    path = project_dir(project_id) / "project.json"
    project = read_json(path, None)
    if not isinstance(project, dict):
        raise ValueError("项目不存在。")
    project.pop("workspace", None)
    project["updated_at"] = now_iso()
    write_json(path, project)
    with _WORKSPACE_LOCK:
        _WORKSPACE_INDEX_CACHE.clear()
    shutil.rmtree(workspace_cache_dir(project_id), ignore_errors=True)
    return workspace_state(project_id, project)


def preview_workspace_file(project_id: str, relative: str) -> dict[str, Any]:
    """预览工作区里某个文件的读取结果，让用户确认 Agent 到底读到了什么。"""
    project = read_json(project_dir(project_id) / "project.json", None)
    if not isinstance(project, dict):
        raise ValueError("项目不存在。")
    root, problem = resolve_workspace_directory(project)
    if root is None:
        raise ValueError(problem)
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("文件不在工作区内。") from exc
    if not target.is_file():
        raise ValueError("文件不存在或已被移动。")
    text, status, message = workspace_text(project_id, target, relative)
    return {
        "relative": relative,
        "name": target.name,
        "size": target.stat().st_size,
        "status": status,
        "message": message,
        "text": text[:8000],
        "chars": len(text),
        "truncated": len(text) > 8000,
    }


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
    confirm_count = len(CONFIRM_PATTERN.findall(xml_text))
    if guid_count:
        errors.append(f"发现禁止的 GUID Token：{guid_count} 个")
    if placeholder_count:
        warnings.append(f"发现待人工替换占位符：{placeholder_count} 个")
    if confirm_count:
        warnings.append(f"发现待确认事实占位符：{confirm_count} 个（TODO_CONFIRM，需人工核实后改写）")
    if errors:
        status = "校验失败"
    elif placeholder_count or confirm_count:
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
        "confirm_count": confirm_count,
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


def enforce_xml_root_id(xml_text: str, topic_id: str) -> str:
    """把 AI 生成 XML 的根元素 id 强制改回本地 Topic id，避免优化/重写后 id 漂移、下游关联断裂。"""
    safe_id = re.sub(r"[^A-Za-z0-9_\-:.]", "_", str(topic_id))
    return re.sub(
        r'(<(?:task|concept|reference|topic)\b[^>]*?\bid=")[^"]*(")',
        lambda match: f"{match.group(1)}{safe_id}{match.group(2)}",
        str(xml_text),
        count=1,
    )


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
    xml_text = str(ai_result["xml"]) if ai_result else build_topic_xml(payload, topic_id)
    if ai_result:
        xml_text = enforce_xml_root_id(xml_text, topic_id)
    validation = validate_topic_xml(xml_text)
    lint_report = ai_result.get("lint") if ai_result else lint_topic_xml(xml_text, str(payload.get("topic_type", "concept")))
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
        "generation_mode": ai_result.get("generation_mode") if ai_result else None,
        "unconfirmed": (ai_result or {}).get("unconfirmed", []),
        "material_slices": (ai_result or {}).get("material_slices", []),
        "context_summary": (ai_result or {}).get("context_summary"),
        "xml": xml_text,
        "validation": validation,
        "lint": lint_report,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    with generation_commit():
        directory.mkdir(parents=True, exist_ok=True)
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
    xml_text = enforce_xml_root_id(str(ai_result["xml"]), topic_id)
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
            "generation_mode": ai_result.get("generation_mode"),
            "unconfirmed": (ai_result or {}).get("unconfirmed", []),
            "material_slices": (ai_result or {}).get("material_slices", []),
            "context_summary": (ai_result or {}).get("context_summary"),
            "xml": xml_text,
            "validation": validate_topic_xml(xml_text),
            "lint": ai_result.get("lint") or lint_topic_xml(xml_text, str(merged.get("topic_type", topic.get("topic_type", "concept")))),
            "updated_at": timestamp,
        }
    )
    with generation_commit():
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


def cover_thumbnail(directory: Path, source: Path) -> Path | None:
    """Best-effort 生成 400px 封面缩略图（依赖 macOS 自带 sips；其他平台返回 None，前端回退原图）。"""
    sips = shutil.which("sips")
    if not sips or not source.exists() or not source.is_file():
        return None
    is_png = source.suffix.lower() == ".png"
    thumb = directory / ("cover_thumb.png" if is_png else "cover_thumb.jpg")
    try:
        if thumb.exists() and thumb.stat().st_size > 0 and thumb.stat().st_mtime >= source.stat().st_mtime:
            return thumb
        args = [sips, "-Z", "400"]
        args += ["-s", "format", "png"] if is_png else ["-s", "format", "jpeg", "-s", "formatOptions", "72"]
        args += [str(source), "--out", str(thumb)]
        result = subprocess.run(args, capture_output=True, timeout=30)
        if result.returncode == 0 and thumb.exists() and thumb.stat().st_size > 0:
            return thumb
    except Exception:
        return None
    return None


def project_summary(project: dict[str, Any]) -> dict[str, Any]:
    project_id = project["id"]
    directory = project_dir(project_id)
    materials = directory / "materials"
    outputs = directory / "outputs"
    topics = directory / "topics"
    cover = project.get("cover") if isinstance(project.get("cover"), dict) else default_cover()
    cover_url = None
    cover_thumb_url = None
    if cover:
        stored_cover = directory / Path(str(cover.get("file", ""))).name
        source_file = Path(str(cover.get("source_file", ""))).name
        asset_ok = cover.get("type") == "asset" and source_file in {asset["file"] for asset in list_editorial_assets()}
        if asset_ok:
            # 直接引用共享素材；顺带清掉旧版本复制进项目目录的重复大文件
            if stored_cover.exists() and stored_cover.name != source_file:
                try:
                    stored_cover.unlink()
                except OSError:
                    pass
            cover_url = f"/static/assets/editorial/{quote(source_file)}"
            cover_thumb_url = f"/api/projects/{quote(project_id)}/cover?thumb=1"
        elif stored_cover.exists() and stored_cover.is_file():
            cover_url = f"/api/projects/{quote(project_id)}/cover"
            cover_thumb_url = f"/api/projects/{quote(project_id)}/cover?thumb=1"
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
        "cover_thumb_url": cover_thumb_url,
        "topic_count": len([p for p in topics.iterdir() if p.is_dir() and (p / "topic.json").exists()])
        if topics.exists()
        else int(project.get("topic_count", 0)),
        "material_count": len(list_project_material_records(project_id)) if materials.exists() else 0,
        "workspace": project_workspace(project),
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
    # 项目封面循环色：按现有项目数对色板长度取模，新项目依次轮换
    existing_count = (
        len([p for p in PROJECTS_DIR.iterdir() if p.is_dir() and (p / "project.json").exists()])
        if PROJECTS_DIR.exists()
        else 0
    )
    color_index = existing_count % len(PROJECT_COLOR_PALETTE)
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
        "color_index": color_index,
        "cover": cover,
    }
    write_json(directory / "project.json", project)
    return project_summary(project)


def delete_project(project_id: str) -> None:
    directory = project_dir(project_id)
    if not (directory / "project.json").exists():
        raise ValueError("项目不存在。")
    shutil.rmtree(directory)
    # 生成日志在独立目录（含 usage/token 记账），不跟着项目目录走，需要单独清。
    shutil.rmtree(GENERATION_LOG_DIR / project_id, ignore_errors=True)


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


@synchronized
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


@synchronized
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
    project: dict[str, Any], payload: dict[str, Any], materials: list[dict[str, Any]], settings: dict[str, Any] | None = None
) -> tuple[str, str, list[str], list[dict[str, Any]]]:
    """Build the framework prompt under a global context budget.

    Section priority: 素材 > Skill > 基线 > 语料。Returns
    (system, user, skill_names, context_report).
    """
    records = selected_skill_records(payload.get("skills") or project.get("skills", []))
    skill_names = [str(item["name"]) for item in records]
    sections: list[PromptSection] = []
    for skill in records:
        block = f"## Skill：{skill['name']}\n{skill.get('content', '')}"
        attachments = text_attachment_context(skill)
        if attachments:
            block += f"\n\n## Skill 附件上下文\n{attachments}"
        sections.append(PromptSection(f"skill:{skill.get('id', skill['name'])}", f"Skill：{skill['name']}", 2, block))
    empty_material_notes: list[str] = []
    for material in materials:
        text = str(material.get("extracted_text", "")).strip()
        message = str(material.get("extract_message", ""))
        if text:
            sections.append(
                PromptSection(
                    f"material:{material.get('id', '')}",
                    f"材料：{material.get('name', '未命名')}",
                    1,
                    text,
                )
            )
        else:
            empty_material_notes.append(f"### 材料：{material.get('name', '未命名')}\n- 暂无可读取文本。{message}")
    # 项目工作区：不导入、不复制，生成时直接读目录里的文件（清单 + 相关正文）。
    workspace_terms = workspace_query_terms(
        project.get("name"), project.get("product"), project.get("version"), payload.get("analysis_note")
    )
    workspace_context, workspace_files = workspace_prompt_context(
        project,
        workspace_terms,
        limit=WORKSPACE_FRAMEWORK_FILES,
        per_file_chars=18_000,
        max_chars=90_000,
    )
    if workspace_context:
        sections.append(PromptSection("workspace", "工作区目录（生成时实时读取）", 1, workspace_context))
    corpus_context = project_corpus_context(project)
    if corpus_context:
        sections.append(PromptSection("corpus", "参考项目语料", 4, corpus_context))
    mode = normalize_project_mode(project.get("mode", "new"))
    baseline_context = project_baseline_context(project) if mode != "new" else ""
    if baseline_context:
        sections.append(PromptSection("baseline", "当前项目基线", 3, baseline_context))
    sections, context_report = fit_prompt_sections(sections, context_char_budget(settings))

    skill_blocks = [section.text for section in sections if section.key.startswith("skill:") and section.text]
    material_blocks = [f"### {section.title}\n{section.text}" for section in sections if section.key.startswith("material:") and section.text]
    workspace_final = next((section.text for section in sections if section.key == "workspace"), "")
    corpus_final = next((section.text for section in sections if section.key == "corpus"), "")
    baseline_final = next((section.text for section in sections if section.key == "baseline"), "")

    mode_instruction = {
        "new": "这是全新开发项目，请从输入材料组织全新的文档框架。",
        "update": "这是版本更新项目。项目中已有的框架和 Topic 是上版本基线，请结合本次材料识别新增、修改、废弃、未变化内容，并在 topic_outline 中填写 change_status。",
        "optimize": "这是 Topic 优化项目。基线框架仅用于定位上下文，除非材料明确要求，不要因为语言优化而重排文档结构。",
    }[mode]
    system = """你是 HIK 文档开发工具中的文档框架设计器。请严格遵守已选 Skill，只根据输入材料生成新的文档框架，不得补造业务事实。
输入材料可能来自用户上传的文件，也可能来自项目工作区目录（工具实时读取）。两者都是可用依据，工作区文件的文件名可作为 source_materials。

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
{chr(10).join(skill_blocks) or '（无可用 Skill 内容。）'}

## 原始材料提取内容
{chr(10).join(material_blocks + empty_material_notes) or '（无可用材料文本。）'}

## 工作区目录（Agent 直接读取的本地文件）
以下内容由工具在生成时直接从项目工作区目录读取，不属于上传材料；文件名可以作为 source_materials 的引用依据。
{workspace_final or '当前项目未设置工作区目录。'}

## 当前项目基线（版本更新或 Topic 优化项目）
{baseline_final or '无当前项目基线。'}

## 参考项目实时语料库
以下内容来自用户选择的参考项目，生成时读取其当前定稿框架、Topic XML 和素材元数据。只能将其作为风格、结构和术语参考，不得把参考项目中的业务事实直接套用到当前项目；若没有参考项目，以下为空。
{corpus_final or '暂无参考项目语料。'}

只返回 JSON。"""
    return system, user, skill_names, context_report


def generate_framework(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    project = read_json(project_dir(project_id) / "project.json", None)
    if not isinstance(project, dict):
        raise ValueError("项目不存在。")
    materials = list_project_material_records(project_id)
    readable = [item for item in materials if str(item.get("extracted_text", "")).strip()]
    workspace_ready = workspace_has_readable(project_id, project)
    if not readable and not workspace_ready:
        if materials:
            raise ValueError(
                "当前材料均未成功提取文本，且项目没有可读取的工作区目录。请补充材料，或把包含需求文档的目录设为工作区。"
            )
        raise ValueError("请先上传至少一份需求材料，或在项目里设置工作区目录（生成时直接读取目录内容）。")
    settings = load_settings()
    system, user, skill_names, context_report = build_framework_ai_messages(project, payload, materials, settings)

    def parse_framework_result(raw_text: str) -> dict[str, Any]:
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
            raise RuntimeError("AI 未返回可识别的 Markdown 标题层级（需要至少一个 # 开头的标题）。")
        return {"parsed": parsed, "markdown": markdown}

    result_data, model = generate_with_repair(
        settings,
        system,
        user,
        parse_framework_result,
        max_tokens=DEFAULT_FRAMEWORK_MAX_TOKENS,
        json_mode=True,
    )
    parsed = result_data["parsed"]
    markdown = result_data["markdown"]
    supporting = normalize_analysis_result(parsed)
    with generation_commit():
        result = save_framework(
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
    result["context_report"] = context_report
    result["context_summary"] = context_report_summary(context_report)
    result["workspace"] = project_workspace(project)
    return result


def update_settings(payload: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    allowed = {"provider", "base_url", "model", "temperature", "timeout_seconds"}
    for key in allowed:
        if key in payload:
            settings[key] = payload[key]
    if "max_tokens" in payload:
        try:
            value = int(payload["max_tokens"] or 0)
        except (TypeError, ValueError):
            value = 0
        settings["max_tokens"] = value if value >= 256 else None
    if "context_char_budget" in payload:
        try:
            value = int(payload["context_char_budget"] or 0)
        except (TypeError, ValueError):
            value = 0
        settings["context_char_budget"] = value if value >= 40_000 else None
    if "structured_task" in payload:
        settings["structured_task"] = bool(payload["structured_task"])
    if "structured_output" in payload:
        settings["structured_output"] = bool(payload["structured_output"])
    if "max_parallel_workers" in payload:
        try:
            value = int(payload["max_parallel_workers"] or MAX_PARALLEL_DEFAULT)
        except (TypeError, ValueError):
            value = MAX_PARALLEL_DEFAULT
        settings["max_parallel_workers"] = max(1, min(value, 12))
    if "batch_chunk_size" in payload:
        try:
            value = int(payload["batch_chunk_size"] or BATCH_CHUNK_DEFAULT)
        except (TypeError, ValueError):
            value = BATCH_CHUNK_DEFAULT
        settings["batch_chunk_size"] = max(1, min(value, 100))
    if "api_key" in payload and str(payload["api_key"]).strip():
        KEYCHAIN.save(str(payload["api_key"]).strip())
    settings["updated_at"] = now_iso()
    write_json(SETTINGS_FILE, settings)
    return public_settings()


# AI 调用采集器（线程局部）：后台 Job 在独立线程串行调用，线程局部足够安全。
_AI_CALL_METAS = threading.local()


def begin_ai_call_collection() -> None:
    """Reset the per-thread AI call collector before a generation flow."""
    _AI_CALL_METAS.items = []


def collect_ai_call_meta(meta: dict[str, Any]) -> None:
    items = getattr(_AI_CALL_METAS, "items", None)
    if isinstance(items, list):
        items.append(meta)


def ai_call_metas() -> list[dict[str, Any]]:
    return list(getattr(_AI_CALL_METAS, "items", []) or [])


AI_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
AI_SDK_UA = "OpenAI/Python 1.68.0"


def endpoint_candidates(settings: dict[str, Any]) -> list[str]:
    """Return the endpoints worth trying for this base_url.

    中转站有的只认 `/v1/chat/completions`，有的把根路径直接映射到 chat
    completions。用户通常只粘贴一个域名，所以这里给出候选顺序，请求失败时
    逐个回退，而不是硬拼一个路径然后 404。
    """
    base_url = str(settings.get("base_url", "")).strip().rstrip("/")
    if not base_url:
        raise ValueError("请先填写 API 地址。")
    if base_url.endswith("/chat/completions") or base_url.endswith("/messages"):
        return [base_url]
    provider = settings.get("provider")
    if provider == "anthropic":
        if base_url.endswith("/v1"):
            return [base_url + "/messages"]
        return [base_url + "/v1/messages", base_url + "/messages"]
    if base_url.endswith("/v1"):
        return [base_url + "/chat/completions"]
    # 先按历史行为拼接根路径（原本能用的配置继续可用），404 再退到 /v1。
    return [base_url + "/chat/completions", base_url + "/v1/chat/completions"]


def endpoint_for(settings: dict[str, Any]) -> str:
    return endpoint_candidates(settings)[0]


def ai_user_agents(settings: dict[str, Any]) -> list[str]:
    """The UA order to try. Cloudflare 1010 blocks `Python-urllib/x.y`."""
    forced = str(settings.get("user_agent", "") or "").strip()
    if forced:
        return [forced]
    return [AI_BROWSER_UA, AI_SDK_UA]


def build_ai_headers(
    settings: dict[str, Any],
    provider: str,
    api_key: str,
    user_agent: str,
) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Encoding": "identity",
        "User-Agent": user_agent,
    }
    if provider == "anthropic":
        headers["x-api-key"] = api_key or ""
        headers["anthropic-version"] = "2023-06-01"
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def looks_like_waf_block(status: int, raw: str) -> bool:
    """Cloudflare 的 1010 / 挑战页，换 UA 或换路径重试才有意义。"""
    if status not in {403, 429, 503}:
        return False
    text = (raw or "").lower()
    return (
        "1010" in text
        or "cloudflare" in text
        or "just a moment" in text
        or "attention required" in text
    )


class AIHTTPError(RuntimeError):
    def __init__(self, status: int, raw: str, endpoint: str, attempts: list[str]):
        self.status = status
        self.raw = raw
        self.endpoint = endpoint
        self.attempts = attempts
        super().__init__(self.describe())

    def describe(self) -> str:
        if looks_like_waf_block(self.status, self.raw):
            return (
                f"HTTP {self.status}：请求被 Cloudflare 拦截（error code 1010 = 浏览器签名被封禁），"
                "不是 API Key 无效。已自动换浏览器 UA 并改用系统 curl 重试，仍未通过；"
                "请确认该中转站是否限制了调用来源（IP / 客户端）。"
            )
        if self.status in (401, 403):
            same_host = "copilot.tencent.com" in self.endpoint
            tip = (
                "WorkBuddy 账号 Key 要用「套餐与用量 → API 管理」里创建的 pt_ 开头 Key，"
                "Key 无效或已删除都会返回这个错。"
                if same_host
                else "请确认 Key 在这个接口地址下有效（有的中转站按 Key 区分线路）。"
            )
            return f"HTTP {self.status}：接口拒绝了这次请求，Key 未被接受。{tip}（请求地址：{self.endpoint}）"
        if self.status == 429:
            return (
                f"HTTP 429：请求被限流（请求地址：{self.endpoint}）。已自动退避重试 3 次并临时降低并发，仍未通过。"
                "通常是同一账号并发太高或额度用完：把「并行上限」调低（如 2–3）、或换一个 Agent 档案分批跑，"
                "等额度重置后再试。"
            )
        if self.status == 504:
            return (
                f"HTTP 504：上游网关超时（请求地址：{self.endpoint}），不是本机网络问题。"
                "对方返回的是「Key 校验服务暂不可用」这种通用降级文案，等一会儿重试通常能过；"
                "如果每次都是 504，多半是 Key 类型和这个地址不匹配（例如把中转站的 sk- Key 发给了只认 pt_ Key 的地址）。"
            )
        return f"服务返回 HTTP {self.status}（请求地址：{self.endpoint}）：{self.raw[:500]}"


def key_endpoint_conflict(endpoint: str, api_key: str) -> str | None:
    """WorkBuddy 官方网关只认 pt_ Key；其它前缀的 Key 会被它的校验服务打成 504。"""
    if "copilot.tencent.com" not in (endpoint or ""):
        return None
    key = (api_key or "").strip()
    if not key or key.startswith("pt_"):
        return None
    prefix = f"{key[:3]}…" if len(key) > 3 else "该"
    return (
        "接口地址和 Key 对不上：" + endpoint + " 只接受 WorkBuddy 账号里 pt_ 开头的 API Key，"
        f"现在这把是 {prefix} 开头的 Key（像是中转站或模型厂商发的），网关判断不了它的类型，"
        "于是固定返回 504「API key verification service temporarily unavailable」——看着像服务挂了，其实是 Key 不对口。"
        "两种改法：① 到 WorkBuddy 的「套餐与用量 → API 管理」创建一把 pt_ Key 填进来；"
        "② 把这个档案的接口地址换回这把 Key 所属的中转站地址再测。"
    )


def curl_post_json(
    endpoint: str,
    data: bytes,
    headers: dict[str, str],
    timeout: int,
) -> tuple[int, str] | None:
    """Last-resort transport for sites that fingerprint the TLS handshake.

    Python's stdlib cannot impersonate a browser's TLS stack, so a relay that
    answers 1010 to every pure-Python request is retried through the system
    curl, which uses OpenSSL/boringssl with a normal cipher order. Returns None
    when curl is unavailable.
    """
    executable = shutil.which("curl")
    if not executable:
        return None
    args = [executable, "-sS", "--max-time", str(max(5, timeout)), "-X", "POST", endpoint]
    for name, value in headers.items():
        args += ["-H", f"{name}: {value}"]
    args += ["--data-binary", "@-", "-w", "\n%{http_code}"]
    if is_private_endpoint(endpoint):
        args += ["--noproxy", "*"]
    else:
        proxy = urllib.request.getproxies().get("https")
        if proxy:
            args += ["--proxy", proxy]
    try:
        completed = subprocess.run(
            args,
            input=data,
            capture_output=True,
            timeout=timeout + 10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    raw = completed.stdout.decode("utf-8", errors="replace")
    body, _, status_text = raw.rpartition("\n")
    try:
        status = int(status_text.strip())
    except ValueError:
        return None
    if completed.returncode != 0 and status == 0:
        return None
    return status, body


def post_ai_json(
    settings: dict[str, Any],
    provider: str,
    api_key: str,
    body: dict[str, Any],
    timeout: int,
) -> tuple[int, str, str]:
    """POST chat payload, retrying paths, UAs and finally the curl transport.

    Returns (status, raw, endpoint). Raises AIHTTPError when every candidate
    is rejected, and RuntimeError for network level failures.
    """
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    endpoints = endpoint_candidates(settings)
    for candidate in endpoints:
        conflict = key_endpoint_conflict(candidate, api_key)
        if conflict:
            raise RuntimeError(conflict)
    user_agents = ai_user_agents(settings)
    attempts: list[str] = []
    waf_blocked = False
    last: AIHTTPError | None = None
    # 退避预算按「整次调用」共享，而不是每个 UA / 端点各给一份：
    # 否则一个被限流的 Key 会为同一条内容发出 8 次请求，越限越重。
    retries = 0
    for endpoint in endpoints:
        for user_agent in user_agents:
            while True:
                headers = build_ai_headers(settings, provider, api_key, user_agent)
                request = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
                try:
                    with AI_REQUEST_GATE.slot():
                        with open_ai_request(request, endpoint, timeout=timeout) as response:
                            raw = response.read().decode("utf-8", errors="replace")
                            AI_REQUEST_GATE.on_success()
                            return response.status, raw, endpoint
                except urllib.error.HTTPError as exc:
                    raw = exc.read().decode("utf-8", errors="replace")
                    attempts.append(f"{endpoint} → HTTP {exc.code}")
                    last = AIHTTPError(exc.code, raw, endpoint, attempts.copy())
                    if exc.code == 429:
                        # 限流的直接信号：先把并发压下来，再按 Retry-After 退避重试。
                        AI_REQUEST_GATE.on_rate_limited()
                    max_retries = len(AI_RETRY_BACKOFF) if exc.code == 429 else 1
                    if exc.code in AI_RETRYABLE_STATUS and retries < max_retries:
                        wait = retry_after_seconds(exc, retries)
                        retries += 1
                        time.sleep(wait)
                        continue
                    if exc.code == 429:
                        # 换 UA 或换端点都救不了限流，直接报错，别继续打。
                        raise last from exc
                    if looks_like_waf_block(exc.code, raw):
                        waf_blocked = True
                        break
                    if exc.code in {404, 405} or exc.code in AI_RETRYABLE_STATUS:
                        break
                    raise last from exc
                except urllib.error.URLError as exc:
                    raise RuntimeError(f"网络连接失败（请求地址：{endpoint}）：{exc.reason}") from exc
                except ConnectionRefusedError as exc:
                    raise RuntimeError(f"模型地址拒绝连接：{endpoint}") from exc
                except TimeoutError as exc:
                    raise RuntimeError("请求超时，请检查地址或超时设置。") from exc

    if waf_blocked and not str(settings.get("transport", "")) == "urllib":
        for endpoint in endpoints:
            headers = build_ai_headers(settings, provider, api_key, ai_user_agents(settings)[0])
            result = curl_post_json(endpoint, data, headers, timeout)
            if result is None:
                break
            status, raw = result
            attempts.append(f"{endpoint}（curl 传输）→ HTTP {status}")
            if 200 <= status < 300:
                return status, raw, endpoint
            if status in {404, 405} or looks_like_waf_block(status, raw):
                last = AIHTTPError(status, raw, endpoint, attempts.copy())
                continue
            last = AIHTTPError(status, raw, endpoint, attempts.copy())
            raise last

    if last is not None:
        raise last
    raise RuntimeError("请求未能发出，请检查 API 地址。")


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


def test_ai_connection(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings if isinstance(settings, dict) else load_settings()
    provider = settings.get("provider", "openai-compatible")
    model = str(settings.get("model", "")).strip()
    if not model and provider != "local":
        raise ValueError("请先填写模型名称。")
    api_key = settings.get("_api_key") or KEYCHAIN.get()
    if provider != "local" and not api_key:
        raise ValueError("尚未配置 API Key。")

    if provider == "anthropic":
        body = {
            "model": model,
            "max_tokens": 8,
            "messages": [{"role": "user", "content": "只回复 OK"}],
        }
    else:
        body = {
            "model": model,
            "temperature": 0,
            "max_tokens": 8,
            "messages": [{"role": "user", "content": "只回复 OK"}],
        }

    timeout = int(settings.get("timeout_seconds", 60))
    try:
        status, raw, endpoint = post_ai_json(settings, provider, api_key or "", body, timeout)
    except AIHTTPError as exc:
        raise RuntimeError(exc.describe()) from exc

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


TASK_STRUCTURE_INSTRUCTION = """本次生成 Task Topic 时不要直接输出 XML。只返回一个 JSON 对象，字段如下：
- "title"：Task 标题（字符串，必填）；
- "shortdesc"：短描述（字符串，必填，3 句以内，回答 Why/What，不放具体步骤）；
- "prerequisites"：前置条件字符串数组，使用“已创建/已执行/已完成 XX”句式，可为空数组；
- "context": 正文说明段落字符串数组，可为空数组；
- "steps"：操作步骤数组（必填，至少 2 步），每个元素为对象：
  - "command"：操作命令（必填），使用“在 XX 位置，单击 XX。”句式，一个步骤只包含一个动作；
  - "info"：该步骤的补充说明字符串数组，可为空数组；
  - "result"：该步骤的系统反馈字符串，可为空字符串；
- "overall_result"：整体操作结果字符串数组，可为空数组；
- "unconfirmed"：素材未确认的事实数组，每个元素为 {"claim": "...", "reason": "..."}；禁止编造参数、按钮、数值或业务行为，素材无法确认的内容必须登记到这里，正文中对应位置使用 TODO_CONFIRM 占位，可为空数组。

只返回该 JSON 对象，不要返回 Markdown 围栏、解释或 XML。"""


def parse_task_structure(raw_text: str) -> dict[str, Any]:
    """Parse and validate the structured Task middle representation.

    Raises RuntimeError with user-facing issues so generate_with_repair can
    feed them back to the model.
    """
    text = clean_ai_json(raw_text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Task 中间稿不是有效 JSON：{str(exc)[:240]}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Task 中间稿必须是 JSON 对象。")
    title = sanitize_text(data.get("title"))
    shortdesc = sanitize_text(data.get("shortdesc"))
    if not title:
        raise RuntimeError("Task 中间稿缺少非空 title 字段。")
    if not shortdesc:
        raise RuntimeError("Task 中间稿缺少非空 shortdesc 字段。")

    prerequisites = parse_lines(data.get("prerequisites"))
    context = parse_lines(data.get("context"))

    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise RuntimeError("Task 中间稿缺少 steps 数组；Task 至少需要 2 个操作步骤。")
    steps: list[dict[str, Any]] = []
    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict):
            raise RuntimeError(f"第 {index} 个步骤必须是对象（含 command 字段）。")
        command = sanitize_text(raw_step.get("command"))
        if not command:
            raise RuntimeError(f"第 {index} 个步骤缺少非空 command 字段。")
        steps.append(
            {
                "command": command,
                "info": parse_lines(raw_step.get("info")),
                "result": sanitize_text(raw_step.get("result")),
            }
        )
    if len(steps) < 2:
        raise RuntimeError(f"Task 至少需要 2 个操作步骤，当前只有 {len(steps)} 步，请补充步骤。")

    overall_result = parse_lines(data.get("overall_result"))

    unconfirmed: list[dict[str, str]] = []
    raw_unconfirmed = data.get("unconfirmed")
    if isinstance(raw_unconfirmed, list):
        for item in raw_unconfirmed[:50]:
            if isinstance(item, dict):
                claim = sanitize_text(item.get("claim"))
                if claim:
                    unconfirmed.append({"claim": claim, "reason": sanitize_text(item.get("reason"))})

    return {
        "title": title,
        "shortdesc": shortdesc,
        "prerequisites": prerequisites,
        "context": context,
        "steps": steps,
        "overall_result": overall_result,
        "unconfirmed": unconfirmed,
    }


def render_task_topic_xml(structure: dict[str, Any]) -> str:
    """Render the structured Task middle representation into DITA Task XML.

    Escaping, nesting, element order and step ids are guaranteed here, so the
    model never has to produce XML itself.
    """
    title = sanitize_text(structure.get("title"))
    shortdesc = sanitize_text(structure.get("shortdesc"))
    prerequisites = [sanitize_text(item) for item in structure.get("prerequisites", []) if sanitize_text(item)]
    context = [sanitize_text(item) for item in structure.get("context", []) if sanitize_text(item)]
    steps = structure.get("steps", [])
    overall_result = [sanitize_text(item) for item in structure.get("overall_result", []) if sanitize_text(item)]

    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<!DOCTYPE task PUBLIC "-//OASIS//DTD DITA Task//EN" "task.dtd"[]>',
        f'<task id="TOPIC_{xml_escape(slugify(title))}" xml:lang="zh-CN">',
        f"    <title>{xml_escape(title)}</title>",
        f"    <shortdesc>{xml_escape(shortdesc)}</shortdesc>",
        "    <taskbody>",
    ]
    if prerequisites:
        lines.append("        <prereq>")
        lines.append("            <ul>")
        for item in prerequisites:
            lines.extend(["                <li>", f"                    <p>{xml_escape(item)}</p>", "                </li>"])
        lines.extend(["            </ul>", "        </prereq>"])
    if context:
        lines.append("        <context>")
        for item in context:
            lines.append(f"            <p>{xml_escape(item)}</p>")
        lines.append("        </context>")
    lines.append("        <steps>")
    for index, step in enumerate(steps, start=1):
        command = sanitize_text(step.get("command"))
        info_items = [sanitize_text(item) for item in step.get("info", []) if sanitize_text(item)]
        step_result = sanitize_text(step.get("result"))
        lines.extend([f'            <step id="STEP_{index}">', f"                <cmd>{xml_escape(command)}</cmd>"])
        for info_item in info_items:
            lines.extend(["                <info>", f"                    <p>{xml_escape(info_item)}</p>", "                </info>"])
        if step_result:
            lines.extend(["                <stepresult>", f"                    <p>{xml_escape(step_result)}</p>", "                </stepresult>"])
        lines.append("            </step>")
    lines.append("        </steps>")
    if overall_result:
        lines.append("        <result>")
        for item in overall_result:
            lines.append(f"            <p>{xml_escape(item)}</p>")
        lines.append("        </result>")
    lines.extend(["    </taskbody>", "</task>"])
    return "\n".join(lines) + "\n"


CONCEPT_STRUCTURE_INSTRUCTION = """本次生成 Concept Topic 时不要直接输出 XML。只返回一个 JSON 对象，字段如下：
- "title"：Concept 标题（字符串，必填）；
- "shortdesc"：短描述（字符串，必填，3 句以内，回答 What/When/Why，不放具体步骤、图表或链接）；
- "context"：正文引言段落字符串数组（conbody 下的直接段落，可为空数组）；
- "sections"：章节对象数组（必填，至少 1 个），每个元素为对象：
  - "title"：节标题（必填）；
  - "level"：层级 1-3，默认 1；
  - "paragraphs"：该节的段落字符串数组（至少 1 段）；
- "unconfirmed"：素材未确认的事实数组，每个元素为 {"claim": "...", "reason": "..."}；禁止编造参数、按钮、数值或业务行为，素材无法确认的内容必须登记到这里，正文中对应位置使用 TODO_CONFIRM 占位，可为空数组。

只返回该 JSON 对象，不要返回 Markdown 围栏、解释或 XML。"""


def parse_concept_structure(raw_text: str) -> dict[str, Any]:
    """Parse and validate the structured Concept middle representation."""
    text = clean_ai_json(raw_text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Concept 中间稿不是有效 JSON：{str(exc)[:240]}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Concept 中间稿必须是 JSON 对象。")
    title = sanitize_text(data.get("title"))
    shortdesc = sanitize_text(data.get("shortdesc"))
    if not title:
        raise RuntimeError("Concept 中间稿缺少非空 title 字段。")
    if not shortdesc:
        raise RuntimeError("Concept 中间稿缺少非空 shortdesc 字段。")
    context = parse_lines(data.get("context"))

    raw_sections = data.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raise RuntimeError("Concept 中间稿缺少 sections 数组；至少需要 1 个章节。")
    sections: list[dict[str, Any]] = []
    for index, raw_section in enumerate(raw_sections, start=1):
        if not isinstance(raw_section, dict):
            raise RuntimeError(f"第 {index} 个章节必须是对象（含 title、paragraphs 字段）。")
        section_title = sanitize_text(raw_section.get("title"))
        if not section_title:
            raise RuntimeError(f"第 {index} 个章节缺少非空 title 字段。")
        paragraphs = parse_lines(raw_section.get("paragraphs"))
        if not paragraphs:
            raise RuntimeError(f"章节“{section_title}”缺少段落内容（paragraphs 至少 1 段）。")
        try:
            level = max(1, min(3, int(raw_section.get("level", 1))))
        except (TypeError, ValueError):
            level = 1
        sections.append({"title": section_title, "level": level, "paragraphs": paragraphs})

    unconfirmed: list[dict[str, str]] = []
    raw_unconfirmed = data.get("unconfirmed")
    if isinstance(raw_unconfirmed, list):
        for item in raw_unconfirmed[:50]:
            if isinstance(item, dict):
                claim = sanitize_text(item.get("claim"))
                if claim:
                    unconfirmed.append({"claim": claim, "reason": sanitize_text(item.get("reason"))})

    return {
        "title": title,
        "shortdesc": shortdesc,
        "context": context,
        "sections": sections,
        "unconfirmed": unconfirmed,
    }


def render_concept_topic_xml(structure: dict[str, Any]) -> str:
    """Render the structured Concept middle representation into DITA Concept XML.

    Section nesting, ids and escaping are guaranteed here, mirroring the
    hand-built template in build_topic_xml.
    """
    title = sanitize_text(structure.get("title"))
    shortdesc = sanitize_text(structure.get("shortdesc"))
    context = [sanitize_text(item) for item in structure.get("context", []) if sanitize_text(item)]
    sections = structure.get("sections", [])

    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<!DOCTYPE concept PUBLIC "-//OASIS//DTD DITA Concept//EN" "concept.dtd"[]>',
        f'<concept id="TOPIC_{xml_escape(slugify(title))}" xml:lang="zh-CN">',
        f"    <title>{xml_escape(title)}</title>",
        f"    <shortdesc>{xml_escape(shortdesc)}</shortdesc>",
        "    <conbody>",
    ]
    for paragraph in context:
        lines.append(f"        <p>{xml_escape(paragraph)}</p>")

    stack: list[dict[str, Any]] = []
    counters: list[int] = []
    for item in sections:
        level = max(1, min(3, int(item.get("level", 1) or 1)))
        if not stack:
            level = 1
        elif level > len(stack) + 1:
            level = len(stack) + 1
        while len(stack) >= level:
            lines.append("    " * (1 + len(stack)) + "</section>")
            stack.pop()
        while len(counters) < level:
            counters.append(0)
        counters[level - 1] += 1
        del counters[level:]
        section_id = "SECTION_" + "_".join(str(value) for value in counters)
        indent = "    " * (1 + len(stack))
        lines.append(f'{indent}<section id="{section_id}">')
        lines.append(f"{indent}    <title>{xml_escape(sanitize_text(item.get('title')))}</title>")
        for paragraph in item.get("paragraphs", []):
            text = sanitize_text(paragraph)
            if text:
                lines.append(f"{indent}    <p>{xml_escape(text)}</p>")
        stack.append({"level": level})
    while stack:
        lines.append("    " * (1 + len(stack)) + "</section>")
        stack.pop()
    lines.extend(["    </conbody>", "</concept>"])
    return "\n".join(lines) + "\n"


def topic_query_terms(payload: dict[str, Any]) -> list[str]:
    """Extract rough topic keywords (CJK runs + latin words) for material slicing."""
    sources = [
        payload.get("title"),
        payload.get("shortdesc"),
        payload.get("chapter_summary"),
        payload.get("brief"),
        payload.get("generation_prompt"),
    ]
    try:
        outline = payload.get("outline")
        if isinstance(outline, list):
            sources.extend(str(item.get("title", "")) if isinstance(item, dict) else str(item) for item in outline)
    except AttributeError:
        pass
    terms: list[str] = []
    for source in sources:
        for token in re.findall(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,6}", str(source or "")):
            token = token.strip()
            if token and token not in terms:
                terms.append(token)
    return terms[:60]


def slice_material_for_topic(text: str, terms: list[str], max_chars: int = TOPIC_SLICE_MAX_CHARS) -> tuple[str, list[list[int]]]:
    """Slice an oversized material around paragraphs matching the topic terms.

    Returns (context_text, ranges). ranges is empty when the material fits and
    was returned verbatim; otherwise it records the [start, end] offsets of the
    kept segments in the original text for paragraph-level traceability.
    """
    text = str(text or "")
    if len(text) <= max_chars:
        return text, []
    paragraphs: list[tuple[int, int, str]] = []
    for match in re.finditer(r"[^\n]+", text):
        segment = match.group(0).strip()
        if segment:
            paragraphs.append((match.start(), match.end(), segment))
    if not paragraphs:
        return text[:max_chars], [[0, max_chars]]

    lowered_terms = [term.lower() for term in terms if len(term) >= 2]

    def score(segment: str) -> int:
        lowered = segment.lower()
        return sum(1 for term in lowered_terms if term in lowered)

    scored = [(score(segment), index) for index, (_, _, segment) in enumerate(paragraphs)]
    chosen: set[int] = set()
    used = 0
    # 优先取相关性最高的段落及其相邻段落，保证上下文完整。
    for _, index in sorted(((value, index) for value, index in scored if value > 0), key=lambda item: (-item[0], item[1])):
        for neighbor in (index - 1, index, index + 1):
            if 0 <= neighbor < len(paragraphs) and neighbor not in chosen:
                length = paragraphs[neighbor][1] - paragraphs[neighbor][0] + 1
                if used + length > max_chars:
                    continue
                chosen.add(neighbor)
                used += length
        if used >= max_chars:
            break
    if not chosen:
        chosen = set(range(min(len(paragraphs), max(1, max_chars // 200))))
        used = sum(paragraphs[index][1] - paragraphs[index][0] + 1 for index in chosen)

    ranges: list[list[int]] = []
    blocks: list[str] = []
    for index in sorted(chosen):
        start, end, segment = paragraphs[index]
        ranges.append([start, end])
        blocks.append(f"［原文 {start}–{end}］{segment}")
    return "\n".join(blocks), ranges


def list_project_unconfirmed(project_id: str) -> dict[str, Any]:
    """Aggregate every topic's unconfirmed facts and TODO_CONFIRM counts."""
    project = read_json(project_dir(project_id) / "project.json", None)
    if not isinstance(project, dict):
        raise ValueError("项目不存在。")
    items: list[dict[str, Any]] = []
    total_confirm_count = 0
    for topic in list_topics(project_id):
        confirm_count = int((topic.get("validation") or {}).get("confirm_count", 0) or 0)
        total_confirm_count += confirm_count
        for entry in topic.get("unconfirmed", []) or []:
            if isinstance(entry, dict) and entry.get("claim"):
                items.append(
                    {
                        "topic_id": topic.get("id"),
                        "topic_title": topic.get("title"),
                        "claim": entry.get("claim"),
                        "reason": entry.get("reason"),
                    }
                )
    return {
        "project_id": project_id,
        "items": items,
        "topic_confirm_count": total_confirm_count,
    }


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


def sibling_context_block(payload: dict[str, Any]) -> str:
    """Render parent/sibling chapter context provided by the frontend.

    Sibling titles tell the model which content belongs to other Topics so it
    stops duplicating neighbouring sections and keeps boundaries clear.
    """
    parent_title = sanitize_text(payload.get("parent_title"))
    raw_siblings = payload.get("sibling_topics")
    siblings: list[dict[str, str]] = []
    if isinstance(raw_siblings, list):
        for item in raw_siblings[:30]:
            if isinstance(item, dict):
                title = sanitize_text(item.get("title"))
                if not title:
                    continue
                siblings.append(
                    {
                        "title": title,
                        "topic_type": sanitize_text(item.get("topic_type")) or "concept",
                        "shortdesc": sanitize_text(item.get("shortdesc"))[:200],
                    }
                )
            else:
                title = sanitize_text(item)
                if title:
                    siblings.append({"title": title, "topic_type": "concept", "shortdesc": ""})
    if not parent_title and not siblings:
        return ""
    lines: list[str] = []
    if parent_title:
        lines.append(f"- 所属父章节：{parent_title}")
    for sibling in siblings:
        desc = f"：{sibling['shortdesc']}" if sibling["shortdesc"] else ""
        lines.append(f"- {sibling['title']}（{sibling['topic_type']}）{desc}")
    header = (
        "## 兄弟章节上下文\n"
        "以下章节由其他 Topic 承担，本 Topic 不要展开它们的内容，只保持边界清晰、避免重复。"
    )
    return header + "\n" + "\n".join(lines)


def build_topic_ai_messages(
    project: dict[str, Any], payload: dict[str, Any], *, structured: bool = False, settings: dict[str, Any] | None = None
) -> tuple[str, str, list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build the topic generation prompt under a global context budget.

    Section priority (kept longest first): 素材 > Skill > 上一版 XML > 语料。
    Oversized materials are sliced by topic relevance with original-text offsets
    for traceability. Returns (system, user, skill_names, context_report,
    material_slices).
    """
    topic_type = str(payload.get("topic_type", "concept"))
    type_name = TOPIC_TYPES.get(topic_type, "Concept")
    inherit_project_skills = payload.get("inherit_project_skills", True) is not False
    selected_skills = payload.get("skills", project.get("skills", []))
    effective_skills = resolve_topic_skill_names(project, selected_skills, inherit_project_skills)
    records = selected_skill_records(effective_skills)
    skill_names = [str(item["name"]) for item in records]

    sections: list[PromptSection] = []
    for skill in records:
        block = f"## Skill：{skill['name']}\n{skill.get('content', '')}"
        attachments = text_attachment_context(skill)
        if attachments:
            block += f"\n\n## Skill 附件上下文\n{attachments}"
        sections.append(PromptSection(f"skill:{skill.get('id', skill['name'])}", f"Skill：{skill['name']}", 2, block))

    selected_material_ids = set(parse_lines(payload.get("material_ids")))
    project_materials = list_project_material_records(str(project.get("id", "")))
    selected_materials = [item for item in project_materials if str(item.get("id")) in selected_material_ids]
    terms = topic_query_terms(payload)
    material_slices: list[dict[str, Any]] = []
    for item in selected_materials:
        material_text = str(item.get("extracted_text", "")).strip()
        if not material_text:
            continue
        slice_text, ranges = slice_material_for_topic(material_text, terms)
        sliced = bool(ranges)
        material_slices.append(
            {
                "material_id": str(item.get("id", "")),
                "name": str(item.get("name", "未命名")),
                "mode": "sliced" if sliced else "full",
                "total_chars": len(material_text),
                "ranges": ranges,
            }
        )
        sections.append(
            PromptSection(
                f"material:{item.get('id', '')}",
                f"研发素材：{item.get('name', '未命名')}" + ("（已按主题切片，保留原文偏移）" if sliced else ""),
                1,
                slice_text,
            )
        )

    workspace_context, workspace_files = workspace_prompt_context(
        project,
        terms,
        limit=WORKSPACE_TOPIC_FILES,
        per_file_chars=12_000,
        max_chars=48_000,
    )
    if workspace_context:
        sections.append(PromptSection("workspace", "工作区目录（生成时实时读取）", 1, workspace_context))
        for item in workspace_files:
            material_slices.append(
                {
                    "material_id": f"workspace:{item['relative']}",
                    "name": item["relative"],
                    "mode": "workspace",
                    "total_chars": item.get("chars", 0),
                    "ranges": [],
                }
            )

    previous_xml = str(payload.get("previous_xml") or "").strip()
    if previous_xml:
        # 保留原始 XML（含真实 GUID/conref 引用）；结构保留编辑在后续版本处理。
        sections.append(PromptSection("previous_xml", "上一版 XML", 3, previous_xml))

    corpus_context = project_corpus_context(project)
    if corpus_context:
        sections.append(PromptSection("corpus", "参考项目语料", 4, corpus_context))

    sections, context_report = fit_prompt_sections(sections, context_char_budget(settings))

    skill_context = "\n\n".join(section.text for section in sections if section.key.startswith("skill:") and section.text)
    material_blocks = [
        f"### {section.title}\n{section.text}"
        for section in sections
        if section.key.startswith("material:") and section.text
    ]
    material_context = "\n\n".join(material_blocks) or "暂无本次选择的研发素材。"
    workspace_final = next((section.text for section in sections if section.key == "workspace"), "")
    previous_context = next((section.text for section in sections if section.key == "previous_xml"), "")
    corpus_final = next((section.text for section in sections if section.key == "corpus"), "")

    generation_mode = str(payload.get("generation_mode", "new")).strip().lower()
    if generation_mode == "optimize":
        mode_instruction = "这是 Topic 优化：只优化语言、结构、术语一致性和表达清晰度，不改变业务事实，不擅自新增功能，尽量保留原 XML 标签结构。"
    elif normalize_project_mode(project.get("mode", "new")) == "update":
        mode_instruction = "这是版本更新：基于上一版 Topic 和本次输入材料更新内容，允许新增、删除或调整必要的 XML 结构，但不得编造事实。"
    else:
        mode_instruction = "这是全新 Topic：根据当前已确认材料从零编写。"

    if structured:
        output_instruction = (
            f"按本提示末尾“{type_name} 输出格式”返回 JSON 中间稿，不要自己输出 XML。"
        )
        unconfirmed_instruction = (
            "素材无法确认的事实登记到 unconfirmed 数组，正文对应位置使用 TODO_CONFIRM 占位，绝对不要编造。"
        )
    else:
        output_instruction = "只输出一个可解析的 DITA XML 文档，不输出解释、Markdown 代码围栏或前后说明。"
        unconfirmed_instruction = (
            "使用 TODO_CONFIRM 占位并尽量在正文中标注待确认内容，或写“请根据已确认需求补充”。"
        )

    system = f"""你是 HIK 文档开发工具中的 Topic 生成器。你必须严格遵守用户提供的 Skill。
输入可能包含用户上传的素材，以及工具从项目工作区目录实时读取的文件；两者都属于可依据的材料，均不得超出其内容编造事实。

输出要求：
1. {output_instruction}
2. Topic 类型只能是 Concept 或 Task。Reference 当前不生成。
3. 不生成 GUID Token（形如 GUID-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx 或 GUID=xxx）。XML id 使用稳定、可读且非 GUID 的英文或拼音标识。
4. 图片引用使用 TODO_IMAGE，交叉引用使用 TODO_REF，素材未确认的事实使用 TODO_CONFIRM。保留占位符，供工程师后续手动替换。
5. 事实不足时不要编造具体参数、按钮、数值或业务行为；{unconfirmed_instruction}
6. Concept 使用 conbody 和 section；Task 使用 taskbody、prereq、steps。每个操作步骤只包含一个动作，步骤至少 2 步。
7. 文案遵守海康写作规范：使用“您”、使用“单击”，短描述不超过 3 句，保持术语一致，数字和单位规范。
8. {mode_instruction}
"""
    if structured:
        structure_instruction = TASK_STRUCTURE_INSTRUCTION if topic_type == "task" else CONCEPT_STRUCTURE_INSTRUCTION
        system += "\n" + structure_instruction

    outline = parse_outline_items(payload.get("outline"))
    user = f"""请基于以下信息生成 {type_name} Topic。

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

{sibling_context_block(payload)}

## 已选 Skill
{skill_context or '（无可用 Skill 内容。）'}

## 本次选择的研发素材
{material_context}

## 工作区目录（Agent 直接读取的本地文件）
以下内容由工具在生成时直接从项目工作区目录读取，不属于上传材料；文件名可以作为来源引用。
{workspace_final or '当前项目未设置工作区目录。'}

## 上一版 XML（仅在重生成时提供）
{previous_context or '无'}

## 参考项目实时语料库
以下内容仅作为术语、结构和表达参考，不能替代当前项目材料，也不能直接引入其中未被当前需求确认的业务事实。
{corpus_final or '暂无参考项目语料。'}

{'请按系统提示的 JSON 中间稿格式返回。' if structured else '请只返回最终 XML。'}"""
    return system, user, skill_names, context_report, material_slices


def _configured_max_tokens(settings: dict[str, Any], fallback: int) -> int:
    try:
        value = int(settings.get("max_tokens") or 0)
    except (TypeError, ValueError):
        value = 0
    return value if value >= 256 else fallback


def call_ai_messages(
    settings: dict[str, Any],
    system: str,
    messages: list[dict[str, str]],
    max_tokens: int = 6000,
    json_mode: bool = False,
) -> tuple[str, str]:
    """Send a multi-turn chat request and return (text, model).

    - Inspects finish_reason/stop_reason so a max_tokens truncation is reported
      clearly instead of surfacing later as a confusing parse error.
    - json_mode asks for strict JSON output (OpenAI response_format or an
      Anthropic "{" prefill); servers that reject response_format fall back to
      plain mode automatically.
    - Every call appends a meta entry (usage/stop_reason/model) to the
      thread-local collector; generation flows read it via ai_call_metas().
    """
    provider = str(settings.get("provider", "openai-compatible"))
    model = str(settings.get("model", "")).strip()
    if not model and provider != "local":
        raise ValueError("请先填写模型名称。")
    endpoint = endpoint_for(settings)
    api_key = settings.get("_api_key") or KEYCHAIN.get()
    if provider != "local" and not api_key:
        raise ValueError("尚未配置 API Key，请先在“AI 服务配置”中保存。")
    effective_max_tokens = _configured_max_tokens(settings, max_tokens)
    temperature = float(settings.get("temperature", 0.2))
    timeout = int(settings.get("timeout_seconds", 60))

    def build_request(allow_json: bool):
        nonlocal messages
        anthropic_prefill = provider == "anthropic" and allow_json and json_mode
        if provider == "anthropic":
            body: dict[str, Any] = {
                "model": model,
                "max_tokens": effective_max_tokens,
                "temperature": temperature,
                "system": system,
                "messages": messages + ([{"role": "assistant", "content": "{"}] if anthropic_prefill else []),
            }
        else:
            body = {
                "model": model,
                "temperature": temperature,
                "max_tokens": effective_max_tokens,
                "messages": [{"role": "system", "content": system}, *messages],
            }
            if allow_json and json_mode:
                body["response_format"] = {"type": "json_object"}
        return body, anthropic_prefill

    modes = [True, False] if json_mode else [False]
    raw = ""
    prefill_used = False
    last_error: Exception | None = None
    for allow_json in modes:
        body, prefill_used = build_request(allow_json)
        try:
            _, raw, _endpoint = post_ai_json(settings, provider, api_key or "", body, timeout)
            last_error = None
            break
        except AIHTTPError as exc:
            # 兼容不支持 response_format 的 OpenAI-compatible 服务：降级后重试一次。
            if allow_json and exc.status == 400 and "response_format" in exc.raw.lower():
                last_error = RuntimeError(exc.describe())
                continue
            raise RuntimeError("AI " + exc.describe()) from exc
    if last_error is not None:
        raise last_error

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("AI 服务返回的内容不是有效 JSON。") from exc

    if provider == "anthropic":
        stop_reason = str(data.get("stop_reason", "") or "")
    else:
        choices = data.get("choices", [])
        first = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
        stop_reason = str(first.get("finish_reason", "") or "")
    truncated = stop_reason in {"length", "max_tokens"}

    text = ai_response_text(data, provider).strip()
    if prefill_used and text and not text.lstrip().startswith("{"):
        text = "{" + text.lstrip()
    if truncated and not text:
        raise RuntimeError(
            f"AI 输出被 max_tokens（{effective_max_tokens}）截断且无内容，请在 AI 服务配置中调大 max_tokens 或缩小输入。"
        )
    if not text:
        raise RuntimeError("AI 服务未返回文本内容。")
    # usage 计数（修复清单 4.5）：此前被丢弃，现采集进调用日志。
    usage_raw = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    if provider == "anthropic":
        usage = {
            "input_tokens": int(usage_raw.get("input_tokens", 0) or 0),
            "output_tokens": int(usage_raw.get("output_tokens", 0) or 0),
        }
    else:
        usage = {
            "input_tokens": int(usage_raw.get("prompt_tokens", 0) or 0),
            "output_tokens": int(usage_raw.get("completion_tokens", 0) or 0),
        }
    collect_ai_call_meta({"usage": usage, "stop_reason": stop_reason, "model": model or "本地模型"})
    return text, model or "本地模型"


def call_ai_text(
    settings: dict[str, Any], system: str, user: str, max_tokens: int = 6000, json_mode: bool = False
) -> tuple[str, str]:
    return call_ai_messages(
        settings, system, [{"role": "user", "content": user}], max_tokens=max_tokens, json_mode=json_mode
    )


REPAIR_FEEDBACK_TEMPLATE = (
    "你上次的输出存在以下问题：\n{error}\n\n"
    "请重新输出完整且已修正的结果。只返回结果本身，不要解释，不要道歉，不要附加说明。"
)


def generate_with_repair(
    settings: dict[str, Any],
    system: str,
    user: str,
    parse_result: Any,
    *,
    max_tokens: int = 6000,
    json_mode: bool = False,
    max_attempts: int = 3,
) -> tuple[Any, str]:
    """Call the AI and feed validation/parse errors back for up to max_attempts tries.

    parse_result(text) must return the parsed value, or raise RuntimeError /
    ValueError with a user-facing issue description (also sent back to the
    model). JobCancelled always propagates so cancellation stays responsive.
    """
    messages: list[dict[str, str]] = [{"role": "user", "content": user}]
    last_error = ""
    begin_ai_call_collection()
    for attempt in range(1, max_attempts + 1):
        text, model = call_ai_messages(settings, system, messages, max_tokens=max_tokens, json_mode=json_mode)
        try:
            return parse_result(text), model
        except JobCancelled:
            raise
        except (RuntimeError, ValueError, ET.ParseError) as exc:
            last_error = str(exc)
            if attempt >= max_attempts:
                break
            check_job_cancelled()
            messages = messages + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": REPAIR_FEEDBACK_TEMPLATE.format(error=last_error)},
            ]
    raise RuntimeError(f"AI 输出在 {max_attempts} 次尝试后仍未通过校验。最后错误：{last_error}")


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
    settings = load_settings()
    expected_root = "task" if topic_type == "task" else "concept"
    previous_xml = str(payload.get("previous_xml") or "").strip()
    structured_enabled = bool(settings.get("structured_output", settings.get("structured_task", True)))
    # 结构化中间稿覆盖全新/更新的 Task 与 Concept；优化模式涉及既有 XML 改写，
    # 仍走直接 XML 路径，等结构保留编辑（修复清单 2.4）落地后再切换。
    structured = (
        topic_type in {"task", "concept"}
        and not previous_xml
        and structured_enabled
    )
    system, user, skill_names, context_report, material_slices = build_topic_ai_messages(
        project, payload, structured=structured, settings=settings
    )
    unconfirmed: list[dict[str, str]] = []
    if structured:
        if topic_type == "task":
            parse_structure: Any = parse_task_structure
            render_structure: Any = render_task_topic_xml
        else:
            parse_structure = parse_concept_structure
            render_structure = render_concept_topic_xml
        structure, model = generate_with_repair(
            settings,
            system,
            user,
            parse_structure,
            max_tokens=DEFAULT_TOPIC_MAX_TOKENS,
            json_mode=True,
        )
        xml_text = render_structure(structure)
        unconfirmed = structure.get("unconfirmed", [])
    else:
        def parse_topic_xml(raw_text: str) -> str:
            xml_candidate = clean_ai_xml(raw_text)
            if not xml_candidate:
                raise RuntimeError("AI 服务未返回 XML 内容。")
            try:
                root = ET.fromstring(xml_candidate)
            except ET.ParseError as exc:
                raise RuntimeError(f"AI 返回的 XML 无法解析：{exc}") from exc
            if root.tag != expected_root:
                raise RuntimeError(f"AI 返回的根标签为 <{root.tag}>，预期为 <{expected_root}>。")
            return xml_candidate

        xml_text, model = generate_with_repair(
            settings,
            system,
            user,
            parse_topic_xml,
            max_tokens=DEFAULT_TOPIC_MAX_TOKENS,
        )
    validation = validate_topic_xml(xml_text)
    lint_report = lint_topic_xml(xml_text, topic_type)
    # 生成记录（修复清单 4.5）：模型参数、Skill 哈希、prompt 哈希/摘要、usage、lint 摘要。
    metas = ai_call_metas()
    usage = {
        "input_tokens": sum(int((meta.get("usage") or {}).get("input_tokens", 0) or 0) for meta in metas),
        "output_tokens": sum(int((meta.get("usage") or {}).get("output_tokens", 0) or 0) for meta in metas),
    }
    generation_mode = "structured-task" if structured and topic_type == "task" else ("structured-concept" if structured else "direct-xml")
    try:
        record_generation_log(
            project_id,
            {
                "operation": "topic-generate",
                "topic_type": topic_type,
                "generation_mode": generation_mode,
                "structured": structured,
                "provider": settings.get("provider"),
                "model": model,
                "model_setting": settings.get("model"),
                "temperature": settings.get("temperature"),
                "max_tokens_setting": settings.get("max_tokens"),
                "skill_names": skill_names,
                "skill_hashes": _skill_content_hashes(skill_names),
                "prompt_chars": len(system) + len(user),
                "prompt_hash": {"system": _sha16(system), "user": _sha16(user)},
                "prompt_summary": user[:200],
                "material_ids": payload.get("material_ids") or [],
                "material_slice_count": len(material_slices or []),
                "attempts": max(1, len(metas)),
                "usage": usage,
                "xml_chars": len(xml_text),
                "lint": {"error_count": lint_report["error_count"], "warning_count": lint_report["warning_count"]},
                "unconfirmed_count": len(unconfirmed),
            },
        )
    except OSError:
        pass  # 日志落盘失败不阻断生成
    inherit_project_skills = payload.get("inherit_project_skills", True) is not False
    overrides = topic_skill_overrides(project, payload.get("skills", project.get("skills", [])), inherit_project_skills)
    return {
        "xml": xml_text,
        "validation": validation,
        "lint": lint_report,
        "usage": usage,
        "skills": skill_names,
        "skill_snapshot": skill_usage_snapshot(skill_names, project, overrides, inherit_project_skills),
        "model": model,
        "source": "ai",
        "generation_mode": generation_mode,
        "unconfirmed": unconfirmed,
        "material_slices": material_slices,
        "context_report": context_report,
        "context_summary": context_report_summary(context_report),
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
    project: dict[str, Any], payload: dict[str, Any], materials: list[dict[str, Any]], settings: dict[str, Any] | None = None
) -> tuple[str, str, list[str], list[dict[str, Any]]]:
    """Build the analysis prompt under a global context budget.

    Section priority: 素材 > Skill > 基线 > 语料。Returns
    (system, user, skill_names, context_report).
    """
    records = selected_skill_records(payload.get("skills") or project.get("skills", []))
    skill_names = [str(item["name"]) for item in records]
    sections: list[PromptSection] = []
    for skill in records:
        block = f"## Skill：{skill['name']}\n{skill.get('content', '')}"
        attachments = text_attachment_context(skill)
        if attachments:
            block += f"\n\n## Skill 附件上下文\n{attachments}"
        sections.append(PromptSection(f"skill:{skill.get('id', skill['name'])}", f"Skill：{skill['name']}", 2, block))
    empty_material_notes: list[str] = []
    for material in materials:
        text = str(material.get("extracted_text", "")).strip()
        status = str(material.get("extract_status", "unsupported"))
        message = str(material.get("extract_message", ""))
        if text:
            sections.append(
                PromptSection(
                    f"material:{material.get('id', '')}",
                    f"材料：{material.get('name', '未命名')}（提取状态：{status}）",
                    1,
                    text,
                )
            )
        else:
            empty_material_notes.append(
                f"### 材料：{material.get('name', '未命名')}\n- 提取状态：{status}\n- 处理说明：{message or '暂无可读取文本'}"
            )
    workspace_terms = workspace_query_terms(
        project.get("name"), project.get("product"), project.get("version"), payload.get("analysis_note")
    )
    workspace_context, _workspace_files = workspace_prompt_context(
        project,
        workspace_terms,
        limit=WORKSPACE_FRAMEWORK_FILES,
        per_file_chars=18_000,
        max_chars=90_000,
    )
    if workspace_context:
        sections.append(PromptSection("workspace", "工作区目录（生成时实时读取）", 1, workspace_context))
    corpus_context = project_corpus_context(project)
    if corpus_context:
        sections.append(PromptSection("corpus", "参考项目语料", 4, corpus_context))
    mode = normalize_project_mode(project.get("mode", "new"))
    mode_instruction = {
        "new": "从零梳理当前需求，输出全新文档框架。",
        "update": "结合复制进来的上版本框架和 Topic，识别新增、修改、废弃、未变化项，并在 topic_outline 中填写 change_status。",
        "optimize": "重点分析目标 Topic 的语言和结构问题，不因为优化表达而擅自改变业务范围。",
    }[mode]
    baseline_context = project_baseline_context(project) if mode != "new" else ""
    if baseline_context:
        sections.append(PromptSection("baseline", "当前项目基线", 3, baseline_context))
    sections, context_report = fit_prompt_sections(sections, context_char_budget(settings))

    skill_blocks = [section.text for section in sections if section.key.startswith("skill:") and section.text]
    material_blocks = [
        f"### {section.title}\n{section.text}" for section in sections if section.key.startswith("material:") and section.text
    ]
    material_context = "\n\n".join(material_blocks + empty_material_notes) or "（无可用材料文本。）"
    workspace_final = next((section.text for section in sections if section.key == "workspace"), "")
    corpus_final = next((section.text for section in sections if section.key == "corpus"), "")
    baseline_final = next((section.text for section in sections if section.key == "baseline"), "")
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
{chr(10).join(skill_blocks) or '（无可用 Skill 内容。）'}

## 原始材料提取内容
{material_context}

## 工作区目录（Agent 直接读取的本地文件）
{workspace_final or '当前项目未设置工作区目录。'}

## 当前项目基线（版本更新或 Topic 优化项目）
{baseline_final or '无当前项目基线。'}

## 参考项目实时语料库
仅作为结构、术语和写作风格参考，不得将参考项目中未被当前材料确认的事实当作当前项目结论。
{corpus_final or '暂无参考项目语料。'}

请保留证据来源，优先使用材料文件名作为 source_materials。只返回 JSON。"""
    return system, user, skill_names, context_report


def generate_requirements_analysis(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    project = read_json(project_dir(project_id) / "project.json", None)
    if not isinstance(project, dict):
        raise ValueError("项目不存在。")
    records = list_project_material_records(project_id)
    readable_records = [item for item in records if str(item.get("extracted_text", "")).strip()]
    if not readable_records and not workspace_has_readable(project_id, project):
        if records:
            raise ValueError("当前材料均未成功提取文本，且项目没有可读取的工作区目录。请补充材料，或把包含需求文档的目录设为工作区。")
        raise ValueError("请先上传至少一份需求材料，或在项目里设置工作区目录（生成时直接读取目录内容）。")
    settings = load_settings()
    system, user, skill_names, context_report = build_requirements_analysis_messages(project, payload, records, settings)

    def parse_analysis_result(raw_text: str) -> dict[str, Any]:
        try:
            parsed = json.loads(clean_ai_json(raw_text))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"AI 返回的需求分析不是有效 JSON：{str(exc)[:240]}") from exc
        return normalize_analysis_result(parsed)

    result, model = generate_with_repair(
        settings,
        system,
        user,
        parse_analysis_result,
        max_tokens=DEFAULT_ANALYSIS_MAX_TOKENS,
        json_mode=True,
    )
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
        "context_report": context_report,
        "context_summary": context_report_summary(context_report),
        **result,
    }
    with generation_commit():
        write_json(analysis_version_dir(project_id) / f"{analysis_id}.json", record)
        project["updated_at"] = created_at
        project["stage"] = "需求分析"
        write_json(project_dir(project_id) / "project.json", project)
    return analysis_record_summary(record)


def batch_generate_topics(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Server-side batch generation: one job iterates framework nodes.

    Nodes whose framework_node_key matches an existing Topic are regenerated in
    place (identity and history preserved); others create new Topics. A single
    item failure does not abort the run; cancellation stops before the next
    uncommitted item. Progress is published for the polling UI.
    """
    project = read_json(project_dir(project_id) / "project.json", None)
    if not isinstance(project, dict):
        raise ValueError("项目不存在。")
    raw_nodes = payload.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValueError("请提供至少一个待生成的框架节点。")
    common_raw = payload.get("common")
    common = common_raw if isinstance(common_raw, dict) else {}
    nodes: list[dict[str, Any]] = []
    for raw in raw_nodes[:200]:
        if not isinstance(raw, dict):
            continue
        title = sanitize_text(raw.get("title"))
        if not title:
            continue
        summary = sanitize_text(raw.get("chapter_summary", raw.get("summary")))
        nodes.append(
            {
                "title": title,
                "topic_type": str(raw.get("topic_type", "concept")),
                "shortdesc": sanitize_text(raw.get("shortdesc")) or summary or f"说明“{title}”相关内容。",
                "chapter_summary": summary,
                "brief": sanitize_text(raw.get("brief", summary)),
                "heading_level": topic_level(raw.get("heading_level", raw.get("level", 2))),
                "framework_node_key": sanitize_text(raw.get("framework_node_key")),
                "parent_title": sanitize_text(raw.get("parent_title")),
                "sibling_topics": raw.get("sibling_topics") if isinstance(raw.get("sibling_topics"), list) else [],
            }
        )
    if not nodes:
        raise ValueError("节点清单中没有有效的 Topic 标题。")
    common_fields = {
        "generation_prompt": sanitize_text(common.get("generation_prompt")),
        "skills": common.get("skills") if isinstance(common.get("skills"), list) else [],
        "inherit_project_skills": common.get("inherit_project_skills", True) is not False,
        "material_ids": parse_lines(common.get("material_ids")),
        "include_image_placeholder": bool(common.get("include_image_placeholder")),
        "include_ref_placeholder": bool(common.get("include_ref_placeholder")),
        "ai_generate": True,
    }
    existing = {
        str(topic.get("framework_node_key")): topic
        for topic in list_topics(project_id)
        if topic.get("framework_node_key")
    }
    items: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0
    total = len(nodes)
    for index, node in enumerate(nodes):
        check_job_cancelled()
        update_job_progress(index, total, node["title"])
        item_payload = {**common_fields, **node}
        try:
            current = existing.get(node["framework_node_key"]) if node["framework_node_key"] else None
            if current is not None:
                summary = regenerate_topic(project_id, str(current["id"]), item_payload)
                status = "updated"
            else:
                summary = create_topic(project_id, item_payload)
                status = "created"
            succeeded += 1
            items.append({"title": node["title"], "status": status, "topic_id": summary.get("id"), "error": None})
        except JobCancelled:
            raise
        except Exception as exc:  # single-item failure must not abort the batch
            failed += 1
            items.append({"title": node["title"], "status": "failed", "topic_id": None, "error": str(exc)[:300]})
        update_job_progress(index + 1, total, node["title"])
    return {"total": total, "succeeded": succeeded, "failed": failed, "items": items}


def batch_generate_topics_parallel(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """多 Agent 并行批量生成（借鉴 dsh-synapse 的并行会话思路）。

    N 个 worker 线程从共享队列领框架节点，每个 worker 绑定一个 Agent 档案
    （独立模型配置 + 独立 API Key，未配 Key 回退主 Key）。单节点失败不中断；
    取消立即生效（worker 线程各自设置 JOB_CONTEXT，取消/进度机制天然兼容）。
    进度含 completed_titles/failed_titles，供前端逐节点点亮状态。
    """
    if not isinstance(read_json(project_dir(project_id) / "project.json", None), dict):
        raise ValueError("项目不存在。")
    raw_nodes = payload.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValueError("请提供至少一个待生成的框架节点。")
    common_raw = payload.get("common")
    common = common_raw if isinstance(common_raw, dict) else {}
    nodes: list[dict[str, Any]] = []
    for raw in raw_nodes[:200]:
        if not isinstance(raw, dict):
            continue
        title = sanitize_text(raw.get("title"))
        if not title:
            continue
        summary = sanitize_text(raw.get("chapter_summary", raw.get("summary")))
        nodes.append(
            {
                "title": title,
                "topic_type": str(raw.get("topic_type", "concept")),
                "shortdesc": sanitize_text(raw.get("shortdesc")) or summary or f"说明“{title}”相关内容。",
                "chapter_summary": summary,
                "brief": sanitize_text(raw.get("brief", summary)),
                "heading_level": topic_level(raw.get("heading_level", raw.get("level", 2))),
                "framework_node_key": sanitize_text(raw.get("framework_node_key")),
                "parent_title": sanitize_text(raw.get("parent_title")),
                "sibling_topics": raw.get("sibling_topics") if isinstance(raw.get("sibling_topics"), list) else [],
            }
        )
    if not nodes:
        raise ValueError("节点清单中没有有效的 Topic 标题。")
    try:
        workers = int(payload.get("workers") or 2)
    except (TypeError, ValueError):
        workers = 2
    run_settings = load_settings()
    worker_cap = max_parallel_workers(run_settings)
    workers = max(1, min(workers, worker_cap))
    # 闸门跟着配置抬高，否则「并行上限 = 10」会被闸门悄悄压回 6。
    AI_REQUEST_GATE.allow(workers)
    chunk_size = batch_chunk_size(run_settings, payload.get("chunk_size"))
    profile_ids = [str(item).strip() for item in (payload.get("profile_ids") or []) if str(item).strip()]
    worker_settings: list[dict[str, Any]] = []
    for index in range(workers):
        profile_id = profile_ids[index % len(profile_ids)] if profile_ids else None
        if profile_id:
            merged = resolve_agent_profile_settings(profile_id)
            if merged is None:
                raise ValueError(f"Agent 档案不存在：{profile_id}")
            worker_settings.append(merged)
        else:
            worker_settings.append(load_settings())

    job_id = getattr(JOB_CONTEXT, "job_id", None)
    if not job_id:
        raise RuntimeError("并行批量生成必须在后台任务中执行。")

    common_fields = {
        "generation_prompt": sanitize_text(common.get("generation_prompt")),
        "skills": common.get("skills") if isinstance(common.get("skills"), list) else [],
        "inherit_project_skills": common.get("inherit_project_skills", True) is not False,
        "material_ids": parse_lines(common.get("material_ids")),
        "include_image_placeholder": bool(common.get("include_image_placeholder")),
        "include_ref_placeholder": bool(common.get("include_ref_placeholder")),
        "ai_generate": True,
    }
    existing = {
        str(topic.get("framework_node_key")): topic
        for topic in list_topics(project_id)
        if topic.get("framework_node_key")
    }
    # 每个波次用自己的队列；这里留一个空队列作为兜底，避免遗漏参数时静默空转。
    task_queue: queue.Queue = queue.Queue()
    results: list[dict[str, Any] | None] = [None] * len(nodes)
    state_lock = threading.Lock()
    shared: dict[str, Any] = {
        "done": 0,
        "completed_titles": [],
        "failed_titles": [],
        "running_titles": [],
        "completed_keys": [],
        "failed_keys": [],
        "running_keys": [],
    }

    def mark_running(node: dict[str, Any]) -> None:
        with state_lock:
            shared["running_titles"].append(node["title"])
            if node["framework_node_key"]:
                shared["running_keys"].append(node["framework_node_key"])

    def mark_finished(node: dict[str, Any], ok: bool) -> None:
        with state_lock:
            running_title = node["title"]
            if running_title in shared["running_titles"]:
                shared["running_titles"].remove(running_title)
            if node["framework_node_key"] and node["framework_node_key"] in shared["running_keys"]:
                shared["running_keys"].remove(node["framework_node_key"])
            shared["done"] += 1
            if ok:
                shared["completed_titles"].append(node["title"])
                if node["framework_node_key"]:
                    shared["completed_keys"].append(node["framework_node_key"])
            else:
                shared["failed_titles"].append(node["title"])
                if node["framework_node_key"]:
                    shared["failed_keys"].append(node["framework_node_key"])

    # 画布模式：每个 Agent 显式管一批节点（groups），否则沿用共享队列自动领任务。
    # 每个 group 可携带自己的 generation_prompt / skills / material_ids，
    # 值缺失（None）表示沿用 common，[] 则是“明确不要”。
    thread_specs: list[dict[str, Any]] = []
    tracked_total = len(nodes)
    groups_raw = payload.get("groups")
    if isinstance(groups_raw, list) and groups_raw:
        key_index = {
            str(node["framework_node_key"]): index
            for index, node in enumerate(nodes)
            if node["framework_node_key"]
        }
        title_index: dict[str, int] = {}
        for index, node in enumerate(nodes):
            title_index.setdefault(node["title"], index)
        assigned: set[int] = set()
        for raw_group in groups_raw[:worker_cap]:
            if not isinstance(raw_group, dict):
                continue
            raw_keys = raw_group.get("node_keys")
            raw_keys = raw_keys if isinstance(raw_keys, list) else []
            indexes: list[int] = []
            for raw_key in raw_keys:
                index = key_index.get(str(raw_key))
                if index is None:
                    index = title_index.get(str(raw_key))
                if index is not None and index not in assigned:
                    indexes.append(index)
                    assigned.add(index)
            if not indexes:
                continue
            profile_id = str(raw_group.get("profile_id") or "").strip()
            if profile_id:
                merged = resolve_agent_profile_settings(profile_id)
                if merged is None:
                    raise ValueError(f"Agent 档案不存在：{profile_id}")
            else:
                merged = load_settings()
            group_skills = raw_group.get("skills")
            thread_specs.append(
                {
                    "indexes": indexes,
                    "settings": merged,
                    "prompt": sanitize_text(raw_group.get("generation_prompt")),
                    "skills": [str(item).strip() for item in group_skills if str(item).strip()] if isinstance(group_skills, list) else None,
                    "inherit": None if "inherit_project_skills" not in raw_group else raw_group.get("inherit_project_skills") is not False,
                    "material_ids": parse_lines(raw_group.get("material_ids")) if "material_ids" in raw_group else None,
                }
            )
        # 画布模式下未分配给任何 Agent 的节点不生成：让画布上保持“未分配”，
        # 避免用户缩小 Agent 范围后，剩余章节被悄悄塞给最后一个 Agent。
        if not thread_specs:
            raise ValueError("画布未分配任何章节，请至少给一个 Agent 框选章节。")
        tracked_total = len(assigned)
    else:
        # 自动派发模式按波次切片：每波开始时按档案轮询生成 spec（见下方驱动循环）。
        thread_specs = []

    wave_state: dict[str, int] = {"index": 1, "total": 1}

    def publish_progress() -> None:
        with BACKGROUND_JOBS_LOCK:
            job = BACKGROUND_JOBS.get(job_id)
            if job is not None:
                titles = "、".join(shared["completed_titles"][-3:]) or "进行中"
                prefix = f"第 {wave_state['index']}/{wave_state['total']} 波 · " if wave_state["total"] > 1 else ""
                job["progress"] = {
                    "done": shared["done"],
                    "total": tracked_total,
                    "detail": prefix + titles,
                    "completed_titles": list(shared["completed_titles"]),
                    "failed_titles": list(shared["failed_titles"]),
                    "running_titles": list(shared["running_titles"]),
                    "completed_keys": list(shared["completed_keys"]),
                    "failed_keys": list(shared["failed_keys"]),
                    "running_keys": list(shared["running_keys"]),
                    "updated_at": now_iso(),
                }

    def worker(spec: dict[str, Any], work_queue: "queue.Queue | None" = None) -> None:
        JOB_CONTEXT.job_id = job_id
        # 子 Agent 档案配置在本线程内生效：模型 / 地址 / Key 都走档案，
        # 生成记录里的 model 也会记成该 Agent 的模型，便于回溯是哪一路产出的。
        SETTINGS_CONTEXT.settings = spec.get("settings")
        indexes = spec.get("indexes")
        group_prompt = spec.get("prompt") or ""
        cursor = 0
        while True:
            if indexes is None:
                try:
                    index, node = (work_queue or task_queue).get_nowait()
                except queue.Empty:
                    return
            else:
                if cursor >= len(indexes):
                    return
                index = indexes[cursor]
                cursor += 1
                node = nodes[index]
            item_payload = {**common_fields, **node}
            # Agent 级覆盖：prompt / Skill / 素材，未设置则沿用 common
            if group_prompt:
                item_payload["generation_prompt"] = group_prompt
            if spec.get("skills") is not None:
                item_payload["skills"] = spec["skills"]
            if spec.get("inherit") is not None:
                item_payload["inherit_project_skills"] = spec["inherit"]
            if spec.get("material_ids") is not None:
                item_payload["material_ids"] = spec["material_ids"]
            mark_running(node)
            try:
                check_job_cancelled()
                current = existing.get(node["framework_node_key"]) if node["framework_node_key"] else None
                if current is not None:
                    summary = regenerate_topic(project_id, str(current["id"]), item_payload)
                    status = "updated"
                else:
                    summary = create_topic(project_id, item_payload)
                    status = "created"
                results[index] = {"title": node["title"], "status": status, "topic_id": summary.get("id"), "error": None, "framework_node_key": node["framework_node_key"]}
                mark_finished(node, True)
            except JobCancelled:
                results[index] = {"title": node["title"], "status": "cancelled", "topic_id": None, "error": "已取消", "framework_node_key": node["framework_node_key"]}
                mark_finished(node, False)
                publish_progress()
                return
            except Exception as exc:  # 单节点失败不中断批次
                results[index] = {"title": node["title"], "status": "failed", "topic_id": None, "error": str(exc)[:300], "framework_node_key": node["framework_node_key"]}
                mark_finished(node, False)
            publish_progress()

    def run_wave(specs: list[dict[str, Any]], work_queue: "queue.Queue | None" = None) -> None:
        threads = [threading.Thread(target=worker, args=(spec, work_queue), daemon=True) for spec in specs]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    if thread_specs:
        # 画布模式：每个 Agent 框选的章节是固定分组，一次跑完即可。
        run_wave(thread_specs)
    else:
        # 自动派发模式：按 chunk_size 切片，一波落盘后再开下一波。
        # 中断时已完成的部分都在磁盘上；也避免长时间持续打满限流。
        total = len(nodes)
        wave_count = (total + chunk_size - 1) // chunk_size
        wave_state["total"] = wave_count
        for wave in range(wave_count):
            if wave:
                check_job_cancelled()
            wave_state["index"] = wave + 1
            start = wave * chunk_size
            wave_indexes = list(range(start, min(total, start + chunk_size)))
            work_queue: queue.Queue = queue.Queue()
            for index in wave_indexes:
                work_queue.put((index, nodes[index]))
            specs = [
                {
                    "indexes": None,
                    "settings": worker_settings[position % len(worker_settings)],
                    "prompt": "",
                    "skills": None,
                    "inherit": None,
                    "material_ids": None,
                }
                for position in range(min(workers, len(wave_indexes)))
            ]
            run_wave(specs, work_queue)
            publish_progress()
            if wave < wave_count - 1:
                time.sleep(0.4)
    check_job_cancelled()
    items = [item or {"title": nodes[index]["title"], "status": "skipped", "topic_id": None, "error": None, "framework_node_key": nodes[index]["framework_node_key"]} for index, item in enumerate(results)]
    succeeded = sum(1 for item in items if item["status"] in {"created", "updated"})
    failed = sum(1 for item in items if item["status"] in {"failed", "cancelled"})
    return {"total": tracked_total, "succeeded": succeeded, "failed": failed, "items": items}


def check_topic_consistency(project_id: str) -> dict[str, Any]:
    """Lightweight cross-Topic checks: duplicates, link collisions, GUID residue."""
    project = read_json(project_dir(project_id) / "project.json", None)
    if not isinstance(project, dict):
        raise ValueError("项目不存在。")
    topics = list_topics(project_id)
    by_title: dict[str, list[str]] = {}
    by_node_key: dict[str, list[str]] = {}
    guid_residue: list[dict[str, str]] = []
    missing_node_key: list[str] = []
    confirm_total = 0
    unconfirmed_total = 0
    for topic in topics:
        topic_id = str(topic.get("id", ""))
        title = str(topic.get("title", ""))
        by_title.setdefault(title, []).append(topic_id)
        node_key = str(topic.get("framework_node_key") or "")
        if node_key:
            by_node_key.setdefault(node_key, []).append(topic_id)
        else:
            missing_node_key.append(topic_id)
        if GUID_PATTERN.search(str(topic.get("xml", ""))):
            guid_residue.append({"topic_id": topic_id, "title": title})
        confirm_total += int((topic.get("validation") or {}).get("confirm_count", 0) or 0)
        unconfirmed_total += len(topic.get("unconfirmed") or [])
    return {
        "project_id": project_id,
        "topic_count": len(topics),
        "duplicate_titles": [
            {"title": title, "topic_ids": ids} for title, ids in by_title.items() if len(ids) > 1
        ],
        "duplicate_node_keys": [
            {"framework_node_key": key, "topic_ids": ids} for key, ids in by_node_key.items() if len(ids) > 1
        ],
        "missing_node_key": missing_node_key,
        "guid_residue": guid_residue,
        "todo_confirm_total": confirm_total,
        "unconfirmed_total": unconfirmed_total,
        "checked_at": now_iso(),
    }


# =========================================================================
# 风格 lint 引擎（修复清单 4.2）：把 Skill 中机器可查规则代码化，0 token 检查。
# =========================================================================

LINT_SENTENCE_SPLIT = re.compile(r"[。！？!?；;]+")
LINT_CJK = re.compile(r"[\u4e00-\u9fff]")
LINT_HALF_WIDTH_ADJACENT_CJK = re.compile(r"[\u4e00-\u9fff][,;:?!()；]|[,;:?!()][\u4e00-\u9fff]")
LINT_NUMBER_UNIT = re.compile(r"\d(?:GB|MB|KB|TB|ms|GHz|MHz|kHz|Hz|inch|px|pt)\b")
LINT_MAX_PER_RULE = 8
# DITA 中这些块级容器内的文字必须包在 <p> 里，不允许裸文本。
LINT_BLOCK_PARENTS = {"conbody", "context", "prereq", "result", "postreq", "refsyn", "section", "stepsresult"}

LINT_RULE_LABELS: dict[str, tuple[str, str]] = {
    "root-tag": ("error", "根标签与 Topic 类型不符"),
    "task-step-count": ("error", "Task 步骤数少于 2，操作指导类 Topic 应至少包含两个步骤"),
    "shortdesc-length": ("warning", "shortdesc 超过 3 句，规范要求控制在 3 句以内"),
    "shortdesc-media": ("error", "shortdesc 中包含 image/xref 引用，规范禁止"),
    "concept-conbody": ("error", "concept 缺少 <conbody> 主体容器"),
    "block-text-in-p": ("error", "块级容器内存在未包在 <p> 中的裸文字"),
    "word-click": ("warning", "正文使用「点击」，HIK 规范用词为「单击」"),
    "halfwidth-punct": ("warning", "中文语句中出现半角标点，应使用全角标点"),
    "sentence-length": ("warning", "存在超过 40 字的长句，建议拆分"),
    "number-unit": ("warning", "数字与英文单位之间缺少空格（如 10GB 应为 10 GB）"),
    "placeholder-residue": ("warning", "残留占位符，需人工处理后发布"),
}


def _lint_summary(issues: list[dict[str, Any]]) -> dict[str, Any]:
    error_count = sum(1 for item in issues if item["severity"] == "error")
    warning_count = sum(1 for item in issues if item["severity"] == "warning")
    return {
        "ok": error_count == 0,
        "error_count": error_count,
        "warning_count": warning_count,
        "issues": issues,
    }


def lint_topic_xml(xml_text: str, topic_type: str = "") -> dict[str, Any]:
    """Rule-based style lint for a rendered Topic XML. Returns aggregated issues.

    每条 issue 聚合同一规则的多次命中（count + 首个样例），避免刷屏。
    """
    raw_hits: dict[str, dict[str, Any]] = {}

    def note(rule: str, detail: str) -> None:
        entry = raw_hits.setdefault(rule, {"count": 0, "samples": []})
        entry["count"] += 1
        if len(entry["samples"]) < 3 and detail:
            entry["samples"].append(detail)

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return _lint_summary(
            [{"rule": "xml-parse", "severity": "error", "message": f"XML 不可解析，跳过风格检查：{exc}", "count": 1, "samples": []}]
        )

    if topic_type in {"task", "concept"} and root.tag != topic_type:
        note("root-tag", f"实际为 <{root.tag}>，预期 <{topic_type}>")

    if root.tag == "task":
        step_count = len(root.findall(".//step"))
        if step_count < 2:
            note("task-step-count", f"当前步骤数：{step_count}")

    shortdesc = root.find("shortdesc")
    if shortdesc is None:
        shortdesc = root.find(".//shortdesc")
    if shortdesc is not None:
        text = "".join(shortdesc.itertext())
        sentences = [s for s in LINT_SENTENCE_SPLIT.split(text) if s.strip()]
        if len(sentences) > 3:
            note("shortdesc-length", f"当前 {len(sentences)} 句：「{text[:40]}…」")
        if shortdesc.find(".//image") is not None or shortdesc.find(".//xref") is not None:
            note("shortdesc-media", "shortdesc 内含 image 或 xref")

    if root.tag == "concept" and root.find("conbody") is None:
        note("concept-conbody", "根元素下未找到 <conbody>")

    for elem in root.iter():
        if elem.tag in LINT_BLOCK_PARENTS:
            direct_text = (elem.text or "").strip()
            if direct_text:
                note("block-text-in-p", f"<{elem.tag}>：「{direct_text[:36]}」")

    def iter_texts(elem: ET.Element):
        if elem.text and elem.text.strip():
            yield elem.text
        for child in elem:
            if child.tail and child.tail.strip():
                yield child.tail
            yield from iter_texts(child)

    for text in iter_texts(root):
        if not LINT_CJK.search(text):
            continue
        stripped = text.strip()
        if "点击" in stripped:
            note("word-click", f"「{stripped[:36]}」")
        if LINT_HALF_WIDTH_ADJACENT_CJK.search(stripped):
            note("halfwidth-punct", f"「{stripped[:36]}」")
        for sentence in LINT_SENTENCE_SPLIT.split(stripped):
            sentence = sentence.strip()
            if len(sentence) > 40:
                note("sentence-length", f"{len(sentence)} 字：「{sentence[:36]}…」")
        match = LINT_NUMBER_UNIT.search(stripped)
        if match:
            note("number-unit", f"「{match.group(0)}」")

    residue = 0
    residue += len(re.findall(r"TODO_IMAGE|TODO_REF", xml_text))
    residue += len(re.findall(r"TODO_CONFIRM", xml_text))
    if residue:
        note("placeholder-residue", f"共 {residue} 个占位符")

    issues: list[dict[str, Any]] = []
    for rule, entry in raw_hits.items():
        severity, label = LINT_RULE_LABELS.get(rule, ("warning", rule))
        if entry["count"] > LINT_MAX_PER_RULE:
            message = f"{label}（共 {entry['count']} 处，仅列出前几处）"
        else:
            message = f"{label}（{entry['count']} 处）"
        issues.append(
            {
                "rule": rule,
                "severity": severity,
                "message": message,
                "count": entry["count"],
                "samples": entry["samples"],
            }
        )
    severity_order = {"error": 0, "warning": 1}
    issues.sort(key=lambda item: (severity_order.get(item["severity"], 2), -item["count"]))
    return _lint_summary(issues)


def check_project_lint(project_id: str) -> dict[str, Any]:
    """Run the style lint over every stored Topic of a project."""
    if not isinstance(read_json(project_dir(project_id) / "project.json", None), dict):
        raise ValueError("项目不存在。")
    results: list[dict[str, Any]] = []
    for topic in list_topics(project_id):
        report = lint_topic_xml(str(topic.get("xml", "")), str(topic.get("topic_type", "")))
        results.append(
            {
                "topic_id": topic.get("id"),
                "title": topic.get("title"),
                "topic_type": topic.get("topic_type"),
                "lint": report,
            }
        )
    error_topics = sum(1 for item in results if item["lint"]["error_count"])
    warning_topics = sum(1 for item in results if item["lint"]["warning_count"])
    total_errors = sum(item["lint"]["error_count"] for item in results)
    total_warnings = sum(item["lint"]["warning_count"] for item in results)
    return {
        "project_id": project_id,
        "topic_count": len(results),
        "results": results,
        "error_topic_count": error_topics,
        "warning_topic_count": warning_topics,
        "total_errors": total_errors,
        "total_warnings": total_warnings,
        "ok": total_errors == 0,
        "checked_at": now_iso(),
    }


# =========================================================================
# 生成记录（修复清单 4.5）：每次 AI 生成落盘黑匣子，可复现、可统计。
# =========================================================================

GENERATION_LOG_DIR = DATA_DIR / "generation_logs"
GENERATION_LOG_KEEP = 200


def _sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _skill_content_hashes(skill_names: list[str]) -> dict[str, str]:
    listed = {str(item.get("name", "")): item for item in list_skills()}
    hashes: dict[str, str] = {}
    for name in skill_names:
        content = str((listed.get(name) or {}).get("content", ""))
        hashes[name] = _sha16(content)
    return hashes


def record_generation_log(project_id: str, record: dict[str, Any]) -> None:
    directory = GENERATION_LOG_DIR / project_id
    directory.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
    payload = {"schema_version": 1, **record, "logged_at": now_iso()}
    write_json(directory / f"{stamp}.json", payload)
    files = sorted(directory.glob("*.json"))
    for path in files[:-GENERATION_LOG_KEEP]:
        try:
            path.unlink()
        except OSError:
            pass


def list_generation_logs(project_id: str) -> dict[str, Any]:
    directory = GENERATION_LOG_DIR / project_id
    entries: list[dict[str, Any]] = []
    if directory.exists():
        for path in sorted(directory.glob("*.json"), reverse=True):
            data = read_json(path, None)
            if not isinstance(data, dict):
                continue
            lint = data.get("lint") or {}
            entries.append(
                {
                    "id": path.stem,
                    "operation": data.get("operation"),
                    "topic_type": data.get("topic_type"),
                    "generation_mode": data.get("generation_mode"),
                    "provider": data.get("provider"),
                    "model": data.get("model"),
                    "prompt_chars": data.get("prompt_chars"),
                    "attempts": data.get("attempts"),
                    "usage": data.get("usage"),
                    "lint_error_count": int(lint.get("error_count", 0) or 0),
                    "lint_warning_count": int(lint.get("warning_count", 0) or 0),
                    "unconfirmed_count": data.get("unconfirmed_count"),
                    "logged_at": data.get("logged_at"),
                }
            )
    totals = {
        "input_tokens": sum(int((entry.get("usage") or {}).get("input_tokens", 0) or 0) for entry in entries),
        "output_tokens": sum(int((entry.get("usage") or {}).get("output_tokens", 0) or 0) for entry in entries),
    }
    return {
        "project_id": project_id,
        "total_calls": len(entries),
        "totals": totals,
        "entries": entries[:100],
    }


# =========================================================================
# 回归集（修复清单 4.4）：基准捕获 + 结构指纹，为改 prompt/换模型提供度量。
# =========================================================================

REGRESSION_DIR = DATA_DIR / "regression"


def topic_structure_fingerprint(xml_text: str) -> dict[str, Any]:
    """结构指纹：根标签、章节标题序列、步骤数、标签轮廓。用于生成结果对比。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return {"ok": False, "error": f"XML 不可解析：{exc}"}

    def tag_outline(elem: ET.Element, depth: int = 0) -> Any:
        if depth >= 4:
            return elem.tag
        return {"tag": elem.tag, "children": [tag_outline(child, depth + 1) for child in list(elem)]}

    shortdesc_text = ""
    shortdesc = root.find("shortdesc")
    if shortdesc is None:
        shortdesc = root.find(".//shortdesc")
    if shortdesc is not None:
        shortdesc_text = "".join(shortdesc.itertext())
    sentences = [s for s in LINT_SENTENCE_SPLIT.split(shortdesc_text) if s.strip()]
    return {
        "ok": True,
        "root": root.tag,
        "title": (root.findtext("title") or "").strip(),
        "shortdesc_sentence_count": len(sentences),
        "section_titles": [(s.findtext("title") or "").strip() for s in root.findall(".//section")],
        "step_count": len(root.findall(".//step")),
        "prereq_present": root.find(".//prereq") is not None,
        "result_present": root.find(".//result") is not None,
        "tag_outline": tag_outline(root),
    }


def _fingerprint_paths(value: Any, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        tag = str(value.get("tag", ""))
        path = f"{prefix}/{tag}"
        paths.append(path)
        for child in value.get("children", []):
            paths.extend(_fingerprint_paths(child, path))
    elif isinstance(value, str):
        paths.append(f"{prefix}/{value}")
    return paths


def fingerprint_similarity(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """对比两个结构指纹：标签轮廓 Jaccard 相似度 + 关键计数差异。"""
    if not baseline.get("ok") or not candidate.get("ok"):
        return {"ok": False, "reason": "指纹不可用（XML 解析失败）"}
    base_paths = set(_fingerprint_paths(baseline.get("tag_outline")))
    cand_paths = set(_fingerprint_paths(candidate.get("tag_outline")))
    union = base_paths | cand_paths
    jaccard = len(base_paths & cand_paths) / len(union) if union else 1.0
    differences: list[str] = []
    if baseline.get("root") != candidate.get("root"):
        differences.append(f"根标签：{baseline.get('root')} → {candidate.get('root')}")
    if baseline.get("section_titles") != candidate.get("section_titles"):
        differences.append(f"章节标题：{baseline.get('section_titles')} → {candidate.get('section_titles')}")
    if baseline.get("step_count") != candidate.get("step_count"):
        differences.append(f"步骤数：{baseline.get('step_count')} → {candidate.get('step_count')}")
    if baseline.get("shortdesc_sentence_count") != candidate.get("shortdesc_sentence_count"):
        differences.append(
            f"shortdesc 句数：{baseline.get('shortdesc_sentence_count')} → {candidate.get('shortdesc_sentence_count')}"
        )
    if baseline.get("prereq_present") != candidate.get("prereq_present"):
        differences.append("prereq 有无变化")
    if baseline.get("result_present") != candidate.get("result_present"):
        differences.append("result 有无变化")
    return {
        "ok": True,
        "tag_jaccard": round(jaccard, 4),
        "differences": differences,
    }


def capture_regression_case(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """把当前项目的全部 Topic（含生成输入与 XML）捕获为一个回归基准用例。"""
    project_path = project_dir(project_id) / "project.json"
    project = read_json(project_path, None)
    if not isinstance(project, dict):
        raise ValueError("项目不存在。")
    settings = load_settings()
    topics: list[dict[str, Any]] = []
    directory = topics_dir(project_id)
    if directory.exists():
        for path in sorted(directory.iterdir()):
            metadata = path / "topic.json"
            if not (path.is_dir() and metadata.exists()):
                continue
            topic = read_json(metadata, None)
            if not isinstance(topic, dict) or not topic.get("id"):
                continue
            payload_snapshot = {
                "topic_type": topic.get("topic_type", "concept"),
                "title": topic.get("title", ""),
                "shortdesc": topic.get("shortdesc", ""),
                "brief": topic.get("brief", ""),
                "chapter_summary": topic.get("chapter_summary", ""),
                "generation_prompt": topic.get("generation_prompt", ""),
                "outline": topic.get("outline", []),
                "prerequisites": topic.get("prerequisites", []),
                "steps": topic.get("steps", []),
                "skills": topic.get("skills", []),
                "inherit_project_skills": topic.get("inherit_project_skills", True),
                "material_ids": topic.get("material_ids", []),
                "framework_node_key": topic.get("framework_node_key", ""),
                "heading_level": topic.get("heading_level", 1),
            }
            topics.append(
                {
                    "topic_id": topic.get("id"),
                    "payload": payload_snapshot,
                    "baseline_xml": str(topic.get("xml", "")),
                    "baseline_fingerprint": topic_structure_fingerprint(str(topic.get("xml", ""))),
                    "baseline_lint": lint_topic_xml(str(topic.get("xml", "")), str(topic.get("topic_type", ""))),
                }
            )
    case_id = f"case_{int(time.time())}_{secrets.token_hex(2)}"
    case = {
        "schema_version": 1,
        "id": case_id,
        "name": sanitize_text(payload.get("name")) or f"{project.get('name', '未命名项目')} 基准",
        "source_project_id": project_id,
        "created_at": now_iso(),
        "settings_snapshot": {
            "provider": settings.get("provider"),
            "model": settings.get("model"),
            "structured_output": bool(settings.get("structured_output", True)),
        },
        "topic_count": len(topics),
        "topics": topics,
    }
    REGRESSION_DIR.mkdir(parents=True, exist_ok=True)
    write_json(REGRESSION_DIR / f"{case_id}.json", case)
    return {"case_id": case_id, "name": case["name"], "topic_count": len(topics), "created_at": case["created_at"]}


def list_regression_cases(project_id: str | None = None) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    if REGRESSION_DIR.exists():
        for path in sorted(REGRESSION_DIR.glob("case_*.json"), reverse=True):
            data = read_json(path, None)
            if not isinstance(data, dict):
                continue
            if project_id and data.get("source_project_id") != project_id:
                continue
            cases.append(
                {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "source_project_id": data.get("source_project_id"),
                    "topic_count": data.get("topic_count"),
                    "created_at": data.get("created_at"),
                }
            )
    return {"cases": cases}


def enqueue_project_generation(operation: str, project_id: str, callback) -> dict[str, Any]:
    if not isinstance(read_json(project_dir(project_id) / "project.json", None), dict):
        raise ValueError("项目不存在。")
    job_id = start_background_job(operation, callback)
    return {"job_id": job_id, "status": "queued", "operation": operation}


class AppHandler(BaseHTTPRequestHandler):
    server_version = "LianJinLu/2.1.0"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{now_iso()}] {format % args}")

    def send_json(self, status: int, payload: Any) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
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
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
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
                self.send_json(200, {"ok": True, "app": "炼金炉", "version": "2.1.0"})
            elif path.startswith("/api/jobs/"):
                job_id = unquote(path.removeprefix("/api/jobs/").strip("/"))
                job = get_background_job(job_id)
                self.send_json(200 if job else 404, job or {"error": "生成任务不存在。"})
            elif path == "/api/assets":
                self.send_json(200, {"assets": list_editorial_assets()})
            elif path == "/api/settings":
                self.send_json(200, public_settings())
            elif path == "/api/agent-profiles":
                self.send_json(200, {"profiles": [agent_profile_public(item) for item in load_settings().get("agent_profiles", [])]})
            elif path == "/api/skills":
                self.send_json(200, {"skills": list_skills()})
            elif path == "/api/fs/scan-directory":
                query = parse_qs(urlparse(self.path).query)
                raw_path = (query.get("path") or [""])[0]
                recursive = (query.get("recursive") or ["1"])[0] not in {"0", "false", "no"}
                self.send_json(200, scan_directory_files(raw_path, recursive))
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
                    source_path: Path | None = None
                    if isinstance(cover, dict):
                        stored_cover = project_dir(project_id) / Path(str(cover.get("file", ""))).name
                        source_file = Path(str(cover.get("source_file", ""))).name
                        if cover.get("type") == "asset" and source_file in {asset["file"] for asset in list_editorial_assets()}:
                            source_path = EDITORIAL_DIR / source_file
                        elif stored_cover.exists() and stored_cover.is_file():
                            source_path = stored_cover
                    if source_path is None:
                        self.send_error(404)
                        return
                    query = parse_qs(urlparse(self.path).query)
                    want_thumb = str((query.get("thumb") or ["0"])[0]).lower() in {"1", "true", "yes"}
                    if want_thumb:
                        thumb = cover_thumbnail(project_dir(project_id), source_path)
                        if thumb is not None:
                            self.send_file(thumb, image_content_type(thumb))
                            return
                    self.send_file(source_path, image_content_type(source_path))
                elif len(parts) == 2 and parts[1] == "materials":
                    self.send_json(200, {"materials": list_project_materials(project_id)})
                elif len(parts) == 2 and parts[1] == "workspace":
                    query = parse_qs(urlparse(self.path).query)
                    refresh = str((query.get("refresh") or ["0"])[0]).lower() in {"1", "true", "yes"}
                    self.send_json(200, workspace_state(project_id, refresh=refresh))
                elif len(parts) == 3 and parts[1] == "workspace" and parts[2] == "file":
                    query = parse_qs(urlparse(self.path).query)
                    relative = str((query.get("relative") or [""])[0])
                    if not relative:
                        raise ValueError("请提供要预览的文件相对路径。")
                    self.send_json(200, preview_workspace_file(project_id, relative))
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
                elif len(parts) == 4 and parts[1] == "framework" and parts[2] == "versions":
                    version_id = Path(parts[3]).name
                    record = read_json(framework_version_dir(project_id) / f"{version_id}.json", None)
                    self.send_json(200 if isinstance(record, dict) else 404, framework_record_summary(record) if isinstance(record, dict) else {"error": "框架版本不存在。"})
                elif len(parts) == 3 and parts[1] == "analysis":
                    record = read_json(analysis_version_dir(project_id) / f"{Path(parts[2]).name}.json", None)
                    self.send_json(200 if isinstance(record, dict) else 404, analysis_record_summary(record) if isinstance(record, dict) else {"error": "分析记录不存在。"})
                elif len(parts) == 2 and parts[1] == "unconfirmed":
                    self.send_json(200, list_project_unconfirmed(project_id))
                elif len(parts) == 2 and parts[1] == "consistency":
                    self.send_json(200, check_topic_consistency(project_id))
                elif len(parts) == 2 and parts[1] == "lint":
                    self.send_json(200, check_project_lint(project_id))
                elif len(parts) == 2 and parts[1] == "generation-logs":
                    self.send_json(200, list_generation_logs(project_id))
                elif len(parts) == 2 and parts[1] == "regression":
                    self.send_json(200, list_regression_cases(project_id))
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
            elif path.startswith("/api/jobs/") and path.endswith("/cancel"):
                job_id = unquote(path.removeprefix("/api/jobs/").removesuffix("/cancel").strip("/"))
                self.send_json(200, {"ok": cancel_background_job(job_id)})
            elif path == "/api/skills":
                self.send_json(201, create_skill(self.read_body()))
            elif path.startswith("/api/projects/") and path.endswith("/workspace"):
                project_id = unquote(path.removeprefix("/api/projects/").removesuffix("/workspace").strip("/"))
                self.send_json(200, save_project_workspace(project_id, self.read_body()))
            elif path.startswith("/api/projects/") and path.endswith("/workspace/refresh"):
                project_id = unquote(path.removeprefix("/api/projects/").removesuffix("/workspace/refresh").strip("/"))
                self.send_json(200, workspace_state(project_id, refresh=True))
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
            elif path.startswith("/api/projects/") and path.endswith("/framework/generate-async"):
                project_id = unquote(path.removeprefix("/api/projects/").removesuffix("/framework/generate-async").strip("/"))
                payload = self.read_body()
                self.send_json(202, enqueue_project_generation("framework", project_id, lambda: generate_framework(project_id, payload)))
            elif path.startswith("/api/projects/") and path.endswith("/topics/batch-generate-async"):
                project_id = unquote(path.removeprefix("/api/projects/").removesuffix("/topics/batch-generate-async").strip("/"))
                payload = self.read_body()
                self.send_json(202, enqueue_project_generation("batch-topics", project_id, lambda: batch_generate_topics(project_id, payload)))
            elif path.startswith("/api/projects/") and path.endswith("/topics/batch-generate-parallel-async"):
                project_id = unquote(path.removeprefix("/api/projects/").removesuffix("/topics/batch-generate-parallel-async").strip("/"))
                payload = self.read_body()
                self.send_json(202, enqueue_project_generation("batch-topics-parallel", project_id, lambda: batch_generate_topics_parallel(project_id, payload)))
            elif path.startswith("/api/agent-profiles/"):
                raw = unquote(path.removeprefix("/api/agent-profiles/").strip("/"))
                parts = raw.split("/")
                profile_id = parts[0] if parts else ""
                action = parts[1] if len(parts) > 1 else ""
                if action == "key":
                    body = self.read_body()
                    self.send_json(200, save_agent_profile_key(profile_id, str(body.get("api_key", ""))))
                elif action == "copy-account-key":
                    self.read_body()
                    self.send_json(200, copy_account_key_to_profile(profile_id))
                elif action == "delete":
                    self.send_json(200, delete_agent_profile(profile_id))
                elif action == "test":
                    merged = resolve_agent_profile_settings(profile_id)
                    if merged is None:
                        raise ValueError("Agent 档案不存在。")
                    try:
                        result = test_ai_connection(merged)
                    except Exception as exc:
                        record_agent_profile_test(profile_id, False, str(exc))
                        raise
                    record_agent_profile_test(profile_id, True, "")
                    self.send_json(200, result)
                else:
                    self.send_json(404, {"error": "接口不存在。"})
            elif path == "/api/agent-profiles":
                self.send_json(201, save_agent_profile(self.read_body()))
            elif path.startswith("/api/projects/") and path.endswith("/topics/generate-async"):
                project_id = unquote(path.removeprefix("/api/projects/").removesuffix("/topics/generate-async").strip("/"))
                payload = self.read_body()
                self.send_json(202, enqueue_project_generation("topic", project_id, lambda: create_topic(project_id, payload)))
            elif path.startswith("/api/projects/") and path.endswith("/generate-async") and "/topics/" in path:
                raw = path.removeprefix("/api/projects/").split("/topics/", 1)
                project_id = unquote(raw[0])
                topic_id = unquote(raw[1].removesuffix("/generate-async").strip("/"))
                payload = self.read_body()
                self.send_json(202, enqueue_project_generation("topic", project_id, lambda: regenerate_topic(project_id, topic_id, payload)))
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
            elif path.startswith("/api/projects/") and path.endswith("/analysis-async"):
                project_id = unquote(path.removeprefix("/api/projects/").removesuffix("/analysis-async").strip("/"))
                payload = self.read_body()
                self.send_json(202, enqueue_project_generation("analysis", project_id, lambda: generate_requirements_analysis(project_id, payload)))
            elif path.startswith("/api/projects/") and path.endswith("/topics"):
                project_id = unquote(path.removeprefix("/api/projects/").removesuffix("/topics").strip("/"))
                self.send_json(201, create_topic(project_id, self.read_body()))
            elif path.startswith("/api/projects/") and path.endswith("/regression/capture"):
                project_id = unquote(path.removeprefix("/api/projects/").removesuffix("/regression/capture").strip("/"))
                self.send_json(201, capture_regression_case(project_id, self.read_body()))
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
                if len(parts) == 1:
                    delete_project(parts[0])
                    self.send_json(200, {"ok": True})
                elif len(parts) == 3 and parts[1] == "materials":
                    delete_project_material(parts[0], parts[2])
                    self.send_json(200, {"ok": True})
                elif len(parts) == 2 and parts[1] == "workspace":
                    self.send_json(200, clear_project_workspace(parts[0]))
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


def create_server() -> ThreadingHTTPServer:
    """初始化数据目录并启动 HTTP 服务，供命令行与独立窗口两种入口复用。"""
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
    return server


def main() -> None:
    server = create_server()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n炼金炉已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Validate generated HIK XML output for Stage 0 constraints.

The validator intentionally does not validate the complete DITA/KC schema yet.
It checks XML well-formedness, forbidden GUID tokens, and unresolved placeholders.
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


GUID_PATTERN = re.compile(r"GUID(?:-|=)[A-Z0-9-]+", re.IGNORECASE)
PLACEHOLDER_PATTERN = re.compile(r"\bTODO_(?:IMAGE|REF)\b")


def iter_xml_files(target: Path):
    if target.is_file():
        yield target
        return
    yield from sorted(target.rglob("*.xml"))


def validate_file(path: Path, release: bool) -> tuple[bool, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    raw = path.read_text(encoding="utf-8-sig", errors="replace")

    try:
        ET.fromstring(raw)
    except ET.ParseError as exc:
        errors.append(f"XML 不可解析：{exc}")

    guid_matches = GUID_PATTERN.findall(raw)
    if guid_matches:
        errors.append(f"发现禁止的 GUID Token：{len(guid_matches)} 个")

    placeholder_matches = PLACEHOLDER_PATTERN.findall(raw)
    if placeholder_matches:
        message = f"发现待人工替换占位符：{len(placeholder_matches)} 个"
        if release:
            errors.append(message)
        else:
            warnings.append(message)

    return not errors, errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 HIK XML 生成结果")
    parser.add_argument("target", type=Path, help="XML 文件或包含 XML 的目录")
    parser.add_argument(
        "--release",
        action="store_true",
        help="发布模式：TODO_IMAGE/TODO_REF 也视为错误",
    )
    args = parser.parse_args()

    files = list(iter_xml_files(args.target))
    if not files:
        print("未找到 XML 文件", file=sys.stderr)
        return 2

    failed = 0
    for path in files:
        ok, errors, warnings = validate_file(path, args.release)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {path}")
        for item in errors:
            print(f"  ERROR: {item}")
        for item in warnings:
            print(f"  WARN: {item}")
        if not ok:
            failed += 1

    print(f"\n总计：{len(files)} 个，失败：{failed} 个")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

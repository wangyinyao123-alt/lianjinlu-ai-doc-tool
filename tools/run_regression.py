#!/usr/bin/env python3
"""回归集对比脚本（修复清单 4.4）。

用法：
    python3 tools/run_regression.py --list              # 列出所有基准用例
    python3 tools/run_regression.py --offline           # 只对基准做 lint + 指纹统计，不调 AI
    python3 tools/run_regression.py --case case_xxx     # 对指定用例重新生成并对比
    python3 tools/run_regression.py --case case_xxx --topic <topic_id>  # 只跑一个 Topic

在线模式会对基准中每个 Topic 用当前 AI 配置重新生成，对比：
- 结构指纹（根标签/章节标题/步骤数/shortdesc 句数）差异与标签轮廓 Jaccard 相似度；
- 风格 lint 通过率（基线 vs 新生成）。
报告写入 data/regression/reports/<case_id>-<时间戳>.md（同名 .json）。

注意：在线模式使用 data/settings.json 的当前 AI 配置与系统凭据中保存的 API Key，
会真实消耗 token；建议先用 --offline 验证基准本身。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402


def load_case(case_id: str) -> dict:
    path = app.REGRESSION_DIR / f"{case_id}.json"
    case = app.read_json(path, None)
    if not isinstance(case, dict):
        raise SystemExit(f"基准用例不存在：{path}")
    return case


def list_cases() -> None:
    cases = app.list_regression_cases().get("cases", [])
    if not cases:
        print("还没有基准用例。在 Topic 工作台的质量巡检面板点「存为回归基准」，或对项目调 POST /api/projects/<id>/regression/capture。")
        return
    for case in cases:
        print(f"{case['id']}  {case.get('created_at', '')}  {case.get('topic_count', 0)} 个 Topic  {case.get('name', '')}")


def offline_stats(case: dict) -> dict:
    rows = []
    for topic in case.get("topics", []):
        lint = topic.get("baseline_lint") or app.lint_topic_xml(topic.get("baseline_xml", ""), str(topic["payload"].get("topic_type", "")))
        fp = topic.get("baseline_fingerprint") or app.topic_structure_fingerprint(topic.get("baseline_xml", ""))
        rows.append(
            {
                "topic_id": topic.get("topic_id"),
                "title": topic["payload"].get("title", ""),
                "lint_error_count": lint.get("error_count", 0),
                "lint_warning_count": lint.get("warning_count", 0),
                "step_count": fp.get("step_count"),
                "section_count": len(fp.get("section_titles", []) or []),
                "fingerprint_ok": fp.get("ok", False),
            }
        )
    return rows


def run_online(case: dict, only_topic: str | None) -> dict:
    settings = app.load_settings()
    results = []
    for topic in case.get("topics", []):
        topic_id = str(topic.get("topic_id", ""))
        if only_topic and topic_id != only_topic:
            continue
        payload = dict(topic.get("payload") or {})
        title = str(payload.get("title", topic_id))
        row: dict = {"topic_id": topic_id, "title": title}
        try:
            ai = app.generate_ai_topic(str(case["source_project_id"]), payload)
            new_xml = str(ai.get("xml", ""))
            new_lint = ai.get("lint") or app.lint_topic_xml(new_xml, str(payload.get("topic_type", "")))
            new_fp = app.topic_structure_fingerprint(new_xml)
            base_lint = topic.get("baseline_lint") or app.lint_topic_xml(topic.get("baseline_xml", ""), str(payload.get("topic_type", "")))
            base_fp = topic.get("baseline_fingerprint") or app.topic_structure_fingerprint(topic.get("baseline_xml", ""))
            similarity = app.fingerprint_similarity(base_fp, new_fp)
            row.update(
                {
                    "ok": True,
                    "model": ai.get("model"),
                    "generation_mode": ai.get("generation_mode"),
                    "attempts": len(app.ai_call_metas()) or 1,
                    "usage": ai.get("usage"),
                    "baseline_lint": {"error": base_lint["error_count"], "warning": base_lint["warning_count"]},
                    "new_lint": {"error": new_lint["error_count"], "warning": new_lint["warning_count"]},
                    "tag_jaccard": similarity.get("tag_jaccard"),
                    "structure_differences": similarity.get("differences", []),
                }
            )
        except Exception as exc:  # noqa: BLE001 - 报告中记录失败原因
            row.update({"ok": False, "error": str(exc)})
        results.append(row)
    return {"case_id": case["id"], "name": case.get("name", ""), "settings": {"provider": settings.get("provider"), "model": settings.get("model")}, "results": results}


def write_report(report: dict, offline: bool) -> Path:
    reports_dir = app.DATA_DIR / "regression" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = reports_dir / f"{report['case_id']}-{stamp}"
    (base.with_suffix(".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# 回归报告：{report.get('name', report['case_id'])}",
        "",
        f"- 时间：{datetime.now().isoformat(timespec='seconds')}",
        f"- 模式：{'离线（仅基准统计）' if offline else '在线重生成对比'}",
    ]
    if not offline:
        lines.append(f"- 当前配置：{report.get('settings', {}).get('provider', '')} / {report.get('settings', {}).get('model', '')}")
    lines.append("")
    if offline:
        rows = report.get("baseline_stats", [])
        lint_errors = sum(r["lint_error_count"] for r in rows)
        lint_warnings = sum(r["lint_warning_count"] for r in rows)
        lines += [
            f"- 基准 Topic 数：{len(rows)}；lint 错误 {lint_errors} 个、提醒 {lint_warnings} 个",
            "",
            "| Topic | lint 错误 | lint 提醒 | 步骤数 | 章节数 |",
            "|---|---|---|---|---|",
        ]
        for r in rows:
            lines.append(f"| {r['title']} | {r['lint_error_count']} | {r['lint_warning_count']} | {r['step_count']} | {r['section_count']} |")
    else:
        rows = report.get("results", [])
        ok_rows = [r for r in rows if r.get("ok")]
        avg_jaccard = sum(r["tag_jaccard"] for r in ok_rows) / len(ok_rows) if ok_rows else 0
        lint_pass = sum(1 for r in ok_rows if r["new_lint"]["error"] == 0)
        lines += [
            f"- Topic 数：{len(rows)}；成功 {len(ok_rows)}；平均标签轮廓相似度 {avg_jaccard:.2%}；lint 零错误 {lint_pass}/{len(ok_rows)}",
            "",
            "| Topic | 相似度 | lint 基线(错/警) | lint 新(错/警) | 结构差异 |",
            "|---|---|---|---|---|",
        ]
        for r in rows:
            if not r.get("ok"):
                lines.append(f"| {r['title']} | 失败 | - | - | {r.get('error', '')[:60]} |")
                continue
            diffs = "；".join(r["structure_differences"]) or "无"
            lines.append(
                f"| {r['title']} | {r['tag_jaccard']:.2%} | {r['baseline_lint']['error']}/{r['baseline_lint']['warning']} | {r['new_lint']['error']}/{r['new_lint']['warning']} | {diffs[:80]} |"
            )
    report_path = base.with_suffix(".md")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(description="回归集对比：基准统计或重生成对比")
    parser.add_argument("--list", action="store_true", help="列出所有基准用例")
    parser.add_argument("--offline", action="store_true", help="只统计基准自身的 lint 与结构，不调 AI")
    parser.add_argument("--case", help="基准用例 ID（--list 可查）")
    parser.add_argument("--topic", help="只跑指定 topic_id（配合 --case）")
    parser.add_argument("--root", help="炼金炉根目录（默认仓库自身；调试包传 ~/Applications/炼金炉）")
    args = parser.parse_args()

    if args.root:
        root = Path(args.root).expanduser().resolve()
        if not (root / "app.py").exists():
            raise SystemExit(f"指定根目录下没有 app.py：{root}")
        app.DATA_DIR = root / "data"
        app.PROJECTS_DIR = app.DATA_DIR / "projects"
        app.SETTINGS_FILE = app.DATA_DIR / "settings.json"
        app.REGRESSION_DIR = app.DATA_DIR / "regression"
        app.GENERATION_LOG_DIR = app.DATA_DIR / "generation_logs"
        print(f"使用数据目录：{app.DATA_DIR}")

    if args.list:
        list_cases()
        return
    if not args.case:
        parser.error("请指定 --case <id>，或用 --list 查看可用用例。")
    case = load_case(args.case)
    if args.offline:
        report = {"case_id": case["id"], "name": case.get("name", ""), "baseline_stats": offline_stats(case)}
    else:
        report = run_online(case, args.topic)
    path = write_report(report, args.offline)
    print(f"报告已写入：{path}")
    # 控制台摘要
    if args.offline:
        rows = report["baseline_stats"]
        print(f"基准 Topic：{len(rows)} 个；lint 错误合计 {sum(r['lint_error_count'] for r in rows)}，提醒合计 {sum(r['lint_warning_count'] for r in rows)}")
    else:
        rows = report.get("results", [])
        ok_rows = [r for r in rows if r.get("ok")]
        if ok_rows:
            avg = sum(r["tag_jaccard"] for r in ok_rows) / len(ok_rows)
            print(f"成功 {len(ok_rows)}/{len(rows)}；平均相似度 {avg:.2%}；lint 零错误 {sum(1 for r in ok_rows if r['new_lint']['error'] == 0)} 个")
        for r in rows:
            if not r.get("ok"):
                print(f"失败：{r['title']}：{r.get('error', '')}")


if __name__ == "__main__":
    main()

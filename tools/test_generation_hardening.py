#!/usr/bin/env python3
"""Offline tests for the V2.1.0 generation hardening changes.

Runs without network access and without touching data/: call_ai_messages is
monkeypatched to simulate AI responses. Usage: python3 tools/test_generation_hardening.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app  # noqa: E402


def test_guid_pattern():
    real = "GUID-0007E23C-6BE9-4DB4-A8AB-233CE6EA1815"
    assert app.GUID_PATTERN.findall(f"see {real} here") == [real], "real KC GUID must match"
    assert app.GUID_PATTERN.findall("GUID=0007e23c-6be9-4db4-a8ab-233ce6ea1815"), "GUID= hex form must match"
    assert not app.GUID_PATTERN.findall("our GUID-based workflow"), "English prose must not match"
    assert not app.GUID_PATTERN.findall("GUID-abc GUID-12345678-hello-world"), "loose forms must not match"
    sanitized = app.sanitize_text(f"参考 {real} 与 GUID-based 描述")
    assert "TODO_REF" in sanitized and real not in sanitized
    assert "GUID-based" in sanitized, "prose must survive sanitize"
    print("PASS  GUID pattern tightened")


def test_fit_prompt_sections():
    sections = [
        app.PromptSection("corpus", "参考项目语料", 4, "C" * 50_000),
        app.PromptSection("skill:a", "Skill：A", 2, "S" * 30_000),
        app.PromptSection("material:1", "材料：一", 1, "M" * 100_000),
        app.PromptSection("material:2", "材料：二", 1, "N" * 100_000),
    ]
    trimmed, report = app.fit_prompt_sections(sections, 150_000)
    by_key = {s.key: s for s in trimmed}
    assert len(by_key["material:1"].text) == 100_000, "highest priority material fully kept"
    assert len(by_key["material:2"].text) == 50_000, "second material truncated to remaining budget"
    assert by_key["skill:a"].text == "", "skill dropped after material budget exhausted (素材 > Skill)"
    assert by_key["corpus"].text == "", "lowest priority dropped when budget exhausted"
    dropped = [item for item in report if item.get("dropped")]
    truncated = [item for item in report if item.get("truncated")]
    assert {item["key"] for item in dropped} == {"skill:a", "corpus"}
    assert len(truncated) == 1 and truncated[0]["key"] == "material:2"
    summary = app.context_report_summary(report)
    assert "材料：二" in summary and "参考项目语料" in summary
    print("PASS  prompt budget waterfall + report")


def test_parse_task_structure():
    good = json.dumps(
        {
            "title": "导出报表",
            "shortdesc": "本文介绍如何导出报表。",
            "prerequisites": ["已创建项目"],
            "context": ["支持按日期导出。"],
            "steps": [
                {"command": "进入导出页面。", "info": ["支持批量"], "result": "页面刷新。"},
                {"command": "单击导出。", "info": [], "result": ""},
            ],
            "overall_result": ["系统下载 CSV 文件。"],
            "unconfirmed": [{"claim": "默认保留 90 天", "reason": "材料未提及"}],
        },
        ensure_ascii=False,
    )
    structure = app.parse_task_structure(f"```json\n{good}\n```")
    assert structure["title"] == "导出报表"
    assert len(structure["steps"]) == 2 and structure["steps"][0]["command"].startswith("进入")
    assert structure["unconfirmed"][0]["claim"] == "默认保留 90 天"

    for bad, needle in [
        (json.dumps({"title": "t", "shortdesc": "s", "steps": [{"command": "只有一步"}]}, ensure_ascii=False), "至少需要 2 个操作步骤"),
        (json.dumps({"title": "", "shortdesc": "s", "steps": []}, ensure_ascii=False), "title"),
        ("not json at all", "有效 JSON"),
    ]:
        try:
            app.parse_task_structure(bad)
        except RuntimeError as exc:
            assert needle in str(exc), f"unexpected error message: {exc}"
        else:  # pragma: no cover
            raise AssertionError(f"expected failure for {bad!r}")
    print("PASS  task structure parsing + rule errors")


def test_render_task_xml():
    structure = app.parse_task_structure(
        json.dumps(
            {
                "title": "导出<报表>",
                "shortdesc": "本文介绍如何导出报表，涵盖筛选与导出操作。",
                "prerequisites": ["已创建项目"],
                "context": ["说明 & 提示"],
                "steps": [
                    {"command": "进入“报表”页签。", "info": ["支持批量导出"], "result": "列表刷新。"},
                    {"command": "单击导出。", "info": [], "result": "系统下载文件。"},
                ],
                "overall_result": ["导出完成。"],
            },
            ensure_ascii=False,
        )
    )
    xml_text = app.render_task_topic_xml(structure)
    root = app.ET.fromstring(xml_text)  # well-formed check
    assert root.tag == "task"
    assert "导出&lt;报表&gt;" in xml_text, "title must be escaped"
    assert "说明 &amp; 提示" in xml_text
    assert xml_text.index("<prereq>") < xml_text.index("<context>") < xml_text.index("<steps>") < xml_text.index("<result>")
    assert 'id="STEP_1"' in xml_text and "<stepresult>" in xml_text and "<info>" in xml_text
    validation = app.validate_topic_xml(xml_text)
    assert validation["ok"], f"rendered XML must pass validation: {validation}"
    print("PASS  task XML rendering (escape/order/validate)")


def test_generate_with_repair(monkeypatched_responses: list[str], parse: Any):
    calls: list[list[dict]] = []

    def fake_call_ai_messages(settings, system, messages, max_tokens=6000, json_mode=False):
        calls.append([dict(m) for m in messages])
        return monkeypatched_responses[len(calls) - 1], "mock-model"

    original = app.call_ai_messages
    app.call_ai_messages = fake_call_ai_messages
    try:
        result, _model = app.generate_with_repair({}, "sys", "user", parse, max_tokens=3)
        return result, calls
    finally:
        app.call_ai_messages = original


def test_repair_loop():
    good = json.dumps({"markdown": "# 标题\n## 章节", "summary": "ok"}, ensure_ascii=False)

    def parse(text: str) -> dict:
        data = json.loads(app.clean_ai_json(text))
        if not isinstance(data, dict) or not data.get("markdown"):
            raise RuntimeError("缺少 markdown 字段")
        return data

    # 第一次坏输出、第二次修正 → 成功且第二次请求带上了错误回喂。
    result, calls = test_generate_with_repair(['oops {"broken', good], parse)
    assert result["markdown"].startswith("# 标题")
    assert len(calls) == 2
    assert any(m["role"] == "assistant" for m in calls[1]), "second attempt must carry previous output"
    feedback = [m for m in calls[1] if m["role"] == "user"][-1]["content"]
    assert "存在以下问题" in feedback

    # 持续失败 → 达到尝试上限后明确报错。
    try:
        test_generate_with_repair(["bad1", "bad2", "bad3"], parse)
    except RuntimeError as exc:
        assert "3 次尝试" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError after max attempts")
    print("PASS  error-feedback repair loop")


def test_configured_max_tokens():
    assert app._configured_max_tokens({"max_tokens": 12000}, 6000) == 12000
    assert app._configured_max_tokens({"max_tokens": 0}, 6000) == 6000
    assert app._configured_max_tokens({}, 9000) == 9000
    assert app._configured_max_tokens({"max_tokens": "abc"}, 6000) == 6000
    print("PASS  max_tokens settings override")


def test_parse_concept_structure():
    good = json.dumps(
        {
            "title": "设备概述",
            "shortdesc": "本文介绍设备的主要功能与组成。",
            "context": ["设备支持远程管理。"],
            "sections": [
                {"title": "功能特点", "level": 1, "paragraphs": ["支持实时预览。", "TODO_CONFIRM：最大并发数待确认。"]},
                {"title": "硬件组成", "level": 2, "paragraphs": ["包含主控模块。"]},
            ],
            "unconfirmed": [{"claim": "最大并发 128", "reason": "材料只写了支持高并发"}],
        },
        ensure_ascii=False,
    )
    structure = app.parse_concept_structure(f"```json\n{good}\n```")
    assert structure["title"] == "设备概述"
    assert len(structure["sections"]) == 2 and structure["sections"][1]["level"] == 2
    assert structure["unconfirmed"][0]["reason"].startswith("材料")

    for bad, needle in [
        (json.dumps({"title": "t", "shortdesc": "s", "sections": []}, ensure_ascii=False), "至少需要 1 个章节"),
        (json.dumps({"title": "t", "shortdesc": "s", "sections": [{"title": "空段落", "paragraphs": []}]}, ensure_ascii=False), "缺少段落内容"),
        ("{broken json", "有效 JSON"),
    ]:
        try:
            app.parse_concept_structure(bad)
        except RuntimeError as exc:
            assert needle in str(exc), f"unexpected error message: {exc}"
        else:  # pragma: no cover
            raise AssertionError(f"expected failure for {bad!r}")
    print("PASS  concept structure parsing + rule errors")


def test_render_concept_xml():
    structure = app.parse_concept_structure(
        json.dumps(
            {
                "title": "设备<概述>",
                "shortdesc": "本文介绍设备的主要功能与组成模块。",
                "context": ["说明 & 背景"],
                "sections": [
                    {"title": "功能特点", "level": 1, "paragraphs": ["支持实时预览。", "参数为 TODO_CONFIRM。"]},
                    {"title": "子项", "level": 2, "paragraphs": ["嵌套段落。"]},
                    {"title": "同级", "level": 1, "paragraphs": ["回到一级。"]},
                ],
            },
            ensure_ascii=False,
        )
    )
    xml_text = app.render_concept_topic_xml(structure)
    root = app.ET.fromstring(xml_text)
    assert root.tag == "concept"
    assert "设备&lt;概述&gt;" in xml_text and "说明 &amp; 背景" in xml_text
    assert 'id="SECTION_1"' in xml_text and 'id="SECTION_1_1"' in xml_text and 'id="SECTION_2"' in xml_text
    validation = app.validate_topic_xml(xml_text)
    assert validation["ok"] and validation["confirm_count"] == 1, f"TODO_CONFIRM must be counted: {validation}"
    assert validation["status"] == "需人工处理"
    print("PASS  concept XML rendering (nesting/escape/TODO_CONFIRM)")


def test_slice_material_for_topic():
    short = "只有一小段。"
    text, ranges = app.slice_material_for_topic(short, ["设备"])
    assert text == short and ranges == [], "short material returned verbatim without ranges"

    target = "设备支持 AES256 加密，密钥由用户配置。\n"
    filler = "这段与主题无关，只是背景介绍。\n" * 10
    long_text = (filler + target * 3 + filler) * 5
    sliced, ranges = app.slice_material_for_topic(long_text, ["AES256", "加密"], max_chars=1200)
    assert len(sliced) <= 1400, "slice respects budget (markers included)"
    assert "［原文 " in sliced and "AES256" in sliced, "kept segments carry original offsets"
    assert all(len(pair) == 2 and pair[0] < pair[1] <= len(long_text) for pair in ranges), "ranges valid offsets"
    print("PASS  material slicing with offset traceability")


def test_list_project_unconfirmed():
    original_read_json = app.read_json
    original_project_dir = app.project_dir
    original_list_topics = app.list_topics

    app.project_dir = lambda project_id: Path("/tmp/fake-project")
    app.read_json = lambda path, default=None: {"id": "fake", "name": "假项目"}
    app.list_topics = lambda project_id: [
        {
            "id": "t1",
            "title": "Topic 一",
            "unconfirmed": [{"claim": "默认 90 天", "reason": "材料未提及"}],
            "validation": {"confirm_count": 2},
        },
        {"id": "t2", "title": "Topic 二", "unconfirmed": [], "validation": {}},
    ]
    try:
        report = app.list_project_unconfirmed("fake")
    finally:
        app.read_json = original_read_json
        app.project_dir = original_project_dir
        app.list_topics = original_list_topics
    assert report["project_id"] == "fake"
    assert len(report["items"]) == 1 and report["items"][0]["claim"] == "默认 90 天"
    assert report["items"][0]["topic_title"] == "Topic 一"
    assert report["topic_confirm_count"] == 2
    print("PASS  unconfirmed aggregation endpoint logic")


def test_sibling_context_block():
    empty = app.sibling_context_block({})
    assert empty == "", "no siblings means no block"
    block = app.sibling_context_block(
        {
            "parent_title": "系统配置",
            "sibling_topics": [
                {"title": "登录设备", "topic_type": "task", "shortdesc": "介绍登录"},
                {"title": "密码策略", "shortdesc": ""},
                "纯文本兄弟",
            ],
        }
    )
    assert "父章节：系统配置" in block
    assert "登录设备（task）：介绍登录" in block
    assert "密码策略（concept）" in block and "纯文本兄弟（concept）" in block
    assert "不要展开" in block
    # system prompt integration
    project = {"id": "p", "name": "P", "mode": "new", "skills": []}
    payload = {"topic_type": "concept", "title": "T", "shortdesc": "S", "material_ids": [], "skills": [],
               "parent_title": "父", "sibling_topics": [{"title": "兄弟A"}]}
    system, user, *_ = app.build_topic_ai_messages(project, payload, structured=True)
    assert "兄弟章节上下文" in user and "兄弟A" in user
    print("PASS  sibling context injection")


def test_batch_generate_topics():
    original = {
        "read_json": app.read_json,
        "project_dir": app.project_dir,
        "list_topics": app.list_topics,
        "create_topic": app.create_topic,
        "regenerate_topic": app.regenerate_topic,
    }
    created: list[str] = []
    updated: list[str] = []

    app.project_dir = lambda project_id: Path("/tmp/fake-project")
    app.read_json = lambda path, default=None: {"id": "fake", "name": "假项目"}
    app.list_topics = lambda project_id: [
        {"id": "t_old", "title": "旧标题", "framework_node_key": "fw:旧节点"},
    ]

    def fake_create(project_id, payload):
        if payload["title"] == "会失败":
            raise RuntimeError("模拟单点失败")
        created.append(payload["title"])
        return {"id": f"t_new_{len(created)}"}

    def fake_regenerate(project_id, topic_id, payload):
        updated.append((topic_id, payload["title"]))
        return {"id": topic_id}

    app.create_topic = fake_create
    app.regenerate_topic = fake_regenerate
    try:
        result = app.batch_generate_topics(
            "fake",
            {
                "nodes": [
                    {"title": "旧节点", "framework_node_key": "fw:旧节点"},
                    {"title": "新节点", "framework_node_key": "fw:新节点"},
                    {"title": "会失败", "framework_node_key": "fw:失败"},
                    {"title": "", "framework_node_key": "fw:空标题"},
                ],
                "common": {"generation_prompt": "统一提示"},
            },
        )
    finally:
        app.read_json = original["read_json"]
        app.project_dir = original["project_dir"]
        app.list_topics = original["list_topics"]
        app.create_topic = original["create_topic"]
        app.regenerate_topic = original["regenerate_topic"]
    assert result["total"] == 3, "blank-title node must be skipped"
    assert result["succeeded"] == 2 and result["failed"] == 1
    assert created == ["新节点"], "new key creates topic"
    assert updated == [("t_old", "旧节点")], "existing key regenerates in place"
    failed_item = next(item for item in result["items"] if item["status"] == "failed")
    assert "模拟单点失败" in failed_item["error"], "single failure recorded, batch continued"
    print("PASS  backend batch generation (create/update/failure isolation)")


def test_check_topic_consistency():
    original_list_topics = app.list_topics
    original_read_json = app.read_json
    original_project_dir = app.project_dir
    app.project_dir = lambda project_id: Path("/tmp/fake-project")
    app.read_json = lambda path, default=None: {"id": "fake", "name": "假项目"}
    guid = "GUID-0007E23C-6BE9-4DB4-A8AB-233CE6EA1815"
    app.list_topics = lambda project_id: [
        {"id": "t1", "title": "重复标题", "framework_node_key": "fw:a", "xml": f"<concept>{guid}</concept>", "unconfirmed": [{"claim": "x"}], "validation": {"confirm_count": 1}},
        {"id": "t2", "title": "重复标题", "framework_node_key": "fw:a", "xml": "<concept>ok</concept>", "unconfirmed": [], "validation": {}},
        {"id": "t3", "title": "无关联", "framework_node_key": "", "xml": "<concept>ok</concept>", "unconfirmed": [], "validation": {}},
    ]
    try:
        report = app.check_topic_consistency("fake")
    finally:
        app.list_topics = original_list_topics
        app.read_json = original_read_json
        app.project_dir = original_project_dir
    assert report["duplicate_titles"] == [{"title": "重复标题", "topic_ids": ["t1", "t2"]}]
    assert report["duplicate_node_keys"] == [{"framework_node_key": "fw:a", "topic_ids": ["t1", "t2"]}]
    assert report["guid_residue"] == [{"topic_id": "t1", "title": "重复标题"}]
    assert report["missing_node_key"] == ["t3"]
    assert report["todo_confirm_total"] == 1 and report["unconfirmed_total"] == 1
    print("PASS  cross-topic consistency checks")


if __name__ == "__main__":
    from typing import Any  # noqa: F401  (used in annotations above)

    test_guid_pattern()
    test_fit_prompt_sections()
    test_parse_task_structure()
    test_render_task_xml()
    test_repair_loop()
    test_configured_max_tokens()
    test_parse_concept_structure()
    test_render_concept_xml()
    test_slice_material_for_topic()
    test_list_project_unconfirmed()
    test_sibling_context_block()
    test_batch_generate_topics()
    test_check_topic_consistency()
    print("\nALL TESTS PASSED")

"""AI 연결 입구(11-23): 설명서 분야 나누기, 목록 좁히기, 여러 스텝 한 번에 시험."""
import asyncio
import json

from engine import mcp_server as M
from engine.library import DictLibrary
from engine import new_macro


def test_reference_core_lists_categories_and_is_short():
    core = M.reference_text("")
    full = M.reference_text("all")
    assert len(core) < len(full) * 0.4
    for cid, *_ in M.REF_CATS:
        assert f"- {cid}:" in core
    assert "type_text" in core and "excel" in core           # 분야 목록에 스텝 이름이 다 보임(못 찾는 일 막기)


def test_reference_categories_cover_every_step_row():
    full = M.reference_text("all")
    parts = M._ref_parts(full)
    rows = [l for l in parts[4].splitlines() if l.startswith("|")][2:]
    seen = "\n".join(M.reference_text(c[0]) for c in M.REF_CATS)
    for r in rows:
        assert r in seen, r[:40]                               # 스텝 표의 모든 줄이 어느 분야엔가 있음


def test_reference_unknown_category_lists_choices():
    assert "input" in M.reference_text("모름")


def test_macro_list_compact_and_filtered(monkeypatch):
    lib = DictLibrary()
    for n in ("메모장_저장", "엑셀_입력", "샵_자동"):
        lib.add(new_macro(n, [{"type": "delay", "seconds": 1}]))

    class E:
        library = lib
    monkeypatch.setattr(M, "env", lambda: E())
    monkeypatch.setattr(M, "_load_groups", lambda: {"사무": ["메모장_저장", "엑셀_입력"]})
    d = json.loads(M.macro_list())
    assert d["count"] == 3 and {g["group"] for g in d["groups"]} == {"사무", ""}
    assert "steps" not in json.dumps(d)                       # 자세한 건 안 줌
    rows = json.loads(M.macro_list(query="메모"))
    assert [r["name"] for r in rows] == ["메모장_저장"] and rows[0]["steps"] == 1
    rows = json.loads(M.macro_list(group="사무"))
    assert {r["name"] for r in rows} == {"메모장_저장", "엑셀_입력"}


def test_test_step_requires_step_or_steps():
    out = asyncio.run(M.macro_test_step())
    assert "steps" in out[0]

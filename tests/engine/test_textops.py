"""사무 기능 ①: 글자 안 {변수}(모든 글자 칸), 글자 만들기·날짜·계산 스텝, 글자 비교 조건. 가짜 화면·입력."""
import datetime as dt

import pytest

from engine import new_macro, validate_macro
from engine.textops import TextOpError, calc, date_op, fill, format_date, parse_date, text_op
from tests.engine.test_runner import World


def typed(w):
    return [e[2] for e in w.input.events if e[1] == "type"]


def test_type_text_fills_vars_and_keeps_unknown_braces():
    w = World()
    r = w.run([{"type": "set", "var": "이름", "value": "김민준"},
               {"type": "type_text", "text": "{이름} 님 {모름} {a b}"}])
    assert r.status == "ok"
    assert typed(w) == ["김민준 님 {모름} {a b}"]
    assert any(e.get("event") == "warning" and "모름" in e.get("message", "") for e in w.events)


def test_launch_menu_key_snapshot_set_fill():
    w = World()
    launched = []
    m = new_macro("m", [{"type": "set", "var": "k", "value": "enter"},
                        {"type": "set", "var": "파일", "value": "a.txt"},
                        {"type": "launch", "target": "notepad {파일}"},
                        {"type": "key", "keys": "{k}"},
                        {"type": "set", "var": "인사", "value": "안녕 {파일}"}])
    r = w.runner(m)
    r.launcher = launched.append
    res = r.run()
    assert res.status == "ok"
    assert launched == ["notepad a.txt"]
    assert ("key_down", "enter") in [e[1:] for e in w.input.events]


def test_text_step_actions():
    w = World()
    steps = [{"type": "set", "var": "원문", "value": "  주문번호: A-1234 / 금액 12,500원 "},
             {"type": "text", "var": "깔끔", "text": "{원문}", "action": "trim"},
             {"type": "text", "var": "번호", "text": "{원문}", "action": "extract", "pattern": r"A-(\d+)"},
             {"type": "text", "var": "금액", "text": "{원문}", "action": "extract", "pattern": r"([\d,]+)원"},
             {"type": "text", "var": "금액수", "text": "{금액}", "action": "number"},
             {"type": "text", "var": "조각", "text": "a, b, c", "action": "split", "sep": ",", "index": -1},
             {"type": "text", "var": "목록", "text": "a, b, c", "action": "split", "sep": ","},
             {"type": "text", "var": "합침", "list": "목록", "action": "join", "sep": "/"},
             {"type": "text", "var": "바꿈", "text": "2026.11.18", "action": "replace", "find": ".", "with": "-"},
             {"type": "text", "var": "앞", "text": "가나다라", "action": "slice", "start": 1, "count": 2},
             {"type": "text", "var": "번호2", "text": "7", "action": "pad", "width": 3},
             {"type": "text", "var": "파일명", "text": "재직_{번호}_{조각}.hwp"}]
    m = new_macro("m", steps)
    assert validate_macro(m) == []
    r = w.runner(m)
    res = r.run()
    assert res.status == "ok", res.error
    v = r._last_vars if hasattr(r, "_last_vars") else None
    # 변수는 이벤트로 확인
    got = {e["var"]: e["value"] for e in w.events if e.get("event") == "set"}
    assert got["깔끔"].startswith("주문번호")
    assert got["번호"] == "1234" and got["금액"] == "12,500" and got["금액수"] == 12500
    assert got["조각"] == "c" and got["목록"] == ["a", "b", "c"] and got["합침"] == "a/b/c"
    assert got["바꿈"] == "2026-11-18" and got["앞"] == "가나" and got["번호2"] == "007"
    assert got["파일명"] == "재직_1234_c.hwp"
    assert v is None or isinstance(v, dict)


def test_text_step_missing_var_or_no_match_fails():
    w = World()
    assert w.run([{"type": "text", "var": "x", "text": "{없음}"}]).status == "failed"
    w = World()
    r = w.run([{"type": "text", "var": "x", "text": "abc", "action": "extract", "pattern": r"\d+"}])
    assert r.status == "failed"
    w = World()          # 실패해도 건너뛰기로 이어 가기
    r = w.run([{"type": "text", "var": "x", "text": "abc", "action": "extract", "pattern": r"\d+", "on_fail": "skip"},
               {"type": "type_text", "text": "계속"}])
    assert r.status == "ok" and typed(w) == ["계속"]


def test_date_format_parse_add_diff():
    now = dt.datetime(2026, 11, 18, 9, 5, 7)
    assert date_op({}, {}, now) == "2026-11-18"
    assert date_op({"format": "yyyy년 M월 d일 (요일) HH:mm"}, {}, now) == "2026년 11월 18일 (수) 09:05"
    assert date_op({"add": {"months": 3}, "format": "yyyyMMdd"}, {}, dt.datetime(2026, 11, 30)) == "20270228"
    assert date_op({"from": "{입사}", "add": {"days": -1}}, {"입사": "2024.03.01"}, now) == "2024-02-29"
    assert date_op({"action": "diff", "from": "2026-11-01", "to": "2026-11-18"}, {}, now) == 17
    assert parse_date(45000) == dt.datetime(2023, 3, 15)            # 엑셀 날짜 숫자
    assert parse_date("2026년 1월 2일") == dt.datetime(2026, 1, 2)
    with pytest.raises(TextOpError):
        parse_date("어제쯤")
    assert format_date(now, "ddd") == "Wed"


def test_date_step_runs_with_wall_clock():
    w = World()
    m = new_macro("m", [{"type": "date", "var": "오늘", "format": "yyyy-MM-dd"},
                        {"type": "type_text", "text": "보고서_{오늘}"}])
    r = w.runner(m)
    r._wall_now = lambda: dt.datetime(2026, 1, 9)
    assert r.run().status == "ok"
    assert typed(w) == ["보고서_2026-01-09"]


def test_calc_safe():
    v = {"가격": "1,200", "수량": 3, "비율": 0.1}
    assert calc("가격 * 수량", v) == 3600
    assert calc("{가격} * (1 + 비율)", v) == 1320
    assert calc("round(10 / 3, 2)", v) == 3.33
    assert calc("max(가격, 5000) - 1", v) == 4999
    for bad in ("__import__('os')", "가격.real", "open('x')", "[1,2]", "2 ** 1000", "1/0"):
        with pytest.raises(TextOpError):
            calc(bad, v)
    w = World()
    assert w.run([{"type": "calc", "var": "x", "expr": "없는변수 + 1"}]).status == "failed"


@pytest.mark.parametrize("op,want,expected", [
    ("contains", "완료", True), ("not_contains", "완료", False), ("starts_with", "처리", True),
    ("ends_with", "됨", True), ("matches", r"\d{3}", True), ("is_empty", True, False)])
def test_text_conditions(op, want, expected):
    w = World()
    r = w.run([{"type": "set", "var": "상태", "value": "처리 완료 123건 됨"},
               {"type": "if", "cond": {"var": "상태", op: want},
                "then": [{"type": "type_text", "text": "예"}], "else": [{"type": "type_text", "text": "아니"}]}])
    assert r.status == "ok"
    assert typed(w) == ["예" if expected else "아니"]


def test_number_text_compares_as_number_but_eq_unchanged():
    w = World()
    r = w.run([{"type": "set", "var": "돈", "value": "1,200"},
               {"type": "if", "cond": {"var": "돈", "gt": 1000}, "then": [{"type": "type_text", "text": "큼"}]},
               {"type": "if", "cond": {"var": "돈", "eq": 1200}, "then": [{"type": "type_text", "text": "같음"}]}])
    assert r.status == "ok" and typed(w) == ["큼"]


def test_cond_value_fills_vars():
    w = World()
    r = w.run([{"type": "set", "var": "a", "value": "사과"}, {"type": "set", "var": "b", "value": "사과"},
               {"type": "if", "cond": {"var": "a", "eq": "{b}"}, "then": [{"type": "type_text", "text": "같다"}]}])
    assert r.status == "ok" and typed(w) == ["같다"]


def test_validation_of_new_steps():
    ok = new_macro("m", [{"type": "text", "var": "x", "text": "a", "action": "upper"},
                         {"type": "date", "var": "d", "add": {"days": 1}},
                         {"type": "calc", "var": "c", "expr": "1+1"}])
    assert validate_macro(ok) == []
    bad = new_macro("m", [{"type": "text", "var": "x", "text": "a", "action": "없는동작"},
                          {"type": "text", "var": "x", "text": "a", "action": "extract", "pattern": "("},
                          {"type": "date", "var": "d", "add": {"weeks": 1}},
                          {"type": "calc", "var": "c"},
                          {"type": "if", "cond": {"var": "x", "matches": "["}, "then": []}])
    errs = validate_macro(bad)
    assert len(errs) >= 5, errs


def test_fill_and_text_op_units():
    assert fill("{a}-{b}", {"a": 1.0, "b": [1, 2]}) == ("1-1, 2", [])
    assert fill(5, {}) == (5, [])
    assert text_op("length", "가나다", {}, {}) == 3

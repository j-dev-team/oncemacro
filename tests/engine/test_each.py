"""사무 기능 ④: 목록마다(목록 변수·숫자 범위·글 줄·폴더 파일·엑셀 표 줄), 점 이름({행.이름})."""
import os

from engine import new_macro, validate_macro
from engine.textops import calc, fill, lookup
from tests.engine.test_runner import World


def typed(w):
    return [e[2] for e in w.input.events if e[1] == "type"]


def run(steps, **attrs):
    w = World()
    r = w.runner(new_macro("m", steps))
    for k, v in attrs.items():
        setattr(r, k, v)
    return r.run(), w


def test_each_list_range_lines_index_break_continue():
    res, w = run([
        {"type": "text", "var": "목록", "text": "사과, 배, 감, 귤", "action": "split", "sep": ","},
        {"type": "each", "var": "과일", "list": "목록", "index_var": "번호", "steps": [
            {"type": "if", "cond": {"var": "과일", "eq": "배"}, "then": [{"type": "continue"}]},
            {"type": "if", "cond": {"var": "과일", "eq": "귤"}, "then": [{"type": "break"}]},
            {"type": "type_text", "text": "{번호}:{과일}"}]},
        {"type": "set", "var": "끝", "value": 3},
        {"type": "each", "var": "i", "range": {"from": 1, "to": "{끝}"}, "steps": [{"type": "type_text", "text": "n{i}"}]},
        {"type": "set", "var": "글", "value": "첫째\n\n둘째\r\n셋째"},
        {"type": "each", "var": "줄", "lines": "글", "reverse": True, "max": 2,
         "steps": [{"type": "type_text", "text": "[{줄}]"}]},
    ])
    assert res.status == "ok", res.error
    assert typed(w) == ["1:사과", "3:감", "n1", "n2", "n3", "[셋째]", "[둘째]"]


def test_each_files_rename_batch(tmp_path):
    for n in ("스캔001.pdf", "스캔002.pdf", "메모.txt"):
        (tmp_path / "받은편지").mkdir(exist_ok=True)
        (tmp_path / "받은편지" / n).write_text("x")
    res, w = run([
        {"type": "each", "var": "파일", "files": {"path": "받은편지", "pattern": "*.pdf"}, "index_var": "번호", "steps": [
            {"type": "file", "action": "info", "path": "{파일}", "var": "정보"},
            {"type": "text", "var": "새", "text": "{번호}", "action": "pad", "width": 3},
            {"type": "file", "action": "rename", "path": "{파일}", "name": "2026-11_거래처_{새}.{정보.확장자}"}]},
    ], base_dir=str(tmp_path))
    assert res.status == "ok", res.error
    assert sorted(os.listdir(tmp_path / "받은편지")) == ["2026-11_거래처_001.pdf", "2026-11_거래처_002.pdf", "메모.txt"]


class FakeOffice:
    """엑셀 대신: 시트 하나(2차원 표)."""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def run(self, kind, action, p):
        self.calls.append((action, dict(p)))
        if action == "open":
            return p["path"]
        if action == "last_row":
            return len(self.table)
        if action == "read":
            a, b = p["cell"].split(":")

            def rc(s):
                col = "".join(ch for ch in s if ch.isalpha())
                row = int("".join(ch for ch in s if ch.isdigit()))
                n = 0
                for ch in col:
                    n = n * 26 + ord(ch) - 64
                return row, n
            r1, c1 = rc(a)
            r2, c2 = rc(b)
            out = []
            for r in range(r1, r2 + 1):
                row = self.table[r - 1] if r - 1 < len(self.table) else []
                out.append([row[c - 1] if c - 1 < len(row) else None for c in range(c1, c2 + 1)])
            return out
        raise AssertionError(action)

    def shutdown(self):
        pass


def test_each_excel_rows_with_header_names():
    office = FakeOffice([["이름", "부서", "금액"], ["김민준", "영업팀", 1200.0], ["이서연", "총무팀", 800.0],
                         [None, None, None], ["박도윤", "영업팀", 300.0]])
    res, w = run([
        {"type": "set", "var": "합계", "value": 0},
        {"type": "each", "var": "행", "rows": {"sheet": "명단"}, "steps": [
            {"type": "if", "cond": {"var": "행.부서", "contains": "영업"}, "then": [
                {"type": "calc", "var": "합계", "expr": "합계 + 행.금액"},
                {"type": "type_text", "text": "{행.행}:{행.이름}/{행.B}"}]}]},
        {"type": "type_text", "text": "합계 {합계}"},
    ], office=office)
    assert res.status == "ok", res.error
    assert typed(w) == ["2:김민준/영업팀", "5:박도윤/영업팀", "합계 1500"]


def test_dotted_lookup_units():
    v = {"행": {"이름": "김", "A": 1}, "목록": ["a", "b"], "정보.크기": 5}
    assert lookup(v, "행.이름") == "김" and lookup(v, "목록.2") == "b" and lookup(v, "목록.-1") == "b"
    assert lookup(v, "정보.크기") == 5
    assert fill("{행.이름}-{행.없음}", v) == ("김-{행.없음}", ["행.없음"])
    assert calc("행.A + 1", v) == 2


def test_validate_each():
    assert validate_macro(new_macro("m", [{"type": "each", "var": "x", "list": [1, 2], "steps": []},
                                          {"type": "each", "var": "x", "range": {"to": 3}, "steps": [{"type": "break"}]}])) == []
    errs = validate_macro(new_macro("m", [{"type": "each", "var": "x", "steps": []},
                                          {"type": "each", "var": "x", "list": "", "steps": []},
                                          {"type": "each", "var": "x", "range": {"from": 1}, "steps": []},
                                          {"type": "each", "var": "x", "files": {}, "steps": []}]))
    assert len(errs) == 4, errs

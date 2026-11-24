"""사무 기능 ⑥: 웹 표 읽기·내려받기(가짜 웹), CSV 읽기·쓰기, 엑셀에 표 한 번에 쓰기 모양."""
import base64
import os

from engine import new_macro, validate_macro
from engine.office import table_grid
from tests.engine.test_runner import World


class FakeWeb:
    def __init__(self):
        self.calls = []

    def run(self, action, **kw):
        self.calls.append((action, kw))
        if action == "table":
            return {"ok": True, "value": [{"행": 1, "row": 1, "1": "중국", "2": "1,411,750,000", "나라": "중국", "인구": "1,411,750,000"},
                                          {"행": 2, "row": 2, "1": "인도", "2": "1,392,329,000", "나라": "인도", "인구": "1,392,329,000"}]}
        if action == "download":
            return {"ok": True, "value": {"name": "report.xlsx", "size": 3, "data": base64.b64encode(b"abc").decode()}}
        return {"ok": True}

    def cancel(self):
        pass


def run(steps, **attrs):
    w = World()
    r = w.runner(new_macro("m", steps))
    for k, v in attrs.items():
        setattr(r, k, v)
    return r.run(), w


def test_web_table_to_csv_and_loop(tmp_path):
    web = FakeWeb()
    res, w = run([
        {"type": "web", "action": "table", "selector": "table.wikitable", "var": "표"},
        {"type": "each", "var": "줄", "list": "표", "steps": [
            {"type": "text", "var": "수", "text": "{줄.인구}", "action": "number"},
            {"type": "calc", "var": "억", "expr": "round(수 / 100000000, 1)"},
            {"type": "type_text", "text": "{줄.행}. {줄.나라} {억}억"}]},
        {"type": "file", "action": "write_csv", "path": "인구.csv", "data": "표"},
        {"type": "file", "action": "read_csv", "path": "인구.csv", "var": "다시"},
        {"type": "type_text", "text": "{다시.2.나라}"},
    ], web=web, base_dir=str(tmp_path))
    assert res.status == "ok", res.error
    assert [e[2] for e in w.input.events if e[1] == "type"] == ["1. 중국 14.1억", "2. 인도 13.9억", "인도"]
    raw = open(tmp_path / "인구.csv", encoding="utf-8-sig").read().splitlines()
    assert raw[0] == "나라,인구" and raw[1] == '중국,"1,411,750,000"'


def test_web_download_saves_with_number_on_clash(tmp_path):
    web = FakeWeb()
    os.makedirs(tmp_path / "받은것")
    (tmp_path / "받은것" / "report.xlsx").write_bytes(b"old")
    res, w = run([{"type": "web", "action": "download", "selector": "a.excel", "path": "받은것", "var": "파일"},
                  {"type": "if", "cond": {"file": {"path": "{파일}"}}, "then": [{"type": "type_text", "text": "받음"}]}],
                 web=web, base_dir=str(tmp_path))
    assert res.status == "ok", res.error
    assert (tmp_path / "받은것" / "report (2).xlsx").read_bytes() == b"abc"
    assert (tmp_path / "받은것" / "report.xlsx").read_bytes() == b"old"
    assert [e[2] for e in w.input.events if e[1] == "type"] == ["받음"]


def test_csv_cp949_and_append(tmp_path):
    p = tmp_path / "엑셀저장.csv"
    p.write_bytes("이름,부서\r\n김민준,영업팀\r\n".encode("cp949"))
    res, w = run([{"type": "file", "action": "read_csv", "path": str(p), "var": "표"},
                  {"type": "set", "var": "새", "value": [{"이름": "이서연", "부서": "총무팀"}]},
                  {"type": "file", "action": "write_csv", "path": "out.csv", "data": "표"},
                  {"type": "file", "action": "write_csv", "path": "out.csv", "data": "새", "append": True}],
                 base_dir=str(tmp_path))
    assert res.status == "ok", res.error
    lines = open(tmp_path / "out.csv", encoding="utf-8-sig").read().splitlines()
    assert lines == ["이름,부서", "김민준,영업팀", "이서연,총무팀"]


def test_table_grid_shapes():
    assert table_grid([[1, 2], [3]]) == [[1, 2], [3]]
    assert table_grid([1, 2, 3]) == [[1, 2, 3]]
    assert table_grid([{"행": 1, "1": "a", "이름": "a"}, {"행": 2, "1": "b", "이름": "b"}]) == [["이름"], ["a"], ["b"]]
    assert table_grid([{"1": "x", "2": "y"}]) == [["x", "y"]]
    assert table_grid("글") is None and table_grid([]) is None


def test_validate_table_download_csv():
    ok = new_macro("m", [{"type": "web", "action": "table", "var": "t"},
                         {"type": "web", "action": "download", "url": "https://a/b.xlsx"},
                         {"type": "file", "action": "read_csv", "path": "a.csv", "var": "t"},
                         {"type": "file", "action": "write_csv", "path": "b.csv", "data": "t"}])
    assert validate_macro(ok) == []
    errs = validate_macro(new_macro("m", [{"type": "web", "action": "table"},
                                          {"type": "web", "action": "download"},
                                          {"type": "file", "action": "write_csv", "path": "b.csv"}]))
    assert len(errs) == 3, errs

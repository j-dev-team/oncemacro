"""목록(더하기·정렬·중복 빼기), 두 줄짜리 표 묶어 돌기, 엑셀 새 파일·형식 저장(가짜 오피스)."""
from engine import new_macro, validate_macro
from engine.listops import sort_items
from tests.engine.test_runner import World


def run(steps, office=None):
    w = World()
    r = w.runner(new_macro("m", steps))
    if office is not None:
        r.office = office
    res = r.run()
    got = {e["var"]: e["value"] for e in w.events if e.get("event") == "set"}
    return res, w, r


def test_list_add_unique_sort_multi_keys():
    w = World()
    r = w.runner(new_macro("m", [
        {"type": "set", "var": "금액", "value": 300},
        {"type": "list", "var": "표", "action": "add", "value": {"날짜": "2026-11-03", "시간": "09:00", "금액": "{금액}"}},
        {"type": "list", "var": "표", "action": "add", "value": {"날짜": "2026-10-02", "시간": "12:00", "금액": 50}},
        {"type": "list", "var": "표", "action": "add", "value": {"날짜": "2026-11-03", "시간": "08:00", "금액": 70}},
        {"type": "list", "var": "표", "action": "add", "value": {"날짜": "2026-10-02", "시간": "12:00", "금액": 50}, "unique": True},
        {"type": "list", "var": "표", "action": "sort", "by": "날짜, 시간"},
        {"type": "list", "var": "표", "action": "count", "to_var": "개수"},
        {"type": "type_text", "text": "{개수}:{표.1.날짜}/{표.2.시간}/{표.3.금액}"},
    ]))
    res = r.run()
    assert res.status == "ok", res.error
    assert [e[2] for e in w.input.events if e[1] == "type"] == ["3:2026-10-02/08:00/300"]


def test_sort_kinds_and_desc():
    items = [{"n": "10"}, {"n": "9"}, {"n": "1,200"}, {"n": ""}]
    assert [i["n"] for i in sort_items(items, [{"key": "n"}])] == ["9", "10", "1,200", ""]       # 숫자로, 빈 값은 뒤
    assert [i["n"] for i in sort_items(items, [{"key": "n", "order": "desc"}])] == ["1,200", "10", "9", ""]
    assert sort_items(["2026.1.5", "2025-12-31"], [{"key": ""}]) == ["2025-12-31", "2026.1.5"]       # 날짜로
    assert sort_items(["나", "가"], [{"key": "", "as": "text"}]) == ["가", "나"]


class FakeOffice:
    """두 줄짜리 거래 표(은행 내역 모양) + 새 파일·저장 기록."""

    def __init__(self):
        self.table = [["거래일자", "구분", "내용", "금액"], ["", "", "받는분", ""],
                      ["2026/11/03\n09:00:00", "출금", "이체(홍길동)", "1,000"], ["", "", "홍 길동", ""],
                      ["2026/10/02\n12:00:00", "입금", "급여", "5,000"], ["", "", "회사", ""],
                      ["2026/10/05\n08:30:00", "출금", "카드", "700"], ["", "", "홍길동 통장", ""]]
        self.calls = []

    def run(self, kind, action, p):
        self.calls.append((action, dict(p)))
        if action == "last_row":
            return len(self.table)
        if action == "read":
            a, b = p["cell"].split(":")
            r1 = int("".join(c for c in a if c.isdigit()))
            r2 = int("".join(c for c in b if c.isdigit()))
            c2 = ord("".join(c for c in b if c.isalpha())) - 64
            return [(self.table[r - 1] + [None] * 9)[:c2] for r in range(r1, r2 + 1)]
        return "saved.xlsx" if action == "save_as" else None

    def shutdown(self):
        pass


def test_rows_grouped_by_two_lines_then_new_file():
    office = FakeOffice()
    w = World()
    r = w.runner(new_macro("m", [
        {"type": "each", "var": "행", "rows": {"header": 0, "from": 3, "group_by": "A", "cols": "A:D"}, "steps": [
            {"type": "text", "var": "이름", "text": "{행.C}{행.줄2.C}", "action": "replace", "find": " ", "with": ""},
            {"type": "if", "cond": {"all": [{"var": "행.B", "eq": "출금"}, {"var": "이름", "contains": "홍길동"}]}, "then": [
                {"type": "text", "var": "날", "text": "{행.A}", "action": "split", "sep": "\n", "index": 1},
                {"type": "text", "var": "돈", "text": "{행.D}", "action": "number"},
                {"type": "list", "var": "결과", "action": "add", "value": {"날짜": "{날}", "금액": "{돈}", "비고": ""}}]}]},
        {"type": "list", "var": "결과", "action": "sort", "by": [{"key": "날짜"}]},
        {"type": "excel", "action": "new", "sheet": "추출"},
        {"type": "excel", "action": "write", "sheet": "추출", "cell": "A1", "value": {"var": "결과"}},
        {"type": "excel", "action": "save_as", "path": "C:\\out\\결과.xlsx", "format": "xlsx", "overwrite": "number", "var": "파일"},
        {"type": "excel", "action": "close"},
    ]))
    r.office = office
    res = r.run()
    assert res.status == "ok", res.error
    writes = [p for a, p in office.calls if a == "write"]
    assert writes[0]["value"] == [{"날짜": "2026/10/05", "금액": 700, "비고": ""}, {"날짜": "2026/11/03", "금액": 1000, "비고": ""}]
    assert ("new", {"sheet": "추출"}) in office.calls
    assert any(a == "save_as" and p["format"] == "xlsx" and p["overwrite"] == "number" for a, p in office.calls)


def test_validation():
    assert validate_macro(new_macro("m", [{"type": "list", "var": "x", "value": 1},
                                          {"type": "list", "var": "x", "action": "sort", "by": [{"key": "a", "order": "desc"}]},
                                          {"type": "excel", "action": "new"},
                                          {"type": "each", "var": "r", "rows": {"group": 2}, "steps": []}])) == []
    errs = validate_macro(new_macro("m", [{"type": "list", "var": "x"},
                                          {"type": "list", "var": "x", "action": "없음"},
                                          {"type": "list", "var": "x", "action": "sort", "by": [{"key": "a", "order": "up"}]}]))
    assert len(errs) == 3, errs

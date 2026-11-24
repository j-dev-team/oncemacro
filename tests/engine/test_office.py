"""오피스 스텝(excel·word·hwp) 검사·실행 흐름. 가짜 세션으로 실제 프로그램 없이 돈다."""
from engine import Runner, new_macro, validate_macro
from engine.backends import FakeClock, FakeInput, FakeVision
from engine.office import OfficeError, fill_vars


class FakeOffice:
    def __init__(self):
        self.cells = {"A1": "이름", "B2": 1000, "B3": 2500}
        self.calls = []
        self.closed = False

    def run(self, kind, action, p):
        self.calls.append((kind, action, dict(p)))
        if action == "read":
            return self.cells.get(p["cell"])
        if action == "write":
            self.cells[p["cell"]] = p["value"]
        if action == "last_row":
            return 3
        if action == "fill_field" and p["name"] == "없음":
            raise OfficeError("누름틀 '없음' 가 없음")
        return None

    def shutdown(self):
        self.closed = True


def run(steps, office):
    clock = FakeClock()
    return Runner(new_macro("o", steps), vision=FakeVision(clock), input=FakeInput(clock), clock=clock,
                  office=office).run()


def test_validate_office_steps():
    ok = new_macro("o", [{"type": "excel", "action": "open", "path": "a.xlsx"},
                         {"type": "excel", "action": "read", "cell": "B{행}", "var": "v"},
                         {"type": "hwp", "action": "fill_field", "name": "이름", "text": "{고객}"},
                         {"type": "word", "action": "save_as", "path": "b.pdf"}])
    assert validate_macro(ok) == []
    bad = new_macro("o", [{"type": "excel", "action": "read", "cell": "A1"},       # var 없음
                          {"type": "hwp", "action": "jump"},                        # 모르는 동작
                          {"type": "word", "action": "replace", "find": "x"}])      # text 없음
    assert len(validate_macro(bad)) == 3


def test_loop_rows_with_template_vars():
    off = FakeOffice()
    res = run([{"type": "excel", "action": "last_row", "cell": "A", "var": "끝"},
               {"type": "set", "var": "행", "value": 2},
               {"type": "repeat", "while": {"var": "행", "le": {"var": "끝"}}, "max_times": 10, "steps": [
                   {"type": "excel", "action": "read", "cell": "B{행}", "var": "금액"},
                   {"type": "excel", "action": "write", "cell": "C{행}", "value": "확인"},
                   {"type": "set", "var": "행", "add": 1}]},
               {"type": "return", "value": {"var": "금액"}}], off)
    assert res.status == "ok" and res.value == 2500
    assert off.cells["C2"] == "확인" and off.cells["C3"] == "확인"
    assert not off.closed           # 밖에서 준 세션은 실행기가 닫지 않음


def test_failure_message_and_missing_var():
    res = run([{"type": "hwp", "action": "fill_field", "name": "없음", "text": "x"}], FakeOffice())
    assert res.status == "failed" and "누름틀" in res.error["reason"]
    res = run([{"type": "excel", "action": "read", "cell": "B{없는변수}", "var": "v"}], FakeOffice())
    assert res.status == "failed" and "없는변수" in res.error["reason"]


def test_fill_vars():
    assert fill_vars("B{행}", {"행": 3.0}) == "B3"
    assert fill_vars(5, {}) == 5

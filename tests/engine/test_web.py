"""웹 요소 스텝(web)·웹 조건 시험. 가짜 웹(FakeWeb)으로 브라우저 없이 돈다."""
from engine import Runner, new_macro, validate_macro
from engine.backends import FakeClock, FakeInput, FakeVision


class FakeWeb:
    """페이지 하나를 흉내: 요소 목록(selector → 글자), 입력칸 값, 지금 주소."""

    def __init__(self, elements=None, password_fields=()):
        self.elements = dict(elements or {})
        self.password_fields = set(password_fields)
        self.url = "about:blank"
        self.calls = []

    def run(self, action, *, selector="", url="", text="", page="p1", timeout_ms=5000, state="visible",
            path="", label="", should_stop=None):
        self.calls.append((action, selector or url, text))
        if action == "goto":
            self.url = url
            return {"ok": True, "value": url, "url": url}
        if action == "exists":
            return {"ok": True, "value": selector in self.elements, "url": self.url}
        if action in ("click", "wait", "read", "fill", "select") and selector not in self.elements:
            return {"ok": False, "error": f"요소 없음 {selector}"}
        if action in ("fill", "select"):
            if selector in self.password_fields:
                return {"ok": False, "error": "막음: 비밀번호·카드 칸에는 입력하지 않음"}
            self.elements[selector] = text
            return {"ok": True, "url": self.url}
        if action == "read":
            return {"ok": True, "value": self.elements[selector], "url": self.url}
        if action == "url":
            return {"ok": True, "value": self.url, "url": self.url}
        return {"ok": True, "url": self.url}


def run(steps, web):
    clock = FakeClock()
    r = Runner(new_macro("w", steps), vision=FakeVision(clock), input=FakeInput(clock), clock=clock, web=web)
    res = r.run()
    return res


def test_validate_web_step_and_cond():
    ok = new_macro("w", [
        {"type": "web", "action": "goto", "url": "https://example.com"},
        {"type": "web", "action": "fill", "selector": "input[name=q]", "text": {"var": "검색어"}},
        {"type": "web", "action": "read", "selector": "h1", "var": "제목"},
        {"type": "if", "cond": {"web": {"selector": "text=로그인"}}, "then": []},
    ])
    assert validate_macro(ok) == []
    bad = new_macro("w", [
        {"type": "web", "action": "goto"},                       # url 없음
        {"type": "web", "action": "click"},                      # selector 없음
        {"type": "web", "action": "read", "selector": "h1"},     # var 없음
        {"type": "web", "action": "jump", "selector": "a"},      # 모르는 동작
        {"type": "if", "cond": {"web": {"state": "visible"}}, "then": []},
    ])
    errs = validate_macro(bad)
    assert len(errs) == 5, errs


def test_goto_fill_click_read_flow():
    web = FakeWeb({"input[name=q]": "", "text=검색": "", "#result": "결과 3건"})
    res = run([
        {"type": "set", "var": "검색어", "value": "매크로"},
        {"type": "web", "action": "goto", "url": "https://example.com"},
        {"type": "web", "action": "fill", "selector": "input[name=q]", "text": {"var": "검색어"}},
        {"type": "web", "action": "click", "selector": "text=검색"},
        {"type": "web", "action": "read", "selector": "#result", "var": "결과"},
        {"type": "return", "value": {"var": "결과"}},
    ], web)
    assert res.status == "ok" and res.value == "결과 3건"
    assert ("fill", "input[name=q]", "매크로") in web.calls


def test_web_condition_branches():
    web = FakeWeb({"text=로그아웃": ""})
    res = run([{"type": "if", "cond": {"web": {"selector": "text=로그아웃"}},
                "then": [{"type": "return", "value": "로그인됨"}], "else": [{"type": "return", "value": "아님"}]}], web)
    assert res.value == "로그인됨"
    res = run([{"type": "if", "cond": {"not": {"web": {"selector": "text=없음"}}},
                "then": [{"type": "return", "value": "없음"}]}], FakeWeb())
    assert res.value == "없음"


def test_missing_element_fails_or_skips():
    res = run([{"type": "web", "action": "click", "selector": "text=없음"}], FakeWeb())
    assert res.status == "failed" and "요소 없음" in res.error["reason"]
    res = run([{"type": "web", "action": "click", "selector": "text=없음", "on_fail": "skip"},
               {"type": "return", "value": "넘어감"}], FakeWeb())
    assert res.value == "넘어감"


def test_password_field_blocked():
    web = FakeWeb({"#pw": ""}, password_fields={"#pw"})
    res = run([{"type": "web", "action": "fill", "selector": "#pw", "text": "secret"}], web)
    assert res.status == "failed" and "막음" in res.error["reason"]


def test_web_selector_fills_variables():
    from engine import Runner, new_macro
    from engine.backends import FakeClock, FakeInput, FakeVision
    calls = []

    class W:
        def run(self, action, **kw):
            calls.append((action, kw["selector"], kw["url"]))
            return {"ok": True, "value": "x"}

    clock = FakeClock()
    m = new_macro("w", [{"type": "set", "var": "행", "value": 3},
                        {"type": "web", "action": "read", "selector": "tr:nth-child({행}) td{x}", "var": "v"},
                        {"type": "web", "action": "goto", "url": "https://example.com/p/{행}"}])
    r = Runner(m, vision=FakeVision(clock), input=FakeInput(clock), clock=clock, web=W()).run()
    assert r.status == "ok"
    assert calls[0][1] == "tr:nth-child(3) td{x}" and calls[1][2] == "https://example.com/p/3"

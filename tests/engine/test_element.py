"""창 요소(버튼 이름) 대상 — 가짜 창으로, 실제 입력 없음."""
from engine import new_macro, validate_macro
from engine import win_uia
from tests.engine.test_runner import World


def el(name, **kw):
    return {"element": {"name": name, **kw}}


def test_click_element_center():
    w = World()
    w.window.elements = [{"name": "확인", "type": "button", "rect": [100, 200, 80, 30]}]
    res = w.run([{"type": "click", "target": el("확인", type="button")}])
    assert res.status == "ok"
    assert w.input.clicks() == [(140, 215)]


def test_element_index_and_offset():
    w = World()
    w.window.elements = [{"name": "삭제", "type": "button", "rect": [0, 0, 10, 10]},
                         {"name": "삭제", "type": "button", "rect": [100, 100, 10, 10]}]
    res = w.run([{"type": "click", "target": {"element": {"name": "삭제", "index": 1}, "offset": [3, 0]}}])
    assert res.status == "ok"
    assert w.input.clicks() == [(108, 105)]


def test_element_contains_and_wait_until_appears():
    w = World()
    w.clock.schedule(2.0, lambda: setattr(w.window, "elements",
                                          [{"name": "저장 완료(3)", "type": "text", "rect": [0, 0, 20, 20]}]))
    res = w.run([{"type": "wait", "until": {"exists": el("저장 완료", match="contains")}}])
    assert res.status == "ok"
    assert w.clock.now() >= 2.0


def test_element_condition_branch():
    w = World()
    w.window.elements = [{"name": "닫기", "type": "button", "rect": [0, 0, 10, 10]}]
    res = w.run([{"type": "if", "cond": {"exists": el("없는 버튼")},
                  "then": [{"type": "click", "target": el("닫기")}],
                  "else": [{"type": "set", "var": "x", "value": 1}]}])
    assert res.status == "ok"
    assert w.input.clicks() == []


def test_missing_element_fails_with_name():
    w = World()
    res = w.run([{"type": "click", "target": el("확인")}], settings={"timeout": 1})
    assert res.status == "failed"
    assert "확인" in str(res.error)


def test_validate_element_target():
    ok = new_macro("m", [{"type": "click", "target": el("확인", type="button", index=0)}])
    assert validate_macro(ok) == []
    bad = new_macro("m", [{"type": "click", "target": {"element": {"type": "zzz"}}}])
    errs = " ".join(validate_macro(bad))
    assert "name" in errs and "type" in errs
    bad2 = new_macro("m", [{"type": "click", "target": {"element": {"name": "a", "x": 1}}}])
    assert any("모르는 키" in e for e in validate_macro(bad2))


def test_check_spec_and_label():
    assert win_uia.check_spec({"id": "btnOk"}) == []
    assert win_uia.check_spec({"name": "a", "index": -1})
    assert win_uia.label({"name": "확인", "type": "button", "index": 2}) == "'확인' button #2"


def test_background_element_click_uses_invoke_not_mouse():
    """11-23: '뒤에서 실행'에서 창 요소는 마우스 메시지 대신 요소 누르기(스토어 앱 계산기가 마우스 메시지를 자주 무시)."""
    from engine import new_macro
    from tests.engine.test_runner import _bg_world
    w, bg = _bg_world()
    w.window.elements = [{"name": "더하기", "type": "button", "rect": [100, 200, 80, 30]}]
    invoked = []
    w.window.invoke_element = lambda spec, open_=False: invoked.append(spec) or True
    res = w.runner(new_macro("m", [{"type": "click", "target": el("더하기", type="button")}],
                             window={"title": "x", "background": True})).run()
    assert res.status == "ok" and invoked == [{"name": "더하기", "type": "button"}]
    assert bg.events == [] and w.input.events == []          # 마우스는 안 씀
    assert any(e.get("kind") == "invoke" for e in w.events)


def test_background_element_click_falls_back_to_mouse_when_invoke_fails():
    from engine import new_macro
    from tests.engine.test_runner import _bg_world
    w, bg = _bg_world()
    w.window.elements = [{"name": "확인", "type": "button", "rect": [100, 200, 80, 30]}]
    res = w.runner(new_macro("m", [{"type": "click", "target": el("확인", type="button")}],
                             window={"title": "x", "background": True})).run()
    assert res.status == "ok" and [e[1] for e in bg.events] == ["move", "down", "up"]


def test_type_text_into_element_uses_value_without_keyboard():
    """11-23: 뒤에서 뜬 대화상자 입력 칸은 키 신호가 다른 곳으로 가서 → 칸을 정해 주면 그 칸에 바로 넣음."""
    w = World()
    w.window.elements = [{"name": "파일 이름:", "type": "edit", "rect": [10, 20, 100, 20]}]
    w.window.values = {}
    res = w.run([{"type": "type_text", "target": el("파일 이름:", type="edit"), "text": "a.txt"}])
    assert res.status == "ok" and w.window.values == {"파일 이름:": "a.txt"}
    assert w.input.events == []                                   # 키보드·마우스 안 씀


def test_type_text_into_element_falls_back_to_click_and_keys():
    w = World()
    w.window.elements = [{"name": "이름", "type": "edit", "rect": [10, 20, 100, 20]}]
    res = w.run([{"type": "type_text", "target": el("이름", type="edit"), "text": "가"}])
    assert res.status == "ok" and w.input.clicks() == [(60, 30)]


def test_type_text_target_must_be_element():
    errs = validate_macro(new_macro("m", [{"type": "type_text", "target": {"point": [1, 2]}, "text": "x"}]))
    assert errs


def test_background_double_click_on_element_opens():
    from engine import new_macro
    from tests.engine.test_runner import _bg_world
    w, bg = _bg_world()
    w.window.elements = [{"name": "새 통합 문서", "type": "listitem", "rect": [100, 200, 80, 30]}]
    calls = []
    w.window.invoke_element = lambda spec, open_=False: calls.append(open_) or True
    res = w.runner(new_macro("m", [{"type": "click", "target": el("새 통합 문서", type="listitem"), "count": 2}],
                             window={"title": "x", "background": True})).run()
    assert res.status == "ok" and calls == [True] and bg.events == []


def test_background_minimized_mouse_fallback_fails_clearly():
    from engine import new_macro
    from tests.engine.test_runner import _bg_world
    w, bg = _bg_world()
    w.window.elements = [{"name": "확인", "type": "button", "rect": [100, 200, 80, 30]}]
    w.window.is_minimized = lambda: True
    res = w.runner(new_macro("m", [{"type": "click", "target": el("확인", type="button")}],
                             window={"title": "x", "background": True})).run()
    assert res.status == "failed" and "최소화" in res.error["reason"]

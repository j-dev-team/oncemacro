"""
실행 의미 테스트 (docs/engine_v2_design.md §6). 가짜 시계·화면·입력으로 화면 없이 돈다.
"""
import threading

import pytest

from engine import MacroError, Runner, new_macro, validate_macro
from engine.backends import FakeClock, FakeInput, FakeVision, FakeWindow
from engine.library import DictLibrary

IMG = "test/btn.png"


class World:
    def __init__(self, origin=(0, 0)):
        self.clock = FakeClock()
        self.vision = FakeVision(self.clock)
        self.input = FakeInput(self.clock)
        self.window = FakeWindow(origin)
        self.library = DictLibrary()
        self.events = []

    def runner(self, macro):
        return Runner(macro, vision=self.vision, input=self.input, clock=self.clock,
                      library=self.library, window_factory=lambda cfg: self.window,
                      on_event=self.events.append)

    def run(self, steps, **fields):
        return self.runner(new_macro("m", steps, **fields)).run()


def click_img(image=IMG, **kw):
    return {"type": "click", "target": {"image": image}, **kw}


# ---------------------------------------------------------------- click

def test_click_image_input_sequence_and_timing():
    w = World()
    w.vision.show(IMG, (100, 200))
    res = w.run([click_img()])
    assert res.status == "ok"
    kinds = [e[1] for e in w.input.events]
    assert kinds == ["move", "down", "up"]
    t_move, t_down, t_up = (e[0] for e in w.input.events)
    # stable_frames=2 → 한 폴링(0.1s) 더 확인, settle 0.15s
    assert t_move == pytest.approx(0.25)
    assert t_down - t_move == pytest.approx(0.04)   # move_settle_ms
    assert t_up - t_down == pytest.approx(0.06)     # click_hold_ms
    assert w.input.clicks() == [(100, 200)]


def test_click_waits_for_image_to_appear_and_stabilize():
    w = World()
    w.vision.show(IMG, (10, 10), start=3.0)
    res = w.run([click_img()])
    assert res.status == "ok"
    assert w.input.events[0][0] >= 3.0 + 0.1 + 0.15 - 1e-9


def test_moving_image_is_not_clicked_until_it_stops():
    w = World()
    # 0~1초 동안 위치가 매 프레임 바뀜 (애니메이션), 1초부터 정지
    for i in range(10):
        w.vision.show(IMG, (100 + i * 20, 100), start=i * 0.1 - 0.05, end=(i + 1) * 0.1 - 0.05)
    w.vision.show(IMG, (500, 100), start=0.95)
    w.run([click_img()])
    assert w.input.clicks() == [(500, 100)]


def test_condition_sees_bobbing_indicator_but_click_waits_for_stable():
    """▼ 처럼 프레임마다 위치가 크게 바뀌는 표시: 조건(if)은 바로 참, 클릭은 멈출 때까지 기다림."""
    w = World()
    for i in range(40):                         # 0~4초 동안 20px 씩 오르내림
        w.vision.show(IMG, (100, 100 + (i % 2) * 20), start=i * 0.1 - 0.05, end=(i + 1) * 0.1 - 0.05)
    w.vision.show(IMG, (100, 100), start=3.95)  # 4초부터 정지
    res = w.run([{"type": "if", "cond": {"exists": {"image": IMG}},
                  "then": [{"type": "key", "keys": "y"}], "else": [{"type": "key", "keys": "n"}]},
                 click_img()])
    assert res.status == "ok"
    keys = [e for e in w.input.events if e[1] == "key_down"]
    assert keys[0][2] == "y" and keys[0][0] < 1.0      # 조건은 즉시 참
    click_t = next(e[0] for e in w.input.events if e[1] == "down")
    assert click_t >= 4.0                               # 클릭은 멈춘 뒤


def test_small_jitter_within_stable_px_is_clickable():
    w = World()
    for i in range(10):                         # 4px 흔들림 → 허용 오차(6px) 안
        w.vision.show(IMG, (100, 100 + (i % 2) * 4), start=i * 0.1 - 0.05, end=(i + 1) * 0.1 - 0.05)
    res = w.run([click_img(timeout=0.8)], on_iteration_fail={"action": "stop"})
    assert res.status == "ok"


def test_click_timeout_fails_with_path_and_best_score():
    w = World()
    w.vision.show(IMG, (1, 1), score=0.71)
    res = w.run([{"type": "delay", "seconds": 0}, click_img(timeout=2)],
                on_iteration_fail={"action": "stop"})
    assert res.status == "failed"
    assert res.error["path"] == "steps[1]"
    assert res.error["type"] == "click"
    assert "0.71" in res.error["reason"] and "0.80" in res.error["reason"]
    assert w.input.events == []


def test_timeout_null_waits_forever():
    w = World()
    w.vision.show(IMG, (5, 5), start=5000)
    res = w.run([click_img(timeout=None)])
    assert res.status == "ok"
    assert w.input.clicks() == [(5, 5)]


def test_window_origin_applies_to_point_and_region():
    w = World(origin=(1000, 500))
    w.vision.show(IMG, (1050, 560))          # 화면 절대좌표
    res = w.run([
        {"type": "click", "target": {"image": IMG, "region": [0, 0, 100, 100]}},
        {"type": "click", "target": {"point": [10, 20]}},
    ], window={"title": "game"})
    assert res.status == "ok"
    assert w.input.clicks() == [(1050, 560), (1010, 520)]
    assert w.window.activated == 1


def test_window_activated_before_first_screen_check():
    """다른 창에 가려진 채로 화면을 찾지 않게, 첫 화면 확인 전에 대상 창을 앞으로."""
    w = World()
    seen = {}
    orig = w.window.activate

    def activate():
        seen["match_calls_at_activate"] = w.vision.match_calls
        orig()

    w.window.activate = activate
    w.vision.show(IMG, (5, 5))
    res = w.run([{"type": "wait", "until": {"exists": {"image": IMG}}}], window={"title": "game"})
    assert res.status == "ok"
    assert seen["match_calls_at_activate"] == 0 and w.window.activated == 1


def test_region_excludes_match_outside():
    w = World()
    w.vision.show(IMG, (500, 500))
    res = w.run([{"type": "click", "target": {"image": IMG, "region": [0, 0, 100, 100]},
                  "timeout": 1}], on_iteration_fail={"action": "stop"})
    assert res.status == "failed"


def test_offset_and_double_click():
    w = World()
    w.vision.show(IMG, (100, 100))
    w.run([{"type": "click", "target": {"image": IMG, "offset": [5, -5]}, "count": 2}])
    assert [e[1] for e in w.input.events] == ["move", "down", "up", "down", "up"]
    assert w.input.pos == (105, 95)


def test_verify_reclicks_until_condition():
    w = World()
    w.vision.show(IMG, (50, 50))
    clicks = []

    def on_click(pos, button):
        clicks.append(pos)
        if len(clicks) == 2:                 # 두 번째 클릭에서야 반응
            w.vision.hide(IMG)

    w.input.on_click = on_click
    res = w.run([click_img(verify={"cond": {"gone": {"image": IMG}}, "timeout": 1, "retries": 3})])
    assert res.status == "ok"
    assert len(clicks) == 2


def test_verify_exhausted_fails():
    w = World()
    w.vision.show(IMG, (50, 50))
    res = w.run([click_img(verify={"cond": {"gone": {"image": IMG}}, "timeout": 0.5, "retries": 1})],
                on_iteration_fail={"action": "stop"})
    assert res.status == "failed"
    assert len(w.input.clicks()) == 2
    assert "확인 2회 실패" in res.error["reason"]


# ---------------------------------------------------------------- wait / gone / remember

def test_wait_gone_requires_continuous_absence():
    w = World()
    w.vision.show(IMG, (1, 1), end=1.0)
    w.vision.show(IMG, (1, 1), start=1.5, end=2.0)   # 잠깐 다시 보임
    res = w.run([{"type": "wait", "until": {"gone": {"image": IMG}, "for": 1.0}},
                 {"type": "key", "keys": "f"}])
    assert res.status == "ok"
    assert w.input.events[0][0] >= 3.0


def test_remember_mouse_and_move_back():
    w = World()
    w.input.pos = (7, 8)
    w.vision.show(IMG, (100, 100))
    res = w.run([{"type": "remember", "var": "p"}, click_img(),
                 {"type": "move", "target": {"var": "p"}}])
    assert res.status == "ok"
    assert w.input.pos == (7, 8)


def test_missing_var_fails_clearly():
    w = World()
    res = w.run([{"type": "move", "target": {"var": "nope"}}], on_iteration_fail={"action": "stop"})
    assert res.status == "failed"
    assert "nope" in res.error["reason"]


# ---------------------------------------------------------------- on_fail

def test_on_fail_skip_continues():
    w = World()
    res = w.run([click_img(timeout=0.5, on_fail="skip"), {"type": "key", "keys": "a"}])
    assert res.status == "ok"
    assert ("key_down" in [e[1] for e in w.input.events])
    assert any(e["event"] == "step_end" and e["status"] == "skipped" for e in w.events)


def test_on_fail_retry_then_succeeds():
    w = World()
    w.vision.show(IMG, (1, 1), start=1.5)
    res = w.run([click_img(timeout=1, on_fail="retry", retries=2)])
    assert res.status == "ok"
    assert sum(e["event"] == "step_retry" for e in w.events) == 1


def test_on_fail_return_value():
    w = World()
    res = w.run([click_img(timeout=0.2, on_fail={"return": "no_button"}), {"type": "key", "keys": "a"}])
    assert res.status == "ok" and res.value == "no_button"
    assert w.input.events == []


def test_skip_is_never_implicit_failure_propagates_out_of_if():
    w = World()
    res = w.run([{"type": "if", "cond": {"var": "x", "is_set": False},
                  "then": [click_img(timeout=0.2)]}],
                on_iteration_fail={"action": "stop"})
    assert res.status == "failed"
    assert res.error["path"] == "steps[0].then[0]"


# ---------------------------------------------------------------- if

def test_if_then_else():
    w = World()
    w.vision.show(IMG, (1, 1))
    steps = [{"type": "if", "cond": {"exists": {"image": IMG}},
              "then": [{"type": "key", "keys": "y"}], "else": [{"type": "key", "keys": "n"}]}]
    w.run(steps)
    assert ("key_down", "y") in [e[1:] for e in w.input.events]

    w2 = World()
    w2.run(steps)
    assert ("key_down", "n") in [e[1:] for e in w2.input.events]


def test_if_within_waits():
    w = World()
    w.vision.show(IMG, (1, 1), start=2.0)
    w.run([{"type": "if", "cond": {"exists": {"image": IMG}}, "within": 3,
            "then": [{"type": "key", "keys": "y"}]}])
    assert ("key_down", "y") in [e[1:] for e in w.input.events]


# ---------------------------------------------------------------- repeat

def _keys(w):
    return [e[2] for e in w.input.events if e[1] == "key_down"]


def test_repeat_times():
    w = World()
    w.run([{"type": "repeat", "times": 3, "steps": [{"type": "key", "keys": "a"}]}])
    assert _keys(w) == ["a", "a", "a"]


def test_repeat_times_inner_failure_fails_immediately():
    w = World()
    res = w.run([{"type": "repeat", "times": 5, "steps": [
        {"type": "key", "keys": "a"}, click_img(timeout=0.2)]}],
        on_iteration_fail={"action": "stop"})
    assert res.status == "failed"
    assert res.error["path"] == "steps[0].steps[1]"
    assert _keys(w) == ["a"]


def test_wait_timeout_fails_with_best_score():
    w = World()
    w.vision.show(IMG, (1, 1), score=0.66)
    res = w.run([{"type": "wait", "until": {"exists": {"image": IMG}}, "timeout": 1}],
                on_iteration_fail={"action": "stop"})
    assert res.status == "failed" and res.error["type"] == "wait"
    assert "1초 대기 초과" in res.error["reason"] and "0.66" in res.error["reason"]


def test_repeat_while_checks_before_zero_iterations():
    w = World()
    w.run([{"type": "repeat", "while": {"exists": {"image": IMG}},
            "steps": [{"type": "key", "keys": "a"}]}])
    assert _keys(w) == []


def test_repeat_until_checks_after_each_iteration():
    w = World()
    w.vision.show(IMG, (1, 1))   # 처음부터 참이어도 한 번은 실행
    w.run([{"type": "repeat", "until": {"exists": {"image": IMG}},
            "steps": [{"type": "key", "keys": "a"}]}])
    assert _keys(w) == ["a"]


def test_repeat_until_condition_changes_by_world():
    w = World()
    count = {"n": 0}

    def on_click(pos, b):
        count["n"] += 1
        if count["n"] == 4:
            w.vision.show("done.png", (0, 0), start=w.clock.now())

    w.input.on_click = on_click
    res = w.run([{"type": "repeat", "until": {"exists": {"image": "done.png"}}, "max_times": 10,
                  "steps": [{"type": "click", "target": {"point": [1, 1]}}]}])
    assert res.status == "ok"
    assert count["n"] == 4


def test_repeat_max_times_exceeded_fails():
    w = World()
    res = w.run([{"type": "repeat", "until": {"exists": {"image": IMG}}, "max_times": 3,
                  "steps": [{"type": "key", "keys": "a"}]}], on_iteration_fail={"action": "stop"})
    assert res.status == "failed"
    assert _keys(w) == ["a"] * 3
    assert "최대 반복 3회" in res.error["reason"]


def test_repeat_forever_break_and_continue():
    w = World()
    steps = [{"type": "repeat", "forever": True, "steps": [
        {"type": "set_result", "value": 0},
        {"type": "if", "cond": {"exists": {"image": "stop.png"}}, "then": [{"type": "break"}]},
        {"type": "if", "cond": {"exists": {"image": "skip.png"}}, "then": [{"type": "continue"}]},
        {"type": "key", "keys": "a"},
        {"type": "delay", "seconds": 1},
    ]}]
    w.vision.show("skip.png", (0, 0), start=2.0, end=4.0)
    w.vision.show("stop.png", (0, 0), start=6.0)
    res = w.run(steps)
    assert res.status == "ok"
    assert 2 <= len(_keys(w)) <= 6


# ---------------------------------------------------------------- 매크로 반복 / 회차 실패

def test_fixed_repeat_continues_after_iteration_failure():
    """v1 버그 수정: 횟수 반복이 한 번 실패로 끝나지 않음."""
    w = World()
    w.vision.show(IMG, (1, 1), start=0, end=0.5)       # 첫 회차만 있음
    w.vision.show(IMG, (1, 1), start=2.5)               # 세 번째 회차 이후 다시 있음
    res = w.run([click_img(timeout=0.5)], repeat={"times": 3},
                on_iteration_fail={"action": "retry", "max_consecutive": 3, "delay": 0.5})
    assert res.status == "ok"
    assert res.iterations == 3              # 성공 3회를 채움
    assert res.failed_iterations >= 1       # 실패한 회차는 다시 돎


def test_consecutive_failures_stop_macro():
    w = World()
    res = w.run([click_img(timeout=0.2)], repeat={"forever": True},
                on_iteration_fail={"action": "retry", "max_consecutive": 3, "delay": 0.1})
    assert res.status == "failed"
    assert res.iterations == 0 and res.failed_iterations == 3
    assert "연속 3회 실패" in res.error["reason"]


def test_single_run_failure_is_reported_as_failed():
    w = World()
    res = w.run([click_img(timeout=0.2)])     # 기본: retry 3회 후 실패
    assert res.status == "failed" and res.failed_iterations == 3


def test_on_iteration_fail_stop():
    w = World()
    res = w.run([click_img(timeout=0.2)], repeat={"times": 5}, on_iteration_fail={"action": "stop"})
    assert res.status == "failed" and res.failed_iterations == 1


def test_vars_reset_each_iteration():
    w = World()
    res = w.run([{"type": "if", "cond": {"var": "seen", "is_set": True},
                  "then": [{"type": "stop", "reason": "변수가 남아 있음"}]},
                 {"type": "remember", "var": "seen"}], repeat={"times": 3})
    assert res.status == "ok"


# ---------------------------------------------------------------- return / stop / result

def test_return_ends_whole_macro_with_value():
    w = World()
    res = w.run([{"type": "key", "keys": "a"}, {"type": "return", "value": 7},
                 {"type": "key", "keys": "b"}], repeat={"times": 5})
    assert res.status == "ok" and res.value == 7 and _keys(w) == ["a"]


def test_set_result_keeps_running():
    w = World()
    res = w.run([{"type": "set_result", "value": "x"}, {"type": "key", "keys": "a"}])
    assert res.value == "x" and _keys(w) == ["a"]


def test_return_and_set_result_can_pass_a_variable():
    w = World()
    res = w.run([{"type": "set", "var": "r", "value": "보냄"}, {"type": "return", "value": {"var": "r"}}])
    assert res.value == "보냄"
    res = w.run([{"type": "set", "var": "n", "add": 2}, {"type": "set_result", "value": {"var": "n"}}])
    assert res.value == 2


def test_stop_step_fails_without_retry():
    w = World()
    res = w.run([{"type": "stop", "reason": "그만"}], repeat={"forever": True})
    assert res.status == "failed" and res.iterations == 0 and res.error["reason"] == "그만"


# ---------------------------------------------------------------- call (체인 대체)

def test_call_result_drives_if():
    w = World()
    w.library.add(new_macro("sub", [{"type": "return", "value": 1}]))
    w.library.add(new_macro("a", [{"type": "key", "keys": "a"}]))
    w.library.add(new_macro("b", [{"type": "key", "keys": "b"}]))
    res = w.run([{"type": "call", "macro": "sub", "result_var": "r"},
                 {"type": "if", "cond": {"var": "r", "eq": 1},
                  "then": [{"type": "call", "macro": "a"}], "else": [{"type": "call", "macro": "b"}]}])
    assert res.status == "ok" and _keys(w) == ["a"]


def test_call_failure_propagates():
    w = World()
    w.library.add(new_macro("sub", [click_img(timeout=0.1)], on_iteration_fail={"action": "stop"}))
    res = w.run([{"type": "call", "macro": "sub"}], on_iteration_fail={"action": "stop"})
    assert res.status == "failed" and "'sub' 실패" in res.error["reason"]


def test_call_recursion_and_missing():
    w = World()
    w.library.add(new_macro("m", [{"type": "call", "macro": "m"}]))
    res = w.runner(w.library.load("m")).run()
    assert res.status == "failed" and "순환" in res.error["reason"]
    res = w.run([{"type": "call", "macro": "없음"}], on_iteration_fail={"action": "stop"})
    assert "없음" in res.error["reason"]


# ---------------------------------------------------------------- 정지

def test_stop_event_interrupts_infinite_wait():
    w = World()
    stop = threading.Event()
    w.clock.schedule(12.34, stop.set)
    res = w.runner(new_macro("m", [click_img(timeout=None)], repeat={"forever": True})).run(stop)
    assert res.status == "stopped"
    assert w.clock.now() < 12.34 + 0.2


def test_backend_exception_becomes_step_failure():
    w = World()

    def boom(*a):
        raise OSError("캡처 실패")

    w.vision.match = boom
    res = w.run([click_img(on_fail="skip"), {"type": "key", "keys": "a"}])
    assert res.status == "ok" and _keys(w) == ["a"]


# ---------------------------------------------------------------- key / drag

def test_key_combo_order():
    w = World()
    w.run([{"type": "key", "keys": "Ctrl+Shift+S"}])
    assert [e[1:] for e in w.input.events] == [
        ("key_down", "ctrl"), ("key_down", "shift"), ("key_down", "s"),
        ("key_up", "s"), ("key_up", "shift"), ("key_up", "ctrl")]


def test_drag():
    w = World()
    w.run([{"type": "drag", "from": {"point": [0, 0]}, "to": {"point": [100, 50]}, "duration_ms": 160}])
    kinds = [e[1] for e in w.input.events]
    assert kinds[0] == "move" and kinds[1] == "down" and kinds[-1] == "up"
    assert w.input.pos == (100, 50)


# ---------------------------------------------------------------- run_step (MCP용)

def test_run_step_keeps_vars_between_calls():
    w = World()
    w.input.pos = (3, 4)
    r = w.runner(new_macro("m", []))
    ctx = r.new_context()
    assert r.run_step({"type": "remember", "var": "p"}, ctx)["status"] == "ok"
    out = r.run_step({"type": "click", "target": {"var": "p"}}, ctx)
    assert out["status"] == "ok" and w.input.clicks() == [(3, 4)]
    with pytest.raises(MacroError):
        r.run_step({"type": "click"}, ctx)


# ---------------------------------------------------------------- 검증

@pytest.mark.parametrize("steps, needle", [
    ([{"type": "clik", "target": {"point": [1, 1]}}], "알 수 없는 스텝"),
    ([{"type": "click", "target": {"point": [1, 1]}, "tiemout": 3}], "tiemout"),
    ([{"type": "click", "target": {"image": "a.png", "point": [1, 1]}}], "정확히 하나"),
    ([{"type": "break"}], "repeat·for_each 안에서만"),
    ([{"type": "repeat", "times": 2, "until": {"var": "x", "eq": 1}, "steps": []}], "정확히 하나"),
    ([{"type": "click", "target": {"image": "a.png", "region": [0, 0, 0, 10]}}], "0보다"),
    ([{"type": "wait", "until": {"exists": {"color": [300, 0, 0], "at": [1, 1]}}}], "0~255"),
    ([{"type": "delay"}], "seconds"),
    ([{"type": "wait", "until": {"exists": {"var": "p"}}}], "is_set"),
])
def test_validation_errors(steps, needle):
    errs = validate_macro(new_macro("m", steps))
    assert any(needle in e for e in errs), errs


def test_validation_ok_for_design_example():
    m = new_macro("동광석 캐기", [
        {"type": "remember", "var": "start_pos", "what": "mouse"},
        {"type": "click", "target": {"image": "mobinogi/가방.png", "region": [718, 881, 306, 155]}},
        {"type": "delay", "seconds": 1.0},
        {"type": "move", "target": {"var": "start_pos"}},
        {"type": "wait", "until": {"gone": {"image": "mobinogi/정지버튼.png",
                                            "region": [346, 795, 260, 185]}, "for": 3.0},
         "timeout": None},
    ], repeat={"forever": True})
    assert validate_macro(m) == []


# ---------------------------------------------------------------- 영역 안 색 존재

def test_color_region_condition_counts_pixels():
    w = World()
    w.vision.add_blob((0, 180, 230), (150, 200), 40)          # 하늘색 글자 40픽셀
    cond = {"exists": {"color": [0, 180, 230], "region": [100, 190, 200, 20],
                       "tolerance": 20, "min_pixels": 25}}
    res = w.run([{"type": "if", "cond": cond, "then": [{"type": "key", "keys": "y"}],
                  "else": [{"type": "key", "keys": "n"}]}])
    assert res.status == "ok" and _keys(w) == ["y"]
    w2 = World()
    w2.vision.add_blob((0, 180, 230), (150, 200), 10)         # 너무 적음
    w2.run([{"type": "if", "cond": cond, "then": [{"type": "key", "keys": "y"}],
             "else": [{"type": "key", "keys": "n"}]}])
    assert _keys(w2) == ["n"]


def test_color_region_validation():
    bad = new_macro("m", [{"type": "wait", "until": {"exists": {"color": [1, 2, 3]}}}])
    assert any("at" in e and "region" in e for e in validate_macro(bad))
    bad2 = new_macro("m", [{"type": "wait", "until": {"exists": {"color": [1, 2, 3], "at": [1, 1],
                                                                  "min_pixels": 3}}}])
    assert any("min_pixels" in e for e in validate_macro(bad2))


def test_color_blob_clicks_thickest_blob():
    w = World()
    w.vision.add_color_blob((236, 229, 211), (60, 300), 6)      # 반쯤 가려진 말풍선
    w.vision.add_color_blob((236, 229, 211), (180, 450), 15)    # 온전한 말풍선
    w.vision.add_color_blob((236, 229, 211), (500, 450), 20)    # 영역 밖
    res = w.run([{"type": "click", "target": {"color": [236, 229, 211], "region": [0, 280, 340, 240],
                                              "tolerance": 14, "blob_depth": 10}, "timeout": 1}])
    assert res.status == "ok" and w.input.clicks() == [(180, 450)]


def test_color_blob_too_thin_is_absent():
    w = World()
    w.vision.add_color_blob((236, 229, 211), (60, 300), 4)      # 가는 크림색 선뿐
    res = w.run([{"type": "click", "target": {"color": [236, 229, 211], "region": [0, 280, 340, 240],
                                              "tolerance": 14, "blob_depth": 10},
                  "timeout": 0.5, "on_fail": "skip"}])
    assert res.status == "ok" and w.input.clicks() == []


def test_color_blob_validation():
    ok = new_macro("m", [{"type": "click", "target": {"color": [1, 2, 3], "region": [0, 0, 9, 9],
                                                      "blob_depth": 5}}])
    assert validate_macro(ok) == []
    bad = new_macro("m", [{"type": "click", "target": {"color": [1, 2, 3], "at": [1, 1], "blob_depth": 5}}])
    assert any("blob_depth" in e for e in validate_macro(bad))
    bad2 = new_macro("m", [{"type": "click", "target": {"color": [1, 2, 3], "region": [0, 0, 9, 9],
                                                        "blob_depth": 5, "min_pixels": 3}}])
    assert any("blob_depth" in e for e in validate_macro(bad2))


def test_vivid_region_detects_colored_text_not_gray():
    cond = {"exists": {"vivid": True, "region": [100, 190, 300, 30], "min_pixels": 200}}
    steps = [{"type": "if", "cond": cond, "then": [{"type": "key", "keys": "y"}],
              "else": [{"type": "key", "keys": "n"}]}]
    w = World()
    w.vision.add_blob((39, 200, 209), (200, 200), 850)      # 하늘색 이름
    w.run(steps)
    assert _keys(w) == ["y"]
    w2 = World()
    w2.vision.add_blob((60, 50, 45), (200, 200), 900)       # 어두운(일반) 이름
    w2.vision.add_blob((220, 180, 60), (380, 205), 69)      # 가격 끝 조금
    w2.run(steps)
    assert _keys(w2) == ["n"]


def test_vivid_hues_excludes_green():
    cond = {"exists": {"vivid": True, "region": [100, 190, 300, 30], "min_pixels": 200,
                       "hues": [[85, 110], [125, 180], [0, 10], [12, 35]]}}
    steps = [{"type": "if", "cond": cond, "then": [{"type": "key", "keys": "y"}],
              "else": [{"type": "key", "keys": "n"}]}]
    w = World()
    w.vision.add_blob((90, 210, 60), (200, 200), 1000)       # 초록 이름(고급) → 제외
    w.run(steps)
    assert _keys(w) == ["n"]
    w2 = World()
    w2.vision.add_blob((39, 200, 209), (200, 200), 850)      # 하늘색 → 포함
    w2.run(steps)
    assert _keys(w2) == ["y"]


def test_set_counter_and_condition():
    w = World()
    steps = [{"type": "repeat", "times": 5, "steps": [
                 {"type": "set", "var": "n", "add": 1},
                 {"type": "if", "cond": {"var": "n", "ge": 3}, "then": [{"type": "break"}]}]},
             {"type": "if", "cond": {"var": "n", "eq": 3}, "then": [{"type": "key", "keys": "y"}],
              "else": [{"type": "key", "keys": "n"}]},
             {"type": "set", "var": "n", "value": 0},
             {"type": "if", "cond": {"var": "n", "eq": 0}, "then": [{"type": "key", "keys": "z"}]}]
    res = w.run(steps)
    assert res.status == "ok" and _keys(w) == ["y", "z"]


def test_set_validation():
    assert validate_macro(new_macro("m", [{"type": "set", "var": "a", "value": 1}])) == []
    assert validate_macro(new_macro("m", [{"type": "set", "var": "a"}]))
    assert validate_macro(new_macro("m", [{"type": "set", "var": "a", "value": 1, "add": 1}]))
    assert validate_macro(new_macro("m", [{"type": "set", "var": "a", "add": "x"}]))


# ---------------------------------------------------------------- 뒤에서 실행 (window.background)

class _BgInput(FakeInput):
    def __init__(self, clock):
        super().__init__(clock)
        self.released = 0

    def release(self):
        self.released += 1


def _bg_world():
    w = World()
    bg = _BgInput(w.clock)
    w.window = FakeWindow((100, 50), bg_input=bg)
    return w, bg


def test_background_uses_window_input_and_capture_without_activating():
    w, bg = _bg_world()
    w.vision.show(IMG, (130, 80))
    res = w.runner(new_macro("m", [click_img()], window={"title": "x", "background": True})).run()
    assert res.status == "ok"
    assert w.window.activated == 0                       # 창을 앞으로 안 가져옴
    assert [e[1] for e in bg.events] == ["move", "down", "up"] and bg.events[0][2:] == (130, 80)
    assert w.input.events == []                          # 진짜 입력은 안 씀
    assert bg.released == 1 and w.vision.bound is None   # 끝나면 뒤에서 실행·캡처 원래대로
    assert any(e["event"] == "background" for e in w.events)


def test_background_sub_macro_shares_and_parent_releases_once():
    w, bg = _bg_world()
    w.library.add(new_macro("sub", [{"type": "click", "target": {"point": [5, 5]}}],
                            window={"title": "x", "background": True}))
    res = w.runner(new_macro("m", [{"type": "call", "macro": "sub"},
                                   {"type": "click", "target": {"point": [1, 1]}}],
                             window={"title": "x", "background": True})).run()
    assert res.status == "ok" and bg.released == 1
    assert [e[2:] for e in bg.events if e[1] == "move"] == [(105, 55), (101, 51)]


def test_background_sub_macro_released_when_parent_is_foreground():
    w, bg = _bg_world()
    w.library.add(new_macro("sub", [{"type": "click", "target": {"point": [5, 5]}}],
                            window={"title": "x", "background": True}))
    res = w.run([{"type": "call", "macro": "sub"}])
    assert res.status == "ok" and bg.released == 1 and w.vision.bound is None


def test_background_unsupported_window_fails_clearly():
    w = World()
    res = w.run([{"type": "click", "target": {"point": [1, 1]}}], window={"title": "x", "background": True},
                on_iteration_fail={"action": "stop"})
    assert res.status == "failed" and "뒤에서 실행" in res.error["reason"]


def test_background_must_be_bool():
    from engine.model import validate_macro
    errs = validate_macro(new_macro("m", [], window={"title": "x", "background": "yes"}))
    assert any("background" in e for e in errs)


def test_background_rebinds_on_each_run_step():
    w, bg = _bg_world()
    r = w.runner(new_macro("m", [], window={"title": "x", "background": True}))
    ctx = r.new_context()
    for _ in range(2):
        assert r.run_step({"type": "click", "target": {"point": [1, 1]}}, ctx)["status"] == "ok"
        assert w.vision.bound is None
    assert bg.released == 2 and len([e for e in bg.events if e[1] == "down"]) == 2
    assert sum(1 for e in w.events if e["event"] == "background") == 2


# ---------------------------------------------------------------- for_each · anchor

def test_for_each_visits_matches_in_reading_order_with_anchor_regions():
    w = World(origin=(100, 50))
    # 카드 책갈피 3개: 2줄(y 차이 5 는 같은 줄), 읽는 순서 = (210,60)(260,63) 다음 줄 (205,200)
    for pos in [(260, 113), (205, 250), (210, 110)]:
        w.vision.show("card.png", pos)
    w.vision.show("tier.png", (250, 103))      # 두 번째 카드(260,113) 의 왼쪽 위에만 '티어'
    steps = [{"type": "for_each", "var": "카드", "target": {"image": "card.png", "region": [0, 0, 400, 300]},
              "steps": [{"type": "if", "cond": {"exists": {"image": "tier.png", "anchor": "카드",
                                                            "region": [-15, -15, 20, 20]}},
                         "then": [{"type": "click", "target": {"point": [0, 20], "anchor": "카드"}},
                                  {"type": "break"}]}]}]
    res = w.run(steps)
    assert res.status == "ok"
    downs = [e for e in w.input.events if e[1] == "move"]
    assert downs[-1][2:] == (260, 133)


def test_for_each_continue_and_order():
    w = World()
    for pos in [(50, 10), (10, 12), (30, 100)]:
        w.vision.show("c.png", pos)
    steps = [{"type": "for_each", "var": "p", "target": {"image": "c.png"},
              "steps": [{"type": "click", "target": {"var": "p"}}]}]
    w.run(steps)
    assert [e[2:] for e in w.input.events if e[1] == "move"] == [(10, 12), (50, 10), (30, 100)]


def test_for_each_reverse_visits_from_last():
    w = World()
    for pos in [(50, 10), (10, 12), (30, 100)]:
        w.vision.show("c.png", pos)
    steps = [{"type": "for_each", "var": "p", "target": {"image": "c.png"}, "reverse": True,
              "steps": [{"type": "click", "target": {"var": "p"}}]}]
    w.run(steps)
    assert [e[2:] for e in w.input.events if e[1] == "move"] == [(30, 100), (50, 10), (10, 12)]


def test_for_each_reverse_must_be_bool():
    from engine.model import validate_macro
    errs = validate_macro(new_macro("m", [{"type": "for_each", "var": "p", "target": {"image": "c.png"},
                                           "reverse": "yes", "steps": []}]))
    assert any("reverse" in e for e in errs)


def test_anchor_requires_variable():
    w = World()
    res = w.run([{"type": "click", "target": {"point": [1, 1], "anchor": "없음"}}],
                on_iteration_fail={"action": "stop"})
    assert res.status == "failed" and "기준 변수" in res.error["reason"]


# ---------------------------------------------------------------- launch · close_window · wait_window

def test_close_launch_wait_window():
    w = World()
    launched = []
    r = Runner(new_macro("m", [{"type": "close_window", "timeout": 5},
                               {"type": "launch", "target": "steam://x"},
                               {"type": "wait_window", "timeout": 30}],
                         window={"title": "x"}),
               vision=w.vision, input=w.input, clock=w.clock, library=w.library,
               window_factory=lambda cfg: w.window, launcher=lambda t: (launched.append(t), setattr(w.window, "open", True)))
    res = r.run()
    assert res.status == "ok" and w.window.closed == 1 and launched == ["steam://x"]


def test_wait_window_times_out():
    w = World()
    w.window.open = False
    res = w.run([{"type": "wait_window", "timeout": 5}], window={"title": "x"},
                on_iteration_fail={"action": "stop"})
    assert res.status == "failed" and "창이 안 생김" in res.error["reason"]


def test_global_vars_shared_across_calls_and_iterations():
    """'전역_' 변수는 부른 매크로와 반복 회차 사이에 유지, 일반 변수는 공유 안 함(11-15 빈 분류 건너뛰기용)."""
    w = World()
    w.library.add(new_macro("sub", [{"type": "set", "var": "전역_n", "add": 1},
                                    {"type": "set", "var": "보통", "value": 5}]))
    w.library.add(new_macro("a", [{"type": "key", "keys": "a"}]))
    res = w.run([{"type": "call", "macro": "sub"},
                 {"type": "call", "macro": "sub"},
                 {"type": "if", "cond": {"all": [{"var": "전역_n", "eq": 2}, {"var": "보통", "is_set": False}]},
                  "then": [{"type": "call", "macro": "a"}]}])
    assert res.status == "ok" and _keys(w) == ["a"]
    w2 = World()
    res = w2.run([{"type": "set", "var": "전역_k", "add": 1},
                  {"type": "if", "cond": {"var": "전역_k", "ge": 3}, "then": [{"type": "return", "value": "셋"}]}],
                 repeat={"times": 5})
    assert res.value == "셋"


def test_set_now_and_compare_with_now():
    w = World()
    res = w.run([{"type": "set", "var": "t", "value": {"now": True}},
                 {"type": "delay", "seconds": 5},
                 {"type": "if", "cond": {"var": "t", "gt": {"now": True, "add": -3}},
                  "then": [{"type": "return", "value": "3초 안"}]},
                 {"type": "if", "cond": {"var": "t", "gt": {"now": True, "add": -10}},
                  "then": [{"type": "return", "value": "10초 안"}]},
                 {"type": "return", "value": "오래됨"}])
    assert res.value == "10초 안"
    w2 = World()
    res = w2.run([{"type": "if", "cond": {"var": "없음", "gt": {"now": True, "add": -10}},
                   "then": [{"type": "return", "value": "있음"}]}, {"type": "return", "value": "없음"}])
    assert res.value == "없음"


def test_set_and_compare_with_other_var():
    w = World()
    res = w.run([{"type": "set", "var": "a", "value": 3},
                 {"type": "set", "var": "b", "value": {"var": "a"}},
                 {"type": "if", "cond": {"var": "b", "eq": {"var": "a"}}, "then": [{"type": "return", "value": "같음"}]},
                 {"type": "return", "value": "다름"}])
    assert res.value == "같음"


def test_scroll_step_moves_then_wheels():
    w = World()
    w.vision.show(IMG, (100, 200))
    res = w.run([{"type": "scroll", "target": {"image": IMG}, "amount": -3}, {"type": "scroll", "amount": 2}])
    assert res.status == "ok"
    kinds = [e[1:] for e in w.input.events]
    assert ("move", 100, 200) in kinds and ("scroll", -3, False) in kinds and ("scroll", 2, False) in kinds


def test_menu_step_and_foreground_block():
    from engine.backends import FakeInput as FI
    w = World()
    bg = FI(w.clock)
    w.window = FakeWindow((0, 0), bg_input=bg)
    w.window.menus = {"서식 > 글꼴": 33}
    steps = [{"type": "menu", "path": "서식 > 글꼴"},
             {"type": "click", "target": {"point": [1, 1]}, "foreground": True},
             {"type": "click", "target": {"point": [2, 2]}, "foreground": True},
             {"type": "click", "target": {"point": [3, 3]}}]
    res = w.run(steps, window={"title": "x", "background": True})
    assert res.status == "ok", res.error
    assert w.window.commands == [33]
    assert w.window.focus_log == ["snapshot", "restore"]          # 연달아 있는 두 스텝은 한 번에
    real = [e[1:] for e in w.input.events if e[1] == "move"]
    back = [e[1:] for e in bg.events if e[1] == "move"]
    assert real == [("move", 1, 1), ("move", 2, 2)] and back == [("move", 3, 3)]


def test_foreground_block_restores_on_failure():
    from engine.backends import FakeInput as FI
    w = World()
    w.window = FakeWindow((0, 0), bg_input=FI(w.clock))
    res = w.run([{"type": "click", "target": {"image": "없음.png"}, "timeout": 0.3, "foreground": True}],
                window={"title": "x", "background": True}, on_iteration_fail={"action": "stop"})
    assert res.status == "failed" and w.window.focus_log == ["snapshot", "restore"]


def test_menu_step_without_menu_fails_clearly():
    w = World()
    res = w.run([{"type": "menu", "path": "파일 > 열기"}], window={"title": "x"}, on_iteration_fail={"action": "stop"})
    assert res.status == "failed" and "메뉴" in res.error["reason"]


def test_foreground_block_waits_while_user_busy():
    from engine.backends import FakeInput as FI
    w = World()
    w.window = FakeWindow((0, 0), bg_input=FI(w.clock))
    w.window.busy = 2
    res = w.run([{"type": "click", "target": {"point": [1, 1]}, "foreground": True}],
                window={"title": "x", "background": True})
    assert res.status == "ok" and any(e.get("event") == "foreground_wait" for e in w.events)


def test_window_size_condition():
    w = World()
    w.window.client_size = lambda: (420, 260)
    res = w.run([{"type": "if", "cond": {"window_size": [420, 260]}, "then": [{"type": "set", "var": "a", "value": 1}]},
                 {"type": "if", "cond": {"window_size": [400, 260]}, "then": [{"type": "stop", "reason": "크기 다른데 실행됨"}]}],
                window={"title": "x"})
    assert res.status == "ok"


# ---- 숨겨서 실행(window.hidden, 11-24)
class _HideWindow(FakeWindow):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.log = []

    def hide(self):
        self.log.append("hide")

    def unhide(self):
        self.log.append("unhide")

    def show_for_now(self):
        self.log.append("show")

    def hide_again(self):
        self.log.append("again")

    def focus_snapshot(self):
        return None


def _hide_world():
    w = World()
    bg = _BgInput(w.clock)
    w.window = _HideWindow((100, 50), bg_input=bg)
    return w


def test_hidden_hides_at_start_and_restores_at_end():
    w = _hide_world()
    res = w.runner(new_macro("m", [{"type": "click", "target": {"point": [5, 5]}}],
                             window={"title": "x", "background": True, "hidden": True})).run()
    assert res.status == "ok"
    assert w.window.log[0] == "hide" and w.window.log[-1] == "unhide"
    assert any(e["event"] == "hidden" for e in w.events)


def test_hidden_restores_even_when_step_fails():
    w = _hide_world()
    res = w.runner(new_macro("m", [{"type": "click", "target": {"image": "nope.png"}, "timeout": 0.5}],
                             window={"title": "x", "background": True, "hidden": True})).run()
    assert res.status != "ok" and w.window.log[-1] == "unhide"


def test_hidden_shows_window_during_foreground_step():
    w = _hide_world()
    res = w.runner(new_macro("m", [{"type": "click", "target": {"point": [5, 5]}, "foreground": True}],
                             window={"title": "x", "background": True, "hidden": True})).run()
    assert res.status == "ok"
    assert w.window.log.index("show") < w.window.log.index("again") < len(w.window.log) - 1


def test_hidden_needs_background_and_support():
    from engine.model import validate_macro
    errs = validate_macro(new_macro("m", [], window={"title": "x", "hidden": True}))
    assert any("hidden" in e for e in errs)
    w, _bg = _bg_world()                                   # hide 없는 창 → 분명한 실패
    res = w.runner(new_macro("m", [{"type": "click", "target": {"point": [5, 5]}}],
                             window={"title": "x", "background": True, "hidden": True})).run()
    assert res.status != "ok" or res.failed_iterations == 1


# ---- 뒤에서 실행 중 앞 창 지키기: 사람이 직접 대상 창을 고르면 되돌리지 않음(11-24)
class _GuardWindow(FakeWindow):
    def __init__(self, *a, answer=True, **k):
        super().__init__(*a, **k)
        self.answer, self.calls = answer, []

    def user_foreground(self):
        return None

    def keep_user_foreground(self, uf):
        self.calls.append(uf)
        return self.answer


def _guard_world(answer):
    w = World()
    bg = _BgInput(w.clock)
    w.window = _GuardWindow((0, 0), bg_input=bg, answer=answer)
    return w


def test_focus_guard_stops_when_person_chose_target():
    w = _guard_world("user")
    r = w.runner(new_macro("m", [{"type": "click", "target": {"point": [1, 1]}}] * 3,
                           window={"title": "x", "background": True}))
    r._get_window()
    r._user_fg = 123
    r._guard_focus("p")
    assert r._user_fg is None and any(e["event"] == "focus_guard_user" for e in w.events)
    r._guard_focus("p")                                  # 사람이 다른 창으로 옮기기 전까지 다시 지키지 않음
    assert w.window.calls == [123]


def test_focus_guard_still_restores_when_target_stole_focus():
    w = _guard_world(True)
    r = w.runner(new_macro("m", [], window={"title": "x", "background": True}))
    r._get_window()
    r._user_fg = 123
    r._guard_focus("p")
    assert r._user_fg == 123 and any(e["event"] == "focus_guard" for e in w.events)

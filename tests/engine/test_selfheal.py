"""헛돎 알아채기·스스로 고치기(engine/selfheal.py) — 가짜 화면, 실제 입력 없음."""
import json

import numpy as np

from engine import Runner, new_macro, validate_macro
from engine.backends import FakeClock, FakeInput, FakeVision
from engine.library import DictLibrary
from engine.selfheal import SelfHeal, day_counts

X_IMG = "test/close_x.png"
X_AT = (90, 10)


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def _fp(v):
    return ("%064x" % v)


def test_detects_same_step_same_screen(tmp_path):
    c = Clock()
    h = SelfHeal("m", {"on": True, "repeat_n": 10, "window_s": 100}, root=str(tmp_path), now=c)
    stuck = False
    for i in range(10):
        c.t += 1
        if h.note("m:steps[0]"):
            stuck = h.note_screen("m:steps[0]", _fp(1)) or stuck
    assert stuck


def test_different_screens_are_not_stuck(tmp_path):
    c = Clock()
    h = SelfHeal("m", {"on": True, "repeat_n": 10, "window_s": 100}, root=str(tmp_path), now=c)
    for i in range(30):
        c.t += 1
        if h.note("m:steps[0]"):
            assert not h.note_screen("m:steps[0]", _fp(2 ** (i * 7 % 250) * 0xFFFFF))


def test_slow_repeats_outside_window_are_not_stuck(tmp_path):
    c = Clock()
    h = SelfHeal("m", {"on": True, "repeat_n": 10, "window_s": 100}, root=str(tmp_path), now=c)
    for i in range(30):
        c.t += 50                                      # 100초 창 안에 2~3번뿐
        if h.note("m:steps[0]"):
            assert not h.note_screen("m:steps[0]", _fp(1))


def test_plan_order_verify_and_saved_first(tmp_path):
    c = Clock()
    cfg = {"on": True, "repeat_n": 10, "window_s": 100, "verify_s": 60, "recover_macro": "복구", "ai": False}
    h = SelfHeal("m", cfg, root=str(tmp_path), now=c)
    k, fp = "m:steps[0]", _fp(5)
    p1 = h.plan(k, fp)
    assert p1["action"] == "close"
    h.started(k, fp, "close")
    p2 = h.plan(k, fp)                                  # 같은 막힘이 또 남 → 닫기는 안 통함, 다음은 복구
    assert p2["action"] == "recover"
    h.started(k, fp, "recover")
    c.t += 61
    h.note("other")                                    # 시간이 지나 같은 막힘이 없었음 → 복구가 통함 → 저장
    saved = json.load(open(tmp_path / "m.json", encoding="utf-8"))
    assert saved and saved[0]["action"] == "recover"
    h2 = SelfHeal("m", cfg, root=str(tmp_path), now=c)
    assert h2.plan(k, fp)["saved"] is not None          # 다음엔 저장된 해결부터
    log = [json.loads(l) for l in open(tmp_path / "events.jsonl", encoding="utf-8")]
    assert [r["결과"] for r in log] == ["안 통함", "통함"]
    assert day_counts(log[0]["시각"][:10], str(tmp_path))["recover"] == 1


def test_rest_and_exhausted(tmp_path):
    c = Clock()
    h = SelfHeal("m", {"on": True, "ai": False, "generic_close": False, "rest_min": 1}, root=str(tmp_path), now=c)
    k, fp = "m:a", _fp(9)
    assert h.plan(k, fp)["action"] == "rest"            # 닫기 대상·복구 매크로가 없으면 바로 쉬기
    h.rest("sub")
    assert h.resting("sub")
    c.t += 61
    assert not h.resting("sub")
    h.started(k, fp, "rest")
    assert h.plan(k, fp) is None                        # 해 볼 게 없음


def test_validate_unstick_keys():
    assert not validate_macro(new_macro("m", [{"type": "delay", "seconds": 1}],
                                        unstick={"on": True, "repeat_n": 20, "close_targets": [{"image": X_IMG}]}))
    assert validate_macro(new_macro("m", [{"type": "delay", "seconds": 1}], unstick={"on": True, "모름": 1}))


class PopupVision(FakeVision):
    def __init__(self, clock, world):
        super().__init__(clock)
        self.world = world

    def grab(self, region):
        img = np.zeros((80, 120), np.uint8)
        img[:, :60] = 200
        if self.world.popup:
            img[20:60, 30:90] = 255 - img[20:60, 30:90]
        else:
            img[:, :] = (self.world.n * 37) % 255         # 팝업이 없으면 매번 다른 화면(정상 흐름)
        return img

    def save_region(self, region, path):
        open(path, "wb").write(b"png")
        return path

    def screen_rect(self):
        return (0, 0, 120, 80)


def test_runner_unsticks_with_close_target(tmp_path, monkeypatch):
    """팝업 앞에서 같은 스텝만 계속 누름 → 막힘 → 닫기 대상(X 그림) 누름 → 팝업 사라짐."""
    monkeypatch.setenv("MACRO_SELFHEAL_DIR", str(tmp_path))

    class W:
        popup = True
        n = 0
    w = W()
    clock = FakeClock()
    vision = PopupVision(clock, w)
    vision.show(X_IMG, X_AT)
    inp = FakeInput(clock)

    def clicked(pos, button):
        w.n += 1
        if pos == X_AT:
            w.popup = False
            vision.hide(X_IMG)
    inp.on_click = clicked
    events = []
    m = new_macro("m", [{"type": "repeat", "times": 40, "steps": [
        {"type": "click", "target": {"point": [5, 5]}}, {"type": "delay", "seconds": 1}]}],
        unstick={"on": True, "repeat_n": 10, "window_s": 1000, "ai": False, "close_targets": [{"image": X_IMG}]})
    r = Runner(m, vision=vision, input=inp, clock=clock, library=DictLibrary(), on_event=events.append)
    res = r.run()
    assert res.status == "ok"
    assert not w.popup
    heals = [e for e in events if e["event"] == "selfheal"]
    assert heals and heals[0]["action"] == "close"
    assert X_AT in inp.clicks()
    assert (tmp_path / "events.jsonl").exists()
    assert any((tmp_path / "evidence").iterdir())


def test_busy_normal_flow_with_many_steps_is_not_stuck(tmp_path):
    """한 단추가 자주 눌려도 그 사이 다른 스텝을 여러 가지 누르면(정상 흐름) 막힘이 아님."""
    c = Clock()
    h = SelfHeal("m", {"on": True, "repeat_n": 10, "window_s": 100, "max_distinct": 6}, root=str(tmp_path), now=c)
    stuck = False
    for i in range(40):
        c.t += 1
        h.note(f"m:other[{i % 8}]")                    # 다른 스텝 8가지
        c.t += 1
        if h.note("m:sell"):
            stuck = h.note_screen("m:sell", _fp(3)) or stuck
    assert not stuck


def test_found_branch_loop_without_any_click_is_stuck(tmp_path):
    """누름 없이 '찾았다' 분기만 되풀이(11-20 명품 창: 제목은 찾는데 받기 단추를 못 찾음) → 막힘."""
    c = Clock()
    h = SelfHeal("m", {"on": True, "repeat_n": 10, "window_s": 600}, root=str(tmp_path), now=c)
    stuck = False
    for i in range(12):
        c.t += 3
        if h.note("m:steps[1]:찾음", is_input=False):
            stuck = h.note_screen("m:steps[1]:찾음", _fp(7)) or stuck
    assert stuck


def test_replay_of_real_stuck_log_is_caught():
    """실제 11-20 기록(있을 때만): 명품 창 헛돎이 20:00~20:06 사이에 잡힘."""
    import os
    import pytest
    import glob
    fs = glob.glob(os.path.join(os.path.dirname(__file__), "..", "..", "logs", "runs", "20261120_191555_*.jsonl"))
    f = fs[0] if fs else ""
    if not f:
        pytest.skip("실행 기록 없음")
    import importlib.util
    spec = importlib.util.spec_from_file_location("ru", os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "replay_unstick.py"))
    ru = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ru)
    found = ru.replay(f)
    assert any("11-20 20:0" in t for t, _k in found)

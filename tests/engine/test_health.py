"""건강 기록(스스로 고치기 1단계): 회차·시간·경로 지문·그림 점수가 쌓이고 요약이 맞는지. 가짜 화면."""
import json

from engine import Runner, new_macro
from engine.backends import FakeClock, FakeInput, FakeVision
from engine.health import HealthRecorder, load_summary

IMG = "t/ok.png"


def run(tmp_path, times=3, score=0.9, fail=False, watch=None):
    clock = FakeClock()
    vis = FakeVision(clock)
    if not fail:
        vis.show(IMG, (10, 10), score=score)
    rec = HealthRecorder(str(tmp_path))
    steps = [{"type": "set", "var": "목표", "value": 1},
             {"type": "click", "target": {"image": IMG}, "timeout": 0.5}]
    m = new_macro("건강", steps, repeat={"times": times}, on_iteration_fail={"action": "stop"},
                  **({"self_heal": {"mode": "notify", "watch_vars": watch}} if watch else {}))
    r = Runner(m, vision=vis, input=FakeInput(clock), clock=clock, health=rec).run()
    return r, rec


def test_iterations_scores_and_summary(tmp_path):
    r, rec = run(tmp_path, times=3, score=0.86, watch=["목표"])
    assert r.status == "ok"
    d = json.load(open(tmp_path / "건강.json", encoding="utf-8"))
    assert len(d["iterations"]) == 3 and all(i["ok"] for i in d["iterations"])
    assert len({i["sig"] for i in d["iterations"]}) == 1                 # 같은 경로 → 같은 지문
    assert d["iterations"][0]["watch"] == {"목표": 1}
    assert d["images"][IMG]["scores"][-1] == 0.86 and d["images"][IMG]["confidence"] == 0.8
    s = load_summary(str(tmp_path), "건강")
    assert s["ok"] == 3 and s["low_images"][0]["image"] == IMG and s["low_images"][0]["margin"] == 0.06


def test_failed_iteration_recorded(tmp_path):
    r, rec = run(tmp_path, times=1, fail=True)
    assert r.status == "failed"
    d = json.load(open(tmp_path / "건강.json", encoding="utf-8"))
    assert d["iterations"][-1]["ok"] is False and "못 찾음" in d["iterations"][-1]["reason"]
    assert IMG not in d["images"]                                           # 안 보일 때 점수는 안 모음


def test_history_survives_new_recorder(tmp_path):
    run(tmp_path, times=2)
    run(tmp_path, times=2)
    assert load_summary(str(tmp_path), "건강")["iterations"] == 4


from engine.health import MacroHealth, config


def _h(tmp_path):
    return MacroHealth("m", str(tmp_path / "m.json"))


def test_stall_needs_watch_vars_and_fires_once(tmp_path):
    h = _h(tmp_path)
    cfg = config({"self_heal": {"mode": "notify", "watch_vars": ["v"], "stall_repeats": 3}})
    kinds = []
    for _ in range(5):
        h.add_iteration(True, 1.0, "s1", {"v": 7})
        kinds += [s["kind"] for s in h.check(cfg)]
    assert kinds == ["stall"]                                  # 3회째 한 번만
    h.add_iteration(True, 1.0, "s1", {"v": 8})                 # 값이 바뀌면 풀림
    assert h.check(cfg) == []
    assert config({"self_heal": {"mode": "notify"}})["watch_vars"] == []    # 목표 변수 없으면 진전 판단 안 함


def test_score_low_and_recovery(tmp_path):
    h = _h(tmp_path)
    cfg = config({"self_heal": {"mode": "notify"}})
    for _ in range(12):
        h.note_image("a.png", 0.83, True, 0.8, (5, 5))
    sig = h.check(cfg)
    assert [s["kind"] for s in sig] == ["score_low"] and sig[0]["detail"]["last_pos"] == [5, 5]
    assert h.check(cfg) == []                                  # 계속되는 동안 되풀이 안 함


def test_new_window_baseline_then_new(tmp_path):
    h = _h(tmp_path)
    assert h.note_windows(["메모장"]) == []                    # 처음은 기준만
    assert h.note_windows(["메모장", "저장 확인"]) == ["저장 확인"]
    assert [s["kind"] for s in h.check(config({}), ["저장 확인"])] == ["new_window"]


def test_slow_after_count(tmp_path):
    h = _h(tmp_path)
    cfg = config({"self_heal": {"mode": "notify", "slow_count": 2, "slow_min_seconds": 1}})
    for _ in range(6):
        h.add_iteration(True, 2.0, "s", {})
        h.check(cfg)
    h.add_iteration(True, 9.0, "s", {})
    assert h.check(cfg) == []
    h.add_iteration(True, 9.5, "s", {})
    assert [s["kind"] for s in h.check(cfg)] == ["slow"]


def test_runner_notify_mode_writes_repair_log(tmp_path):
    from engine import Runner, new_macro
    from engine.backends import FakeClock, FakeInput, FakeVision
    from engine.health import HealthRecorder
    from engine.repairs import load_all
    clock = FakeClock()
    vis = FakeVision(clock)
    vis.show("t/a.png", (1, 1), score=0.82)
    rec = HealthRecorder(str(tmp_path / "h"), str(tmp_path / "r"))
    m = new_macro("알림", [{"type": "click", "target": {"image": "t/a.png"}}], repeat={"times": 12},
                  self_heal={"mode": "notify"})
    ev = []
    assert Runner(m, vision=vis, input=FakeInput(clock), clock=clock, health=rec, on_event=ev.append).run().status == "ok"
    assert any(e["event"] == "health_warning" and e["kind"] == "score_low" for e in ev)
    log = load_all(str(tmp_path / "r"))
    assert log and log[0]["kind"] == "score_low" and log[0]["status"] == "notified"


def test_off_mode_no_signals(tmp_path):
    from engine import Runner, new_macro
    from engine.backends import FakeClock, FakeInput, FakeVision
    from engine.health import HealthRecorder
    clock = FakeClock()
    vis = FakeVision(clock)
    vis.show("t/a.png", (1, 1), score=0.82)
    rec = HealthRecorder(str(tmp_path / "h"), str(tmp_path / "r"))
    ev = []
    Runner(new_macro("끔", [{"type": "click", "target": {"image": "t/a.png"}}], repeat={"times": 12}),
           vision=vis, input=FakeInput(clock), clock=clock, health=rec, on_event=ev.append).run()
    assert not any(e["event"] == "health_warning" for e in ev)

"""멈춤 지킴이: 사용자가 끈 것과 죽은 것 구분, 다시 켜기(1시간 3번까지), 멈춤 알림/다시 켜기, 하루 실적."""
import json
import os
import time

from engine import guard


def test_decide():
    now = 10_000.0
    base = {"macro": "m", "pid": 1, "guard": True, "started": now - 3600, "stall_min": 10, "restarts": []}
    assert guard.decide({}, False, None, now) == "없음"
    assert guard.decide(dict(base, guard=False), False, None, now) == "없음"
    assert guard.decide(dict(base, user_stopped=True), False, None, now) == "사용자가끔"
    assert guard.decide(base, False, None, now) == "다시켬"
    assert guard.decide(dict(base, restarts=[now - 100] * 3), False, None, now) == "다시켜기잦음"
    assert guard.decide(base, True, now - 60, now) == "없음"
    assert guard.decide(base, True, now - 700, now) == "멈춤알림"
    assert guard.decide(dict(base, restart_on_stall=True), True, now - 700, now) == "멈춤다시켬"
    assert guard.decide(dict(base, ended=now - 5, status="ok"), True, now - 700, now) == "없음"


def test_state_and_loop(tmp_path):
    root = str(tmp_path)
    guard.mark_started("팜", 4242, True, root=root)
    started, notes, stopped = [], [], []
    calls = {"n": 0}

    def until():
        calls["n"] += 1
        return calls["n"] > 2
    guard.run_loop(started.append, stopped.append, lambda a, b: notes.append(b), lambda pid: False, root=root,
                   every=0, until=until)
    assert started == ["팜", "팜"] and len(guard.read_state(root)["restarts"]) == 2
    guard.mark_ended("stopped", user_stopped=True, root=root)
    started.clear()
    guard.run_loop(started.append, stopped.append, lambda a, b: None, lambda pid: False, root=root, every=0,
                   until=lambda: False)                   # 사용자가 끔 → 바로 끝, 다시 안 켬
    assert started == []


def test_summary(tmp_path):
    root = str(tmp_path)
    runs = tmp_path / "logs" / "runs"
    runs.mkdir(parents=True)
    day = time.strftime("%Y%m%d")
    for i, st in enumerate(("ok", "failed", "stopped", "ok")):
        (runs / f"{day}_10000{i}_m.jsonl").write_text(
            json.dumps({"event": "run_end", "depth": 0, "result": {"status": st}}) + "\n", encoding="utf-8")
    guard.log_event("다시켬", "m", root=root)
    guard.log_event("멈춤알림", "m", root=root)
    s = guard.summary(day, root=root)
    assert s == {"runs": 4, "ok": 2, "failed": 1, "stopped": 1, "restarts": 1, "stalls": 1}


def test_settings(tmp_path):
    root = str(tmp_path)
    guard.save_setting("m", {"on": True, "stall_min": 5}, root=root)
    assert guard.load_settings(root)["m"]["stall_min"] == 5
    guard.save_setting("m", None, root=root)
    assert guard.load_settings(root) == {}

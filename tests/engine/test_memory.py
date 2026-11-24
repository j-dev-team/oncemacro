"""메모리 매크로(부가 기능): 진짜 다른 프로그램(시험용 memtarget.py)의 값을 읽기 전용으로 읽는다.
켜고 끄기·저장한 이름·포인터 따라가기·조건·값이 바뀔 때까지/이상이 될 때까지 기다리기·실행 끝에 떼기."""
import json
import os
import subprocess
import sys
import time

import pytest

from engine import Runner, new_macro, validate_macro
from engine import memory as mm
from engine.backends import FakeClock, FakeInput, FakeVision

HERE = os.path.dirname(os.path.abspath(__file__))


@pytest.fixture
def target():
    p = subprocess.Popen([sys.executable, os.path.join(HERE, "memtarget.py"), "0"], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, text=True)
    info = json.loads(p.stdout.readline())
    yield p, info
    try:
        p.stdin.close()
    except Exception:
        pass
    p.wait(5)


@pytest.fixture
def root(tmp_path):
    mm.set_enabled(True, root=str(tmp_path))
    return str(tmp_path)


class RealClock(FakeClock):
    """기다리기가 진짜 시간으로 흐르게(다른 프로그램이 값을 바꾸는 동안)."""

    def now(self):
        return time.monotonic()

    def sleep(self, seconds, stop):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if stop is not None and stop.is_set():
                return False
            time.sleep(0.01)
        return True


def run(steps, root, pid, real_clock=False):
    clock = RealClock() if real_clock else FakeClock()
    events = []
    r = Runner(new_macro("m", steps), vision=FakeVision(clock), input=FakeInput(clock), clock=clock,
               on_event=events.append)
    r.base_dir = root
    r.memory_pid = pid
    res = r.run()
    return res, {e["var"]: e["value"] for e in events if e.get("event") == "set"}, r


def test_read_kinds_and_pointer(target, root):
    p, a = target
    steps = [{"type": "memory", "value": {"offset": a["int"], "kind": "int32"}, "var": "i"},
             {"type": "memory", "value": {"offset": a["double"], "kind": "double"}, "var": "d"},
             {"type": "memory", "value": {"offset": hex(a["text"]), "kind": "text", "length": 32}, "var": "t"},
             {"type": "memory", "value": {"offset": a["text16"], "kind": "text16", "length": 16}, "var": "w"},
             {"type": "memory", "value": {"offset": a["ptr"] + 8, "pointers": [0], "kind": "int32"}, "var": "pi"}]
    assert not validate_macro(new_macro("m", steps))
    res, got, r = run(steps, root, a["pid"])
    assert res.status == "ok", res.error
    assert got == {"i": 100, "d": 3.5, "t": "가게 열림", "w": "hello 세계", "pi": 100}
    assert r._memory is None                       # 실행 끝에 뗌


def test_saved_name_and_condition(target, root):
    p, a = target
    mm.save_value("돈", {"offset": a["int"], "kind": "int32"}, root=root)
    steps = [{"type": "if", "cond": {"memory": {"value": "돈", "ge": 100}},
              "then": [{"type": "set", "var": "결과", "value": "많음"}],
              "else": [{"type": "set", "var": "결과", "value": "적음"}]}]
    res, got, _ = run(steps, root, a["pid"])
    assert res.status == "ok" and got["결과"] == "많음"


def test_wait_until_changed_and_ge(target, root):
    p, a = target
    spec = {"offset": a["int"], "kind": "int32"}

    def bump():
        time.sleep(0.3)
        p.stdin.write("\n")
        p.stdin.flush()
    import threading
    threading.Thread(target=bump, daemon=True).start()
    steps = [{"type": "wait", "until": {"memory": {"value": spec, "changed": True}}, "timeout": 5},
             {"type": "memory", "value": spec, "var": "후"}]
    res, got, _ = run(steps, root, a["pid"], real_clock=True)
    assert res.status == "ok", res.error
    assert got["후"] == 107

    def bump2():
        for _ in range(3):
            time.sleep(0.15)
            p.stdin.write("\n")
            p.stdin.flush()
    threading.Thread(target=bump2, daemon=True).start()
    steps = [{"type": "wait", "until": {"memory": {"value": spec, "ge": 125}}, "timeout": 5}]
    res, _, _ = run(steps, root, a["pid"], real_clock=True)
    assert res.status == "ok", res.error


def test_addon_off_fails_without_attaching(target, tmp_path):
    p, a = target
    opened = []
    steps = [{"type": "memory", "value": {"offset": a["int"]}, "var": "i"}]
    clock = FakeClock()
    r = Runner(new_macro("m", steps), vision=FakeVision(clock), input=FakeInput(clock), clock=clock)
    r.base_dir = str(tmp_path)                       # 부가 기능 꺼짐(설정 없음)
    r.memory_pid = a["pid"]
    r.memory_reader = lambda pid: opened.append(pid)
    res = r.run()
    assert res.status == "failed" and "꺼져" in res.error["reason"] and opened == []


def test_validation():
    ok = lambda st: not validate_macro(new_macro("m", st))  # noqa: E731
    assert not ok([{"type": "memory", "value": {"offset": "zz"}, "var": "a"}])
    assert not ok([{"type": "memory", "value": {"offset": 1, "kind": "long"}, "var": "a"}])
    assert not ok([{"type": "if", "cond": {"memory": {"value": "x", "changed": True}}, "then": []}])   # 기다리기 전용
    assert ok([{"type": "wait", "until": {"memory": {"value": "x", "changed": True}}}])
    assert ok([{"type": "memory", "value": {"module": "a.dll", "offset": "0x10", "pointers": ["0x8", 4], "kind": "float"},
                "var": "a"}])


def test_bad_address_is_plain_failure(target, root):
    p, a = target
    res, _, _ = run([{"type": "memory", "value": {"offset": 16}, "var": "i"}], root, a["pid"])
    assert res.status == "failed" and "읽지 못함" in res.error["reason"]


def test_read_number_memory_first_then_screen(target, root):
    p, a = target
    clock = FakeClock()
    vis = FakeVision(clock)
    vis.read_text = lambda region, opts: ("777", 0.9)          # 화면 숫자
    ev = []
    steps = [{"type": "read_number", "region": [0, 0, 10, 10], "var": "n",
              "memory": {"value": {"offset": a["int"], "kind": "int32"}, "range": [0, 1000]}}]
    assert not validate_macro(new_macro("m", steps))
    r = Runner(new_macro("m", steps), vision=vis, input=FakeInput(clock), clock=clock, on_event=ev.append)
    r.base_dir, r.memory_pid = root, a["pid"]
    assert r.run().status == "ok"
    reads = [e for e in ev if e.get("event") == "read"]
    assert reads[0]["value"] == 100 and reads[0]["source"] == "memory"
    # 범위 밖이면 화면으로 + 알림 한 번
    steps[0]["memory"]["range"] = [500, 600]
    ev.clear()
    r = Runner(new_macro("m", [steps[0], steps[0]]), vision=vis, input=FakeInput(clock), clock=clock, on_event=ev.append)
    r.base_dir, r.memory_pid = root, a["pid"]
    assert r.run().status == "ok"
    assert [e["value"] for e in ev if e.get("event") == "read"] == [777, 777]
    assert len([e for e in ev if e.get("event") == "warning" and "다시 찾아야" in e["message"]]) == 1
    # 부가 기능이 꺼져 있으면 화면으로만(알림 없음)
    mm.set_enabled(False, root=root)
    ev.clear()
    r = Runner(new_macro("m", steps), vision=vis, input=FakeInput(clock), clock=clock, on_event=ev.append)
    r.base_dir, r.memory_pid = root, a["pid"]
    r.run()
    assert [e["value"] for e in ev if e.get("event") == "read"] == [777] and not [e for e in ev if e.get("event") == "warning"]

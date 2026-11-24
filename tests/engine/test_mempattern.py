"""무늬 찾기(다시 켠 다른 프로세스에서도 같은 모양 자리 찾기)·목표 맞추기(계산되는 값)."""
import json
import os
import subprocess
import sys

import pytest

from engine import memory as mm
from engine import mempattern as mp
from engine.memwrite import ProcessWriter

HERE = os.path.dirname(os.path.abspath(__file__))


def _start():
    p = subprocess.Popen([sys.executable, os.path.join(HERE, "memtarget.py"), "0"], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, text=True)
    return p, json.loads(p.stdout.readline())


def _stop(p):
    try:
        p.stdin.close()
    except Exception:
        pass
    p.wait(5)


def test_pattern_found_again_in_new_process():
    p1, a1 = _start()
    try:
        r1 = mm.ProcessReader(a1["pid"])
        sig = mp.capture(r1, a1["double"], "double", before=24, after=24)
        assert "??" in sig["pattern"]
        assert a1["double"] in mp.find(r1, sig, limit=2000)
        r1.close()
    finally:
        _stop(p1)
    p2, a2 = _start()                                    # '다시 켬': 주소가 바뀐 새 프로세스
    try:
        r2 = mm.ProcessReader(a2["pid"])
        hits = mp.find(r2, sig, limit=2000)
        assert a2["double"] in hits
        assert any(r2.value({"offset": h, "kind": "double"}) == 3.5 for h in hits)
        r2.close()
    finally:
        _stop(p2)


def test_goal_seek_with_computed_level():
    state = {"pts": 0}
    level_of = lambda pts: int((pts + 70) ** 0.5 / 20 ** 0.5) if pts >= 0 else 0   # 숨은 규칙(모름)

    got = mp.goal_seek(lambda x: state.update(pts=x), lambda: level_of(state["pts"]), 10, lo=0, hi=100000, settle=0)
    assert got is not None and level_of(got) == 10 and level_of(got - 1) == 9 and state["pts"] == got
    assert mp.goal_seek(lambda x: state.update(pts=x), lambda: min(5, level_of(state["pts"])), 10, 0, 10000, settle=0) is None


def test_goal_seek_on_real_process():
    p, a = _start()
    try:
        w = ProcessWriter(a["pid"])
        spec = {"offset": a["int"], "kind": "int32"}
        got = mp.goal_seek(lambda x: w.write(spec, x, log=False), lambda: w.value(spec) // 100, 42, 0, 100000, settle=0)
        assert got == 4200 and w.value(spec) == 4200
        w.close()
    finally:
        _stop(p)


def test_saved_spec_with_pattern_resolves_after_restart():
    p1, a1 = _start()
    try:
        r1 = mm.ProcessReader(a1["pid"])
        spec = {"offset": hex(a1["double"]), "kind": "double",
                "pattern": mp.capture(r1, a1["double"], "double")}
        assert not mm.check_spec(spec)
        assert r1.value(spec) == 3.5
        r1.close()
    finally:
        _stop(p1)
    p2, a2 = _start()
    try:
        r2 = mm.ProcessReader(a2["pid"])
        assert r2.value(spec) == 3.5                    # 옛 offset 은 틀렸지만 무늬로 다시 찾음
        r2.close()
    finally:
        _stop(p2)

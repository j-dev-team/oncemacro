"""메모리 매크로 2·3번: 값 찾기(처음·다시 좁히기·모르는 처음 값·자료형 자동)·값 바꾸기·고정 — 진짜 다른 프로그램(memtarget.py)으로."""
import json
import os
import subprocess
import sys
import time

import pytest

from engine import memory as mm
from engine.memscan import Scan, spec_for
from engine.memwrite import Freezer, ProcessWriter

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


def bump(p, n=1):
    for _ in range(n):
        p.stdin.write("\n")
        p.stdin.flush()
    time.sleep(0.15)


def test_find_by_value_then_narrow(target):
    p, a = target
    r = mm.ProcessReader(a["pid"])
    try:
        s = Scan(r, "int32")
        n1 = s.first(100)
        assert n1 >= 1 and a["int"] in [x["address"] for x in s.results(n1)]
        bump(p)                                   # 100 → 107
        s.next("eq", 107)
        bump(p)                                   # 107 → 114
        n3 = s.next("increased")
        addrs = [x["address"] for x in s.results(1000)]
        assert a["int"] in addrs and n3 <= 20, n3
        bump(p)                                   # 114 → 121
        s.next("inc_by", 7)
        hit = [x for x in s.results() if x["address"] == a["int"]][0]
        assert hit["value"] == 121
    finally:
        r.close()


def test_unknown_first_value(target):
    p, a = target
    r = mm.ProcessReader(a["pid"])
    try:
        s = Scan(r, "int32")
        assert s.first(None) == -1               # 담아 둠
        bump(p)
        s.next("increased")
        bump(p)
        s.next("increased")
        s.next("unchanged")
        bump(p)
        s.next("inc_by", 7)
        assert a["int"] in [x["address"] for x in s.results(5000)]
    finally:
        r.close()


def test_auto_kind_finds_double(target):
    p, a = target
    r = mm.ProcessReader(a["pid"])
    try:
        s = Scan(r, "auto")
        s.first(3.5)
        assert any(x["address"] == a["double"] and x["kind"] == "double" for x in s.results(100000))
    finally:
        r.close()


def test_write_freeze_and_log(target, tmp_path):
    p, a = target
    w = ProcessWriter(a["pid"], root=str(tmp_path))
    try:
        spec = spec_for(w, a["int"], "int32")
        assert w.value(spec) == 100
        w.write(spec, 999)
        assert w.value(spec) == 999
        bump(p)
        assert w.value(spec) == 1006              # 게임이 계속 바꿈
        fz = Freezer(w, interval=0.02)
        fz.set("체력", spec, 500)
        time.sleep(0.1)
        bump(p, 3)                                 # 게임이 깎으려 해도
        time.sleep(0.1)
        assert w.value(spec) == 500               # 고정
        assert fz.toggle("체력", spec, 500) is False
        bump(p)
        assert w.value(spec) == 507               # 고정 풀림
        fz.stop()
        lines = open(os.path.join(tmp_path, "logs", "memory", "writes.jsonl"), encoding="utf-8").read().splitlines()
        assert any('"value": 999' in ln for ln in lines) and any("freeze_on" in ln for ln in lines)
    finally:
        w.close()


def test_spec_for_module_relative(target):
    p, a = target
    r = mm.ProcessReader(a["pid"])
    try:
        mods = r.modules()
        exe_base = mods.get("python.exe") or mods.get("python311.dll")
        sp = spec_for(r, a["int"], "int32")
        assert sp["kind"] == "int32" and "offset" in sp
        if exe_base:
            sp2 = spec_for(r, exe_base + 0x10, "int32")
            assert sp2.get("module") and sp2["offset"] == "0x10"
    finally:
        r.close()


def test_write_and_freeze_steps(target, tmp_path):
    from engine import Runner, new_macro, validate_macro
    from engine.backends import FakeClock, FakeInput, FakeVision
    p, a = target
    mm.set_enabled(True, root=str(tmp_path))
    mm.save_value("체력", {"offset": a["int"], "kind": "int32"}, root=str(tmp_path))
    steps = [{"type": "memory", "action": "write", "value": "체력", "set": 777},
             {"type": "memory", "action": "read", "value": "체력", "var": "a"},
             {"type": "memory", "action": "freeze", "value": "체력", "set": 300, "interval": 0.02},
             {"type": "delay", "seconds": 0.1},
             {"type": "memory", "action": "unfreeze", "value": "체력"}]
    assert not validate_macro(new_macro("m", steps))
    assert validate_macro(new_macro("m", [{"type": "memory", "action": "write", "value": "체력"}]))   # set 없음
    clock = FakeClock()
    ev = []
    r = Runner(new_macro("m", steps), vision=FakeVision(clock), input=FakeInput(clock), clock=clock, on_event=ev.append)
    r.base_dir = str(tmp_path)
    r.memory_pid = a["pid"]
    res = r.run()
    assert res.status == "ok", res.error
    assert [e for e in ev if e.get("event") == "set"][0]["value"] == 777
    assert any(e.get("event") == "memory_write" for e in ev) and any(e.get("event") == "memory_freeze" for e in ev)
    rd = mm.ProcessReader(a["pid"])
    try:
        assert rd.value({"offset": a["int"], "kind": "int32"}) == 300
    finally:
        rd.close()
    assert not getattr(r, "_mem_freezers", {}) and not getattr(r, "_mem_writers", {})   # 실행 끝에 풂·뗌


def test_range_match_for_rounded_display():
    """화면에 '2.1k'·'853'(소수 버림)처럼 보이는 값: 범위로 찾는다."""
    import numpy as np
    from engine.memscan import _match, _views
    a = np.array([2049, 2050, 2100, 2150, 2151], np.int32)
    assert _match(a, "int32", (2050.0, 2150.0), 0.5).tolist() == [False, True, True, True, False]
    f = np.array([852.4, 853.7, 854.2], np.float32)
    assert _match(f, "float", (853.0, 853.999), 0.5).tolist() == [False, True, False]
    raw = np.array([7, 857, 9], np.int64).tobytes()
    hits = [(s, st, v[_match(v, "int64", 857, 0.5)].tolist()) for s, st, v in _views(raw, "int64")]
    assert (0, 8, [857]) in hits                     # 8바이트 값도 4바이트 간격으로 빠짐없이

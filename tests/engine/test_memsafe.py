"""안전하게 쓰기: 후보 줄이기(바뀌는 자리·포인터 일부 빼기)·나눠 쓰고 살아 있는지 확인·써 보고 확인하며 반씩 좁히기·되돌리기·저장 폴더 백업."""
import json
import os
import subprocess
import sys
import time

import pytest

from engine import memory as mm
from engine import memsafe as ms
from engine.memscan import Scan
from engine.memwrite import ProcessWriter

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


def test_pointer_half_and_changing_are_dropped(target):
    p, a = target
    w = ProcessWriter(a["pid"])
    try:
        assert ms.looks_pointer(w, a["ptr"] + 8)          # 구조체 안 포인터의 아래 절반
        assert not ms.looks_pointer(w, a["int"])
        cand = [a["int"], a["ptr"] + 8]
        r = ms.narrow_safe(w, cand, "int32", None, watch=0.2, polls=2)
        assert a["int"] in r["keep"] and a["ptr"] + 8 in r["pointer"]
        r2 = ms.narrow_safe(w, [a["int"]], "int32", 999, watch=0.1, polls=2)   # 기대값과 다르면 뺌
        assert r2["changing"] == [a["int"]]
    finally:
        w.close()


def test_auto_narrow_finds_real_and_restores_others(target):
    p, a = target
    w = ProcessWriter(a["pid"])
    try:
        s = Scan(w, "int32")
        s.first(100)
        addrs = [x["address"] for x in s.results(100000)]
        keep = ms.narrow_safe(w, addrs, "int32", 100, watch=0.2, polls=2)["keep"]
        assert a["int"] in keep
        before = {x: w.value({"offset": x, "kind": "int32"}) for x in keep}
        state = {"last": 100}

        def screen_changed():                            # 가짜 '화면': 진짜 값이 바뀌면 화면도 바뀜
            cur = w.value({"offset": a["int"], "kind": "int32"})
            ch = cur != state["last"]
            state["last"] = cur
            return ch
        real = ms.auto_narrow(w, keep, "int32", 5000, screen_changed, settle=0.3)
        assert real == a["int"] and w.value({"offset": a["int"], "kind": "int32"}) == 5000
        others = [x for x in keep if x != real]
        assert all(w.value({"offset": x, "kind": "int32"}) == before[x] for x in others)   # 나머지는 되돌림
        assert ms.alive(a["pid"])
    finally:
        w.close()


def test_backup_save_folders(tmp_path):
    game = tmp_path / "게임"
    (game / "Bin").mkdir(parents=True)
    exe = game / "Bin" / "MyGame-Win64.exe"
    exe.write_bytes(b"MZ")
    sv = game / "UserData" / "Saved" / "SaveGames"
    sv.mkdir(parents=True)
    (sv / "Slot1.sav").write_bytes(b"GVAS")
    assert ms.save_folders(str(exe)) == [str(sv)]
    made = ms.backup_saves(str(exe), root=str(tmp_path / "root"))
    assert len(made) == 1 and os.path.exists(os.path.join(made[0], "Slot1.sav"))
    assert open(os.path.join(made[0], "_original_location.txt"), encoding="utf-8").read().strip() == str(sv)


def test_alive_and_exe_path(target):
    p, a = target
    assert ms.alive(a["pid"]) and ms.exe_path(a["pid"]).lower().endswith("python.exe")

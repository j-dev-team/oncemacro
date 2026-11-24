"""다시 켜도 찾기: 포인터 경로 찾기(가짜 메모리로) — 모듈 안 고정 칸 → 힙 구조체 → 값. 다시 켠 것처럼 주소가 바뀌어도 경로로 다시 찾음."""
import struct

import numpy as np

from engine import memptr as mp
from engine.memory import MemoryError_


class FakeMem:
    def __init__(self, heap_base):
        self.mem = {}
        self.mods = {"game.exe": 0x140000000}
        self.ptr_size = 8
        # 모듈 .data 0x140010100 → 힙 객체 A(heap_base) ; A+0x30 → 객체 B ; B+0x18 = 돈
        a, b = heap_base, heap_base + 0x5000
        self.put(0x140010100, struct.pack("<Q", a))
        self.put(a + 0x30, struct.pack("<Q", b))
        self.put(b + 0x18, struct.pack("<i", 9455))
        self.money = b + 0x18

    def put(self, addr, data):
        for i, c in enumerate(data):
            self.mem[addr + i] = c

    def read(self, addr, n):
        try:
            return bytes(self.mem[addr + i] if (addr + i) in self.mem else 0 for i in range(n)) if any(
                (addr + i) in self.mem for i in range(n)) or self._inside(addr) else (_ for _ in ()).throw(MemoryError_("x"))
        except KeyError:
            raise MemoryError_("x")

    def _inside(self, addr):
        return any(lo <= addr < lo + sz for lo, sz in self.regs())

    def regs(self):
        return [(0x140010000, 0x1000), (self.money - 0x5018 - 0x1000 + 0x1000 - 0x1000, 0x8000)]

    def modules(self):
        return self.mods

    def value(self, spec):
        from engine.memory import ProcessReader
        return ProcessReader.value(self, spec)

    def resolve(self, spec):
        from engine.memory import ProcessReader
        return ProcessReader.resolve(self, spec)

    def _resolve_plain(self, spec):
        from engine.memory import ProcessReader
        return ProcessReader._resolve_plain(self, spec)


def _patch(monkeypatch, fm):
    monkeypatch.setattr(mp, "regions", lambda r: fm.regs())
    monkeypatch.setattr(mp, "_read_safe", lambda r, a, n: fm.read(a, n))
    monkeypatch.setattr(mp, "_modules_ranges", lambda r: [("game.exe", 0x140000000, 0x140100000)])


def test_find_and_follow_after_restart(monkeypatch):
    fm = FakeMem(0x22000000000)
    _patch(monkeypatch, fm)
    paths = mp.find_paths(fm, fm.money, depth=3)
    assert paths and paths[0] == {"module": "game.exe", "offset": "0x10100", "pointers": ["0x30", "0x18"]}
    spec = mp.to_spec(paths[0], "int32")
    assert fm.value(spec) == 9455
    fm2 = FakeMem(0x35500000000)                         # '다시 켬': 힙 주소가 바뀜
    _patch(monkeypatch, fm2)
    assert mp.resolve_path(fm2, paths[0]) == fm2.money
    assert mp.verify(fm2, paths, "int32", 9455) == [paths[0]]


def test_keep_going_collects_deeper_and_stable_filter(monkeypatch, tmp_path):
    fm = FakeMem(0x22000000000)
    # 짧은(2단계) 경로: 모듈 0x140010200 → B 직접(다시 켜면 끊기게 할 것)
    b = fm.money - 0x18
    fm.put(0x140010200, struct.pack("<Q", b))
    _patch(monkeypatch, fm)
    short = mp.find_paths(fm, fm.money, depth=3)
    assert all(len(p["pointers"]) == 1 for p in short)            # 짧은 것만
    deep = mp.find_paths(fm, fm.money, depth=3, keep_going=True, max_paths=50)
    assert any(len(p["pointers"]) == 2 for p in deep) and any(len(p["pointers"]) == 1 for p in deep)
    f = str(tmp_path / "cands.json")
    mp.save_candidates(deep, "int32", f)
    fm2 = FakeMem(0x35500000000)                                   # 다시 켬: 짧은 경로 칸은 비어 있음
    _patch(monkeypatch, fm2)
    keep = mp.stable_paths(mp.load_candidates(f)["paths"], fm2, "int32", 9455)
    assert keep and all(len(p["pointers"]) == 2 for p in keep)

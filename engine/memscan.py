"""메모리 매크로 2번: 값 찾기(혼자 하는 게임·보호 장치 없는 프로그램용). Qt 없음.

처음 찾기: 지금 값(또는 '모르는 처음 값')으로 읽고 쓸 수 있는 메모리 전체를 훑어 후보 주소를 모은다.
다시 찾기: 값이 바뀐 뒤 같음·커짐·작아짐·바뀜·안 바뀜·○만큼 커짐/작아짐으로 후보를 좁힌다.
자료형: int8~int64·float·double, 'auto' 면 int32·float·double·int16·int64 를 함께 찾아 각 후보에 표시.
읽기 전용으로 붙는다(engine.memory.ProcessReader). 쓰기·고정은 memwrite.py.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Dict, List, Optional, Tuple

import numpy as np

from .i18n import t
from .memory import KINDS, MemoryError_, ProcessReader

NP = {"int8": np.int8, "uint8": np.uint8, "int16": np.int16, "uint16": np.uint16, "int32": np.int32,
      "uint32": np.uint32, "int64": np.int64, "uint64": np.uint64, "float": np.float32, "double": np.float64}
AUTO_KINDS = ("int32", "float", "double", "int16", "int64")
MODES = ("eq", "changed", "unchanged", "increased", "decreased", "inc_by", "dec_by", "between")
CHUNK = 4 << 20
MAX_RESULTS = 20_000_000          # 이보다 많으면 숫자를 더 좁혀 달라고 함
MAX_UNKNOWN_BYTES = 768 << 20     # '모르는 처음 값' 으로 담아 둘 수 있는 최대(메모리 상한 3GB 안에서)

MEM_COMMIT = 0x1000
WRITABLE = {0x04, 0x08, 0x40, 0x80}            # READWRITE, WRITECOPY, EXECUTE_READWRITE, EXECUTE_WRITECOPY
PAGE_GUARD = 0x100


class _MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p), ("AllocationProtect", wintypes.DWORD),
                ("PartitionId", wintypes.WORD), ("RegionSize", ctypes.c_size_t), ("State", wintypes.DWORD),
                ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD)]


def regions(reader: ProcessReader, writable_only: bool = True) -> List[Tuple[int, int]]:
    """[(시작 주소, 크기)] — 값이 들 만한(쓰기 가능한, 확정된) 곳."""
    k = reader.k
    k.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(_MBI), ctypes.c_size_t]
    k.VirtualQueryEx.restype = ctypes.c_size_t
    out = []
    addr = 0
    mbi = _MBI()
    top = 0x7FFFFFFF0000 if reader.ptr_size == 8 else 0x7FFF0000
    while addr < top:
        if not k.VirtualQueryEx(reader.h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            break
        base, size = int(mbi.BaseAddress or 0), int(mbi.RegionSize)
        if size <= 0:
            break
        prot = mbi.Protect & 0xFF
        if mbi.State == MEM_COMMIT and not (mbi.Protect & PAGE_GUARD) and (prot in WRITABLE or not writable_only):
            out.append((base, size))
        addr = base + size
    return out


def _read_safe(reader, addr, size) -> Optional[bytes]:
    try:
        return reader.read(addr, size)
    except MemoryError_:
        return None


def _align(kind: str) -> int:
    return min(KINDS[kind][1], 4)


def _views(raw: bytes, kind: str):
    """raw 를 그 자료형으로 본 값들(복사 없이). 4바이트마다 보는데, 8바이트 자료형은 시작 0·4 두 갈래로.
    돌려줌: [(시작 바이트, 간격, 값 배열)] — 주소 = 시작 + 번호 × 간격."""
    item = KINDS[kind][1]
    a = _align(kind)
    out = []
    for start in range(0, item, a):
        n = (len(raw) - start) // item
        if n > 0:
            out.append((start, item, np.frombuffer(raw, dtype=NP[kind], count=n, offset=start)))
    return out


def _match(arr: np.ndarray, kind: str, value, tol: float):
    if isinstance(value, (tuple, list)):          # 범위(화면에 '2.1k' 처럼 반올림돼 보이는 값)
        lo, hi = float(value[0]), float(value[1])
        with np.errstate(invalid="ignore", over="ignore"):
            if kind in ("float", "double"):
                return (arr >= arr.dtype.type(lo)) & (arr <= arr.dtype.type(hi))
            info = np.iinfo(NP[kind])
            lo_i, hi_i = max(int(np.ceil(lo)), int(info.min)), min(int(np.floor(hi)), int(info.max))
            if lo_i > hi_i:
                return np.zeros(arr.shape, bool)
            return (arr >= NP[kind](lo_i)) & (arr <= NP[kind](hi_i))
    if kind in ("float", "double"):
        with np.errstate(invalid="ignore", over="ignore"):      # 실수로 보면 엉뚱한 값(NaN 등)이 많음 — 조용히 거름
            v = float(value)
            # 넓은 범위 안에 드는 것만 고른 뒤 정확히 비교(전부를 실수 64비트로 바꾸지 않음)
            m = (arr >= arr.dtype.type(v - tol - 1)) & (arr <= arr.dtype.type(v + tol + 1))
            nz = np.nonzero(m)[0]
            if nz.size:
                m[nz] = np.abs(arr[nz].astype(np.float64) - v) <= tol
            return m
    v = float(value)
    info = np.iinfo(NP[kind])
    if v != int(v) or not (info.min <= int(v) <= info.max):     # 소수·범위 밖 값은 그 정수형에서 찾을 수 없음
        return np.zeros(arr.shape, bool)
    return arr == NP[kind](int(v))


class Scan:
    """한 번의 찾기(처음 → 다시 → 다시…). 후보: kind 마다 (주소 배열, 지난 값 배열)."""

    def __init__(self, reader: ProcessReader, kind: str = "auto", tol: float = 0.5, progress=None, stop=None):
        self.r = reader
        self.kinds = list(AUTO_KINDS) if kind == "auto" else [kind]
        for k in self.kinds:
            if k not in NP:
                raise ValueError(k)
        self.tol = tol
        self.cands: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
        self.unknown: Optional[List[Tuple[int, bytes]]] = None     # '모르는 처음 값' 이면 통째로 담아 둔 메모리
        self.progress = progress or (lambda done, total: None)
        self.stop = stop or (lambda: False)
        self.rounds = 0

    # -------------------------------------------------- 처음 찾기
    def first(self, value=None):
        """value=None 이면 '모르는 처음 값'(지금 메모리를 담아 두고 다음에 바뀐 것으로 좁힘)."""
        regs = regions(self.r)
        total = sum(s for _, s in regs)
        if value is None:
            if total > MAX_UNKNOWN_BYTES:
                raise MemoryError_(t("처음 값을 모르고 찾기엔 메모리가 너무 큼({mb}MB) — 지금 값을 숫자로 넣어 찾으세요",
                                     mb=total >> 20))
            self.unknown = []
        done = 0
        found = {k: ([], []) for k in self.kinds}
        n_found = 0
        for base, size in regs:
            off = 0
            while off < size:
                if self.stop():
                    raise MemoryError_(t("찾기를 멈춤"))
                n = min(CHUNK, size - off)
                raw = _read_safe(self.r, base + off, n)
                if raw is not None:
                    if value is None:
                        self.unknown.append((base + off, raw))
                    else:
                        for k in self.kinds:
                            for start, step, vals in _views(raw, k):
                                hit = np.nonzero(_match(vals, k, value, self.tol))[0]
                                if hit.size:
                                    found[k][0].append(base + off + start + hit.astype(np.int64) * step)
                                    found[k][1].append(vals[hit].copy())
                                    n_found += hit.size
                                if n_found > MAX_RESULTS:
                                    raise MemoryError_(t("후보가 너무 많음 — 값이 바뀐 뒤 다시 찾거나 자료형을 정하세요"))
                off += n
                done += n
                self.progress(done, total)
        if value is not None:
            self.cands = {k: (np.concatenate(found[k][0]) if found[k][0] else np.zeros(0, np.int64),
                              np.concatenate(found[k][1]) if found[k][1] else np.zeros(0, NP[k]))
                          for k in self.kinds}
        self.rounds = 1
        return self.count()

    # -------------------------------------------------- 다시 찾기
    def _now(self, kind: str, addrs: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """후보 주소들의 지금 값(못 읽은 곳은 ok=False). 가까운 주소끼리 묶어 한 번에 읽는다."""
        size = KINDS[kind][1]
        vals = np.zeros(addrs.size, NP[kind])
        ok = np.zeros(addrs.size, bool)
        if not addrs.size:
            return vals, ok
        order = np.argsort(addrs, kind="stable")
        sa = addrs[order]
        i = 0
        while i < sa.size:
            if self.stop():
                raise MemoryError_(t("찾기를 멈춤"))
            start = int(sa[i])
            j = int(np.searchsorted(sa, start + CHUNK - size, side="right"))
            j = max(j, i + 1)
            end = int(sa[j - 1]) + size
            raw = _read_safe(self.r, start, end - start)
            if raw is None:                       # 묶음이 안 읽히면 하나씩
                for q in range(i, j):
                    one = _read_safe(self.r, int(sa[q]), size)
                    if one is not None:
                        vals[order[q]] = np.frombuffer(one, NP[kind])[0]
                        ok[order[q]] = True
            else:
                buf = np.frombuffer(raw, np.uint8)
                offs = (sa[i:j] - start).astype(np.int64)
                idx = offs[:, None] + np.arange(size)[None, :]
                vals[order[i:j]] = buf[idx].copy().view(NP[kind]).reshape(-1)
                ok[order[i:j]] = True
            i = j
        return vals, ok

    def _from_unknown(self):
        """'모르는 처음 값' 뒤 첫 '다시 찾기': 담아 둔 메모리 전체를 후보로 펼친다."""
        cands = {}
        for k in self.kinds:
            a, item = _align(k), KINDS[k][1]
            addrs, vals = [], []
            for base, raw in self.unknown:
                usable = (len(raw) - item) // a * a + item if len(raw) >= item else 0
                if not usable:
                    continue
                arr = np.lib.stride_tricks.as_strided(np.frombuffer(raw, np.uint8),
                                                      shape=((usable - item) // a + 1, item), strides=(a, 1))
                v = arr.copy().view(NP[k]).reshape(-1)
                addrs.append(base + np.arange(v.size, dtype=np.int64) * a)
                vals.append(v)
            cands[k] = (np.concatenate(addrs) if addrs else np.zeros(0, np.int64),
                        np.concatenate(vals) if vals else np.zeros(0, NP[k]))
        self.unknown = None
        return cands

    def next(self, mode: str, value=None, value2=None):
        if mode not in MODES:
            raise ValueError(mode)
        if self.unknown is not None:
            if mode in ("eq", "between"):
                self.unknown = None                 # 숫자를 알게 됐으면 그냥 처음 찾기처럼
                return self.first(value) if mode == "eq" else self.count()
            self.cands = self._from_unknown()
        new = {}
        for k, (addrs, old) in self.cands.items():
            cur, ok = self._now(k, addrs)
            with np.errstate(invalid="ignore", over="ignore"):
                f = cur.astype(np.float64)
                o = old.astype(np.float64)
            tol = self.tol if k in ("float", "double") else 0
            if mode == "eq":
                keep = _match(cur, k, value, self.tol)
            elif mode == "between":
                keep = (f >= float(value) - tol) & (f <= float(value2) + tol)
            elif mode == "changed":
                keep = np.abs(f - o) > (1e-6 if tol else 0)
            elif mode == "unchanged":
                keep = np.abs(f - o) <= (1e-6 if tol else 0)
            elif mode == "increased":
                keep = f > o
            elif mode == "decreased":
                keep = f < o
            elif mode == "inc_by":
                keep = np.abs((f - o) - float(value)) <= tol
            else:
                keep = np.abs((o - f) - float(value)) <= tol
            keep &= ok
            if k in ("float", "double"):
                keep &= np.isfinite(f)
            new[k] = (addrs[keep], cur[keep])
        self.cands = new
        self.rounds += 1
        return self.count()

    # -------------------------------------------------- 결과
    def count(self) -> int:
        if self.unknown is not None:
            return -1                               # 아직 모름(담아 둔 상태)
        return int(sum(a.size for a, _ in self.cands.values()))

    def results(self, limit: int = 200) -> List[dict]:
        """[{address, kind, value}] — 자료형 우선순위(int32 → float → …) 순."""
        out = []
        for k in self.kinds:
            addrs, vals = self.cands.get(k, (np.zeros(0), np.zeros(0)))
            for a, v in zip(addrs[:max(0, limit - len(out))], vals[:max(0, limit - len(out))]):
                vv = v.item()
                out.append({"address": int(a), "kind": k, "value": round(vv, 6) if isinstance(vv, float) else vv})
            if len(out) >= limit:
                break
        return out

    def guess_kind(self) -> Optional[str]:
        """후보가 남은 자료형이 하나뿐이면 그것."""
        left = [k for k, (a, _) in self.cands.items() if a.size]
        return left[0] if len(left) == 1 else None


def spec_for(reader: ProcessReader, address: int, kind: str) -> dict:
    """찾은 주소를 저장할 모양으로: 실행 파일·DLL 안이면 '모듈 + 위치'(다시 켜도 같을 수 있음), 아니면 절대 주소."""
    best = None
    for name, base in reader.modules().items():
        if base <= address and (best is None or base > best[1]):
            best = (name, base)
    spec = {"offset": hex(address), "kind": kind}
    if best is not None:
        size = _module_size(reader, best[0])
        if size and address < best[1] + size:
            spec = {"module": best[0], "offset": hex(address - best[1]), "kind": kind}
    return spec


def _module_size(reader, name) -> int:
    k = reader.k
    from .memory import _MODULEENTRY32W
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k.CreateToolhelp32Snapshot(0x8 | 0x10, reader.pid)
    try:
        me = _MODULEENTRY32W()
        me.dwSize = ctypes.sizeof(me)
        ok = k.Module32FirstW(snap, ctypes.byref(me))
        while ok:
            if me.szModule.lower() == name:
                return int(me.modBaseSize)
            ok = k.Module32NextW(snap, ctypes.byref(me))
    finally:
        k.CloseHandle(snap)
    return 0

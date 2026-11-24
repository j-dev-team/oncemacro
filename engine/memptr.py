"""메모리 매크로 4번: 다시 켜도 찾기 — 포인터 경로 찾기. Qt 없음.

프로그램을 다시 켜면 값의 주소가 바뀐다. 하지만 실행 파일·DLL(모듈) 안의 고정된 자리에서 시작해
'주소를 담은 칸'을 몇 번 따라가면 늘 그 값에 닿는 길(포인터 경로)이 있는 경우가 많다.
찾는 법(거꾸로): 값 주소 X 를 가리키는(X-오프셋 이내) 8바이트 칸들을 메모리 전체에서 찾고, 그중 모듈 안에 있는 칸이 있으면 끝.
없으면 그 칸들을 다시 같은 방식으로(최대 depth 단계). 결과는 engine.memory 주소 모양 {module, offset, pointers}.
다시 켠 뒤 같은 경로로 값을 읽어 맞는지 확인(verify)한다.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from .i18n import t
from .memory import MemoryError_, ProcessReader
from .memscan import CHUNK, _read_safe, regions


def _modules_ranges(reader: ProcessReader) -> List[Tuple[str, int, int]]:
    from .memscan import _module_size
    out = []
    for name, base in reader.modules().items():
        size = _module_size(reader, name)
        if size:
            out.append((name, base, base + size))
    return out


def _all_pointer_cells(reader: ProcessReader, targets: np.ndarray, max_off: int, include_modules: bool = True):
    """targets(정렬) 중 하나를 [t-max_off, t] 로 가리키는 8바이트 칸들: [(칸 주소, 가리키는 값, 맞은 대상)]"""
    out = []
    regs = regions(reader)                               # 쓰기 가능한 곳(모듈의 .data 포함)
    for base, size in regs:
        off = 0
        while off < size:
            n = min(CHUNK, size - off)
            raw = _read_safe(reader, base + off, n)
            if raw is not None and len(raw) >= 8:
                u = np.frombuffer(raw[: len(raw) // 8 * 8], dtype=np.uint64)
                plausible = (u >= 0x10000) & (u <= 0x7FFFFFFFFFFF)      # 주소로 쓸 수 있는 값만(빈 칸·큰 수 빼기)
                vals = np.where(plausible, u, 0).astype(np.int64)
                # 각 값 v 에 대해 v <= t <= v+max_off 인 대상 t 가 있는지
                idx = np.searchsorted(targets, vals, side="left")
                ok = idx < targets.size
                hit = np.zeros(vals.size, bool)
                hit[ok] = (targets[idx[ok]] - vals[ok]) <= max_off
                hit &= plausible
                for i in np.nonzero(hit)[0]:
                    out.append((base + off + int(i) * 8, int(vals[i]), int(targets[idx[i]])))
            off += n
    return out


def find_paths(reader: ProcessReader, address: int, depth: int = 3, max_off: int = 0x800,
               max_paths: int = 20, level_cap: int = 4000, keep_going: bool = False) -> List[dict]:
    """address 에 닿는 '모듈 + 위치 → 포인터들' 경로 후보. 짧은 것부터.
    keep_going=True 면 짧은 경로를 찾아도 depth 까지 더 깊이 모은다(다시 켜면 짧은 경로가 끊기는 게임용,
    2026-11-19 여름의 아지트: 3단계 경로 15개가 다시 켠 뒤 모두 어긋남)."""
    mods = _modules_ranges(reader)

    def in_module(a):
        for name, lo, hi in mods:
            if lo <= a < hi:
                return name, a - lo
        return None

    found: List[dict] = []
    # frontier: {칸 주소: 그 칸에서 address 까지의 오프셋 목록(뒤쪽부터)}
    frontier: Dict[int, List[int]] = {address: []}
    for level in range(depth):
        targets = np.array(sorted(frontier), dtype=np.int64)
        cells = _all_pointer_cells(reader, targets, max_off)
        nxt: Dict[int, List[int]] = {}
        for cell, ptr, tgt in cells:
            offs = [tgt - ptr] + frontier[tgt]
            m = in_module(cell)
            if m is not None:
                found.append({"module": m[0], "offset": hex(m[1]), "pointers": [hex(o) for o in offs]})
                if len(found) >= max_paths:
                    return _short_first(found)
            elif len(nxt) < level_cap:
                nxt.setdefault(cell, offs)
        if found and not keep_going:
            break                                        # 더 짧은 경로가 있으면 더 깊이 안 감
        frontier = nxt
        if not frontier:
            break
    return _short_first(found)


def _short_first(paths):
    return sorted(paths, key=lambda p: (len(p["pointers"]), int(p["offset"], 16)))


def resolve_path(reader: ProcessReader, path: dict) -> Optional[int]:
    """경로를 따라가 지금 주소. 못 따라가면 None. (engine.memory 의 pointers 는 '읽고 더하기' 순서라 형식 변환)"""
    try:
        mods = reader.modules()
        base = mods.get(path["module"].lower())
        if base is None:
            return None
        addr = base + int(path["offset"], 16)
        offs = [int(o, 16) for o in path["pointers"]]
        for o in offs:
            ptr = int(np.frombuffer(reader.read(addr, 8), dtype=np.uint64)[0])
            if not ptr:
                return None
            addr = ptr + o
        return addr
    except (MemoryError_, KeyError, ValueError):
        return None


def to_spec(path: dict, kind: str) -> dict:
    """찾은 경로 → engine.memory 주소 모양(저장·매크로 단계에 그대로)."""
    return {"module": path["module"], "offset": path["offset"], "pointers": list(path["pointers"]), "kind": kind}


def verify(reader: ProcessReader, paths: List[dict], kind: str, expect) -> List[dict]:
    """지금 값이 expect 인 경로만(다시 켠 뒤 걸러내기)."""
    ok = []
    for p in paths:
        try:
            if reader.value(to_spec(p, kind)) == expect:
                ok.append(p)
        except MemoryError_:
            pass
    return ok



def save_candidates(paths: List[dict], kind: str, path: str, note: str = ""):
    """다시 켠 뒤 겹쳐 보려고 후보 경로를 파일로."""
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"kind": kind, "note": note, "paths": paths}, f, ensure_ascii=False)


def load_candidates(path: str) -> dict:
    import json
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def stable_paths(candidates: List[dict], reader: ProcessReader, kind: str, expect) -> List[dict]:
    """다시 켠 뒤에도 같은 값에 닿는 경로만(두 번·세 번 켠 결과 겹치기). verify 와 같지만 이름을 분명히."""
    return verify(reader, candidates, kind, expect)

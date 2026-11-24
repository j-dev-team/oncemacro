"""메모리 매크로: 무늬 찾기(다시 켜도 찾기의 다른 길) + 계산되는 값 스스로 맞추기. Qt 없음.

무늬 찾기: 값 바로 앞뒤의 바이트(그 객체의 모양)를 무늬로 저장해 두었다가, 다시 켠 뒤 메모리 전체에서 같은 무늬를 찾는다.
  포인터처럼 보이는 8바이트(켤 때마다 바뀜)와 값 자체는 '아무거나(??)'로 둔다.
목표 맞추기(goal seek): 레벨처럼 '다른 값(점수)에서 계산되는 값'은 바로 못 바꾼다. 점수를 바꿔 넣고, 결과(레벨)를
  읽어(메모리나 화면 숫자) 목표에 닿을 때까지 반씩 좁혀 가며 스스로 맞춘다 — 사람에게 숫자를 묻지 않는다.
"""
from __future__ import annotations

import struct
import time
from typing import Callable, List, Optional, Tuple

import numpy as np

from .i18n import t
from .memory import KINDS, MemoryError_
from .memscan import CHUNK, _read_safe, regions


# ------------------------------------------------------------ 무늬 찾기
def capture(reader, addr: int, kind: str = "int32", before: int = 32, after: int = 32, min_distinct: int = 12) -> dict:
    """addr 주변 바이트를 무늬로. 0 이 아닌 고정 바이트가 min_distinct 개가 될 때까지 앞뒤를 넓힌다(최대 512).
    돌려줌: {pattern: "aa bb ?? ..", value_at: 값까지 거리, kind}"""
    while True:
        sig = _capture(reader, addr, kind, before, after)
        vals, care = _parse(sig["pattern"])
        if int(((vals != 0) & care).sum()) >= min_distinct or before >= 512:
            return sig
        before, after = before * 2, after * 2


def _capture(reader, addr: int, kind: str, before: int, after: int) -> dict:
    size = KINDS[kind][1]
    start = addr - before
    raw = reader.read(start, before + size + after)
    mask = [True] * len(raw)
    for i in range(before, before + size):              # 값 자체는 바뀌니 빼기
        mask[i] = False
    for i in range(0, len(raw) - 7, 1):                  # 포인터처럼 보이는 8바이트(정렬된 것)는 빼기
        if (start + i) % 8:
            continue
        q = struct.unpack_from("<Q", raw, i)[0]
        if 0x10000 <= q <= 0x7FFFFFFFFFFF:
            for k in range(i, i + 8):
                mask[k] = False
    pat = " ".join(f"{b:02x}" if m else "??" for b, m in zip(raw, mask))
    return {"pattern": pat, "value_at": before, "kind": kind}


def _parse(pat: str) -> Tuple[np.ndarray, np.ndarray]:
    parts = pat.split()
    vals = np.array([0 if p == "??" else int(p, 16) for p in parts], dtype=np.uint8)
    care = np.array([p != "??" for p in parts], dtype=bool)
    return vals, care


def find(reader, sig: dict, limit: int = 50) -> List[int]:
    """무늬가 맞는 곳들의 '값 주소' 목록."""
    vals, care = _parse(sig["pattern"])
    n = len(vals)
    if care.sum() < 8 or int(((vals != 0) & care).sum()) < 4:
        raise MemoryError_(t("무늬가 너무 약해요(구별되는 바이트가 모자람)"))
    anchor = int(np.argmax(care))                       # 처음 '고정된' 바이트로 먼저 거르기
    out = []
    for base, size in regions(reader):
        off = 0
        while off < size and len(out) < limit:
            m = min(CHUNK + n, size - off)
            raw = _read_safe(reader, base + off, m)
            if raw is not None and len(raw) >= n:
                buf = np.frombuffer(raw, dtype=np.uint8)
                cand = np.nonzero(buf[anchor: len(buf) - n + anchor + 1] == vals[anchor])[0]
                for c in cand:
                    seg = buf[c: c + n]
                    if seg.size == n and np.all((seg == vals) | ~care):
                        out.append(base + off + int(c) + int(sig["value_at"]))
                        if len(out) >= limit:
                            break
            off += CHUNK
    return sorted(set(out))


def find_near(reader, sig: dict, value_addr: int) -> List[int]:
    """그 자리 하나만 무늬가 맞는지(빠른 확인). 맞으면 [value_addr], 아니면 []."""
    vals, care = _parse(sig["pattern"])
    start = value_addr - int(sig["value_at"])
    if int(((vals != 0) & care).sum()) < 4:
        return []
    try:
        buf = np.frombuffer(reader.read(start, len(vals)), dtype=np.uint8)
    except MemoryError_:
        return []
    return [value_addr] if np.all((buf == vals) | ~care) else []


# ------------------------------------------------------------ 목표 맞추기
def goal_seek(set_input: Callable[[float], None], read_output: Callable[[], Optional[float]], target: float,
              lo: float, hi: float, integer: bool = True, settle: float = 0.3, max_steps: int = 30,
              progress: Callable[[str], None] = lambda s: None) -> Optional[float]:
    """출력이 target 이 되는 가장 작은 입력을 찾는다(입력이 클수록 출력이 크거나 같다고 봄).
    돌려줌: 찾은 입력(출력이 target 이 됨) / 못 찾으면 None. 끝나면 그 입력이 들어가 있다."""

    def out_at(x):
        set_input(int(round(x)) if integer else x)
        time.sleep(settle)
        return read_output()

    o = out_at(hi)
    if o is None or o < target:
        return None                                     # 가장 큰 입력으로도 못 닿음
    steps = 0
    while (hi - lo) > (1 if integer else 1e-6) and steps < max_steps:
        mid = (lo + hi) / 2
        if integer:
            mid = int(mid)
        o = out_at(mid)
        steps += 1
        progress(t("입력 {x} → 결과 {o}", x=mid, o=o))
        if o is not None and o >= target:
            hi = mid
        else:
            lo = mid
    o = out_at(hi)
    return hi if o == target else None

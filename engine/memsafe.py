"""메모리 매크로: 안전하게 쓰기(2026-11-18 게임이 꺼진 일의 고침).

그날: 같은 값을 가진 후보 96곳에 한꺼번에 새 값을 썼더니, 돈이 아닌 자리(포인터·개수 등)가 바뀌어 게임이 꺼졌다.
그래서 쓰기 전에:
1) 후보 줄이기 — 잠깐 지켜보는 동안 값이 바뀌는 자리, 파일을 비춘 영역(MEM_MAPPED), 8바이트 포인터의 일부로 보이는 자리를 뺀다.
2) 저장 폴더 자동 백업(찾을 수 있을 때).
3) 몇 개씩 나눠 쓰고, 쓸 때마다 프로그램이 살아 있는지 확인. 죽으면 바로 멈춘다.
4) 자동으로 좁히기: 반으로 나눠 써 보고(나눠 쓰기로) 화면 숫자가 바뀌는지로 진짜 자리를 고른 뒤, 나머지는 원래 값으로 되돌린다.
Qt 없음.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import struct
import time
from ctypes import wintypes
from typing import Callable, Dict, List, Optional

from .i18n import t
from .memory import KINDS, MemoryError_
from .memscan import _MBI

MEM_MAPPED = 0x40000
MEM_COMMIT = 0x1000


def _region(reader, addr: int):
    k = reader.k
    k.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(_MBI), ctypes.c_size_t]
    k.VirtualQueryEx.restype = ctypes.c_size_t
    mbi = _MBI()
    if not k.VirtualQueryEx(reader.h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
        return None
    return mbi


def _committed(reader, addr: int) -> bool:
    if addr < 0x10000 or addr > (0x7FFFFFFFFFFF if reader.ptr_size == 8 else 0x7FFFFFFF):
        return False
    m = _region(reader, addr)
    return bool(m and m.State == MEM_COMMIT)


def looks_pointer(reader, addr: int) -> bool:
    """addr 의 4바이트가 8바이트 포인터의 아래·위 절반으로 보이면 True."""
    if reader.ptr_size != 8:
        return False
    base = addr - (addr % 8)
    try:
        q = struct.unpack("<Q", reader.read(base, 8))[0]
    except MemoryError_:
        return False
    return q > 0xFFFFFFFF and _committed(reader, q)


def narrow_safe(reader, addrs: List[int], kind: str, expect, watch: float = 1.5, polls: int = 4) -> Dict[str, list]:
    """후보 줄이기. 돌려줌: {"keep": [...], "changing": [...], "mapped": [...], "pointer": [...]}"""
    out = {"keep": [], "changing": [], "mapped": [], "pointer": []}
    seen = {a: [] for a in addrs}
    for i in range(polls):
        for a in addrs:
            try:
                seen[a].append(reader.value({"offset": a, "kind": kind}))
            except MemoryError_:
                seen[a].append(None)
        if i < polls - 1:
            time.sleep(watch / max(1, polls - 1))
    cache = {}
    for a in addrs:
        vals = seen[a]
        if any(v != vals[0] for v in vals) or (expect is not None and vals[0] != expect):
            out["changing"].append(a)
            continue
        base = a & ~0xFFFF
        if base not in cache:
            m = _region(reader, a)
            cache[base] = m.Type if m else 0
        if cache[base] == MEM_MAPPED:
            out["mapped"].append(a)
            continue
        if kind in ("int32", "uint32", "float") and looks_pointer(reader, a):
            out["pointer"].append(a)
            continue
        out["keep"].append(a)
    return out


def alive(pid: int) -> bool:
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    h = k.OpenProcess(0x1000, False, int(pid))
    if not h:
        return False
    code = wintypes.DWORD()
    try:
        k.GetExitCodeProcess(h, ctypes.byref(code))
        return code.value == 259            # STILL_ACTIVE
    finally:
        k.CloseHandle(h)


def write_batches(writer, addrs: List[int], kind: str, value, batch: int = 4, pause: float = 0.25,
                  stop: Callable[[], bool] = lambda: False) -> Dict[int, object]:
    """몇 개씩 나눠 쓰고 쓸 때마다 살아 있는지 확인. 돌려줌: {주소: 원래 값}(되돌리기용). 죽으면 MemoryError_."""
    olds: Dict[int, object] = {}
    for i in range(0, len(addrs), max(1, batch)):
        if stop():
            break
        part = addrs[i:i + batch]
        for a in part:
            try:
                olds[a] = writer.value({"offset": a, "kind": kind})
                writer.write({"offset": a, "kind": kind}, value)
            except MemoryError_:
                pass
        time.sleep(pause)
        if not alive(writer.pid):
            raise MemoryError_(t("쓰는 도중 프로그램이 꺼졌어요(돈이 아닌 자리였을 수 있음). 저장을 불러오세요"))
    return olds


def restore(writer, olds: Dict[int, object], kind: str, written):
    """우리가 쓴 값이 그대로인 곳만 원래 값으로(그 사이 프로그램이 바꾼 곳은 그대로 둠)."""
    for a, old in olds.items():
        try:
            if writer.value({"offset": a, "kind": kind}) == written and old is not None:
                writer.write({"offset": a, "kind": kind}, old)
        except MemoryError_:
            pass


def auto_narrow(writer, addrs: List[int], kind: str, value, screen_changed: Callable[[], bool],
                progress: Callable[[str], None] = lambda s: None, settle: float = 1.5) -> Optional[int]:
    """써 보고 확인하며 반씩 좁히기. screen_changed(): 마지막 확인 뒤 화면 숫자가 바뀌었는지.
    진짜 자리를 찾으면 그 주소(그곳엔 value 가 남음), 화면이 안 바뀌면 None. 나머지는 되돌림."""
    cands = list(addrs)
    screen_changed()                                   # 기준 잡기

    def trial(part):
        olds = write_batches(writer, part, kind, value)
        t0 = time.time()
        hit = False
        while time.time() - t0 < settle:
            time.sleep(0.25)
            if screen_changed():
                hit = True
                break
        restore(writer, olds, kind, value)
        time.sleep(0.5)
        screen_changed()                               # 되돌린 뒤 기준 다시
        return hit

    if not trial(cands):
        return None
    while len(cands) > 1:
        half = cands[:len(cands) // 2]
        cands = half if trial(half) else cands[len(cands) // 2:]
        progress(t("남은 후보 {n}개", n=len(cands)))
    writer.write({"offset": cands[0], "kind": kind}, value)
    return cands[0]


# ------------------------------------------------------------ 저장 폴더 찾기·백업
def save_folders(exe_path: str) -> List[str]:
    """그 프로그램의 저장 폴더 후보(있는 것만). 언리얼·유니티·렌파이에서 흔한 자리."""
    if not exe_path:
        return []
    d = os.path.dirname(os.path.abspath(exe_path))
    name = os.path.splitext(os.path.basename(exe_path))[0].split("-")[0]
    cands = []
    up = d
    for _ in range(5):                                  # 언리얼: <게임>/Saved/SaveGames, UserData/Saved/SaveGames
        for sub in ("Saved/SaveGames", "UserData/Saved/SaveGames", "game/saves", "saves", "Save", "SaveData"):
            cands.append(os.path.join(up, sub))
        up = os.path.dirname(up)
    la = os.environ.get("LOCALAPPDATA", "")
    ap = os.environ.get("APPDATA", "")
    if la:
        cands.append(os.path.join(la, name, "Saved", "SaveGames"))
        low = os.path.join(os.path.dirname(la), "LocalLow")
        if os.path.isdir(low):
            for comp in os.listdir(low):
                cands.append(os.path.join(low, comp, name))
    if ap:
        rp = os.path.join(ap, "RenPy")
        if os.path.isdir(rp):
            cands += [os.path.join(rp, x) for x in os.listdir(rp) if name.lower() in x.lower()]
    seen, out = set(), []
    for c in cands:
        c = os.path.normpath(c)
        if c not in seen and os.path.isdir(c) and os.listdir(c):
            seen.add(c)
            out.append(c)
    return out


def backup_saves(exe_path: str, root: Optional[str] = None) -> List[str]:
    """저장 폴더를 memory/backups/<프로그램>_<시각>/ 로 복사. 돌려줌: 만든 백업 폴더들."""
    if root is None:
        from .real import PROJECT_ROOT as root
    made = []
    stamp = time.strftime("%Y%m%d_%H%M%S")
    prog = os.path.splitext(os.path.basename(exe_path or "program"))[0]
    for i, f in enumerate(save_folders(exe_path)):
        dst = os.path.join(root, "memory", "backups", f"{prog}_{stamp}" + (f"_{i + 1}" if i else ""))
        shutil.copytree(f, dst)
        with open(os.path.join(dst, "_original_location.txt"), "w", encoding="utf-8") as fh:
            fh.write(f + "\n")
        made.append(dst)
    return made


def exe_path(pid: int) -> str:
    """프로그램 번호 → 실행 파일 전체 경로(못 얻으면 '')."""
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    h = k.OpenProcess(0x1000, False, int(pid))
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(1024)
        if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return buf.value
        return ""
    finally:
        k.CloseHandle(h)

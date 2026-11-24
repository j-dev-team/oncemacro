"""메모리 매크로(부가 기능): 대상 프로그램의 메모리 값을 '읽기만' 한다. 설계: docs/메모리_매크로_설계.md

- 읽기 전용으로 붙음: OpenProcess(PROCESS_VM_READ | QUERY_LIMITED_INFORMATION) + ReadProcessMemory.
  대상 프로그램에 아무것도 넣지 않고, '뒤에서 실행'과도 따로 동작한다.
- 기본은 꺼짐: settings/addons.json 의 {"memory": true} 일 때만 실행된다(enabled()).
- 주소 모양: {"process"?, "module"?, "offset", "pointers"?, "kind", "length"?}
  모듈이 없으면 offset 이 절대 주소. pointers 가 있으면 [기준]을 읽고 오프셋을 더해 가며 따라간다.
- 저장한 이름: memory/values.json {이름: 주소 모양}.
값 쓰기는 이 판에 없다(설계 6번, 맨 뒤).
"""
from __future__ import annotations

import ctypes
import json
import os
import struct
from ctypes import wintypes
from typing import Any, Dict, List, Optional, Union

from .i18n import t

KINDS = {"int8": ("b", 1), "uint8": ("B", 1), "int16": ("h", 2), "uint16": ("H", 2), "int32": ("i", 4),
         "uint32": ("I", 4), "int64": ("q", 8), "uint64": ("Q", 8), "float": ("f", 4), "double": ("d", 8)}
TEXT_KINDS = ("text", "text16")          # text = UTF-8(1바이트 글자 포함), text16 = UTF-16(윈도우 넓은 글자)
ALL_KINDS = tuple(KINDS) + TEXT_KINDS
ADDR_KEYS = {"process", "module", "offset", "pointers", "kind", "length", "note", "hotkey", "freeze_to", "pattern"}

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class MemoryError_(RuntimeError):
    pass


# ------------------------------------------------------------ 켜고 끄기·저장한 이름
def _root(root: Optional[str] = None) -> str:
    if root:
        return root
    from .real import PROJECT_ROOT
    return PROJECT_ROOT


def addons_path(root: Optional[str] = None) -> str:
    return os.path.join(_root(root), "settings", "addons.json")


def addons(root: Optional[str] = None) -> dict:
    try:
        with open(addons_path(root), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def enabled(root: Optional[str] = None) -> bool:
    return bool(addons(root).get("memory"))


def set_enabled(on: bool, root: Optional[str] = None):
    d = addons(root)
    d["memory"] = bool(on)
    p = addons_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def values_path(root: Optional[str] = None) -> str:
    return os.path.join(_root(root), "memory", "values.json")


def load_values(root: Optional[str] = None) -> Dict[str, dict]:
    try:
        with open(values_path(root), encoding="utf-8") as f:
            d = json.load(f)
        return {k: v for k, v in d.items() if isinstance(v, dict)} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_value(name: str, spec: dict, root: Optional[str] = None):
    d = load_values(root)
    d[name] = {k: v for k, v in spec.items() if k in ADDR_KEYS}
    p = values_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def to_int(v: Union[int, str]) -> int:
    if isinstance(v, bool):
        raise ValueError
    if isinstance(v, int):
        return v
    s = str(v).strip().lower().replace("_", "")
    neg = s.startswith("-")
    s = s.lstrip("+-")
    n = int(s, 16) if s.startswith("0x") else int(s, 16) if any(c in "abcdef" for c in s) else int(s)
    return -n if neg else n


def check_spec(spec: Any) -> List[str]:
    """주소 모양 검사. 돌려줌: 문제 설명 목록."""
    errs = []
    if not isinstance(spec, dict):
        return [t("주소는 객체여야 함")]
    for k in spec:
        if k not in ADDR_KEYS:
            errs.append(t("모르는 칸 '{key}'", key=k))
    if "offset" not in spec and not isinstance(spec.get("pattern"), dict):
        errs.append(t("offset(주소 또는 모듈 안 위치)이 필요"))
    elif "offset" in spec:
        try:
            to_int(spec["offset"])
        except (ValueError, TypeError):
            errs.append(t("offset 은 숫자나 0x 로 시작하는 16진수"))
    for p in spec.get("pointers") or []:
        try:
            to_int(p)
        except (ValueError, TypeError):
            errs.append(t("pointers 는 숫자 목록"))
            break
    if spec.get("kind", "int32") not in ALL_KINDS:
        errs.append(t("kind 는 {kinds} 중 하나", kinds=" / ".join(ALL_KINDS)))
    if spec.get("kind") in TEXT_KINDS and "length" in spec and not (isinstance(spec["length"], int) and 0 < spec["length"] <= 4096):
        errs.append(t("length 는 1~4096"))
    return errs


# ------------------------------------------------------------ 윈도우 읽기
class _MODULEENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("th32ModuleID", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("GlblcntUsage", wintypes.DWORD), ("ProccntUsage", wintypes.DWORD),
                ("modBaseAddr", ctypes.c_void_p), ("modBaseSize", wintypes.DWORD), ("hModule", wintypes.HMODULE),
                ("szModule", ctypes.c_wchar * 256), ("szExePath", ctypes.c_wchar * 260)]


class ProcessReader:
    """한 프로그램에 읽기 전용으로 붙음. close() 로 뗀다."""

    def __init__(self, pid: int):
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                        ctypes.POINTER(ctypes.c_size_t)]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
        self.k = k
        self.pid = int(pid)
        self.h = k.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION, False, self.pid)
        if not self.h:
            err = ctypes.get_last_error()
            raise MemoryError_(t("이 프로그램은 메모리 매크로를 쓸 수 없어요(읽기로 붙지 못함, 오류 {code}). 화면 인식으로 진행해요",
                                 code=err))
        wow = wintypes.BOOL(0)
        try:
            k.IsWow64Process(self.h, ctypes.byref(wow))
        except Exception:
            pass
        self.ptr_size = 4 if wow.value else 8          # 32비트 프로그램이면 포인터 4바이트
        self._modules: Optional[Dict[str, int]] = None

    def close(self):
        if self.h:
            self.k.CloseHandle(self.h)
            self.h = None

    def read(self, addr: int, size: int) -> bytes:
        if not self.h:
            raise MemoryError_(t("이미 떨어진 프로그램"))
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t(0)
        ok = self.k.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got))
        if not ok or got.value != size:
            raise MemoryError_(t("주소 {addr} 를 읽지 못함(없는 곳이거나 바뀜)", addr=hex(addr)))
        return buf.raw

    def modules(self) -> Dict[str, int]:
        """{모듈 이름(소문자): 시작 주소}"""
        if self._modules is None:
            k = self.k
            k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
            snap = k.CreateToolhelp32Snapshot(0x8 | 0x10, self.pid)     # MODULE | MODULE32
            out: Dict[str, int] = {}
            if snap and snap != wintypes.HANDLE(-1).value:
                try:
                    me = _MODULEENTRY32W()
                    me.dwSize = ctypes.sizeof(me)
                    ok = k.Module32FirstW(snap, ctypes.byref(me))
                    while ok:
                        out.setdefault(me.szModule.lower(), int(me.modBaseAddr or 0))
                        ok = k.Module32NextW(snap, ctypes.byref(me))
                finally:
                    k.CloseHandle(snap)
            self._modules = out
        return self._modules

    def resolve(self, spec: dict) -> int:
        """주소 모양 → 지금 주소. 무늬(pattern)가 있으면: offset 으로 읽히고 무늬가 맞으면 그대로,
        아니면(다시 켜서 옮겨 감) 무늬로 메모리를 찾아 첫 자리(찾은 것은 이 실행 동안 기억)."""
        if isinstance(spec.get("pattern"), dict) and not spec.get("pointers"):
            return self._resolve_pattern(spec)
        return self._resolve_plain(spec)

    def _resolve_pattern(self, spec: dict) -> int:
        from . import mempattern as mpat
        key = spec["pattern"].get("pattern", "")
        cache = self.__dict__.setdefault("_pattern_hits", {})
        if key in cache:
            return cache[key]
        if "offset" in spec:
            try:
                a = self._resolve_plain(spec)
                if a in mpat.find_near(self, spec["pattern"], a):
                    cache[key] = a
                    return a
            except MemoryError_:
                pass
        hits = mpat.find(self, spec["pattern"], limit=20)
        if not hits:
            raise MemoryError_(t("무늬로도 그 값을 찾지 못했어요(프로그램 판이 바뀌었을 수 있음)"))
        cache[key] = hits[0]
        return hits[0]

    def _resolve_plain(self, spec: dict) -> int:
        base = 0
        if spec.get("module"):
            mods = self.modules()
            base = mods.get(str(spec["module"]).lower())
            if base is None:
                raise MemoryError_(t("모듈 '{name}' 이 그 프로그램에 없음", name=spec["module"]))
        addr = base + to_int(spec["offset"])
        for off in spec.get("pointers") or []:
            raw = self.read(addr, self.ptr_size)
            ptr = struct.unpack("<I" if self.ptr_size == 4 else "<Q", raw)[0]
            if not ptr:
                raise MemoryError_(t("포인터를 따라가다 빈 곳(0)을 만남"))
            addr = ptr + to_int(off)
        return addr

    def value(self, spec: dict):
        kind = spec.get("kind", "int32")
        addr = self.resolve(spec)
        if kind in KINDS:
            fmt, size = KINDS[kind]
            v = struct.unpack("<" + fmt, self.read(addr, size))[0]
            return round(v, 6) if kind in ("float", "double") else v
        n = int(spec.get("length", 64))
        raw = self.read(addr, n * (2 if kind == "text16" else 1))
        txt = raw.decode("utf-16-le" if kind == "text16" else "utf-8", errors="replace")
        return txt.split("\x00", 1)[0]


def pid_of_process(name: str) -> Optional[int]:
    from .office_guard import processes
    want = name.upper() if name.lower().endswith(".exe") else (name + ".exe").upper()
    for pid, n in processes([want]).items():
        return pid
    return None


def pid_of_window(hwnd: int) -> Optional[int]:
    from .office_guard import pid_of_hwnd
    return pid_of_hwnd(hwnd)


class MemorySession:
    """한 번의 매크로 실행 동안 프로그램별 ProcessReader 를 들고 있다가 close() 에서 모두 뗀다."""

    def __init__(self, reader_factory=ProcessReader):
        self.readers: Dict[int, ProcessReader] = {}
        self.factory = reader_factory

    def reader(self, pid: int):
        r = self.readers.get(pid)
        if r is None:
            r = self.readers[pid] = self.factory(pid)
        return r

    def close(self):
        for r in self.readers.values():
            try:
                r.close()
            except Exception:
                pass
        self.readers.clear()


def delete_value(name: str, root: Optional[str] = None):
    d = load_values(root)
    if d.pop(name, None) is not None:
        with open(values_path(root), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)


def values_for(process: str, root: Optional[str] = None) -> Dict[str, dict]:
    """그 프로그램(실행 파일 이름) 것만. process 를 안 적은 값도 함께."""
    p = (process or "").lower()
    return {k: v for k, v in load_values(root).items() if not v.get("process") or str(v["process"]).lower() == p}


def export_values(process: str, path: str, root: Optional[str] = None) -> int:
    """그 프로그램의 저장한 값을 파일로(다른 사람과 주고받기)."""
    vals = values_for(process, root)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"program": process, "values": vals}, f, ensure_ascii=False, indent=1)
    return len(vals)


def import_values(path: str, root: Optional[str] = None) -> int:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    vals = d.get("values") if isinstance(d, dict) else None
    if not isinstance(vals, dict):
        raise MemoryError_(t("값 묶음 파일이 아님"))
    n = 0
    for k, v in vals.items():
        if isinstance(v, dict) and not check_spec(v):
            if d.get("program") and not v.get("process"):
                v["process"] = d["program"]
            save_value(k, v, root)
            n += 1
    return n

"""메모리 매크로 3번: 값 바꾸기·고정(혼자 하는 게임·보호 장치 없는 프로그램용). Qt 없음.

- 쓰기는 읽기와 달리 쓰기 권한(VM_WRITE|VM_OPERATION)으로 붙는다. 쓰기 단계·값 찾기 화면에서만 그렇게 붙는다.
- 고정: 정한 간격마다 그 값으로 되돌려 쓴다(여러 값 한꺼번에, 켜고 끄기).
- 쓴 것은 모두 logs/memory/writes.jsonl 에 남긴다(언제·어느 프로그램·어디·무엇을).
- 보호 장치가 막으면(붙기·쓰기 실패) 그대로 알리고 넘어가려 하지 않는다.
"""
from __future__ import annotations

import ctypes
import json
import os
import struct
import threading
import time
from ctypes import wintypes
from typing import Dict, Optional, Tuple

from .i18n import t
from .memory import KINDS, TEXT_KINDS, MemoryError_, ProcessReader

PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def log_path(root: Optional[str] = None) -> str:
    if root is None:
        from .real import PROJECT_ROOT as root
    return os.path.join(root, "logs", "memory", "writes.jsonl")


def _log(rec: dict, root: Optional[str] = None):
    try:
        p = log_path(root)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(rec, at=time.strftime("%Y-%m-%d %H:%M:%S")), ensure_ascii=False) + "\n")
    except OSError:
        pass


def pack(kind: str, value, length: Optional[int] = None) -> bytes:
    if kind in KINDS:
        fmt, _ = KINDS[kind]
        v = float(value) if kind in ("float", "double") else int(float(value))
        try:
            return struct.pack("<" + fmt, v)
        except struct.error:
            raise MemoryError_(t("{value} 은(는) {kind} 에 넣을 수 없는 값", value=value, kind=kind))
    if kind in TEXT_KINDS:
        raw = str(value).encode("utf-16-le" if kind == "text16" else "utf-8") + (b"\x00\x00" if kind == "text16" else b"\x00")
        if length:
            cap = length * (2 if kind == "text16" else 1)
            if len(raw) > cap:
                raise MemoryError_(t("글자가 너무 김(최대 {n}자)", n=length))
        return raw
    raise MemoryError_(t("모르는 자료형 {kind}", kind=kind))


class ProcessWriter(ProcessReader):
    """쓰기 권한으로 붙음(읽기도 됨)."""

    def __init__(self, pid: int, root: Optional[str] = None):
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        h = k.OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION | PROCESS_QUERY_LIMITED_INFORMATION,
                          False, int(pid))
        if not h:
            raise MemoryError_(t("이 프로그램은 값 바꾸기를 쓸 수 없어요(쓰기로 붙지 못함, 오류 {code})",
                                 code=ctypes.get_last_error()))
        k.CloseHandle(h)
        super().__init__(pid)                       # 읽기 쪽 준비(모듈·포인터 크기)
        self.k.CloseHandle(self.h)
        self.h = k.OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION | PROCESS_QUERY_LIMITED_INFORMATION,
                               False, int(pid))
        self.k.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                              ctypes.POINTER(ctypes.c_size_t)]
        self.root = root
        try:
            from .office_guard import processes
            self.exe = processes().get(int(pid), "")
        except Exception:
            self.exe = ""

    def write_raw(self, addr: int, data: bytes):
        got = ctypes.c_size_t(0)
        ok = self.k.WriteProcessMemory(self.h, ctypes.c_void_p(addr), data, len(data), ctypes.byref(got))
        if not ok or got.value != len(data):
            raise MemoryError_(t("주소 {addr} 에 쓰지 못함(없는 곳이거나 막혀 있음)", addr=hex(addr)))

    def write(self, spec: dict, value, log: bool = True) -> int:
        kind = spec.get("kind", "int32")
        addr = self.resolve(spec)
        self.write_raw(addr, pack(kind, value, spec.get("length")))
        if log:
            _log({"pid": self.pid, "program": self.exe, "address": hex(addr), "kind": kind, "value": value,
                  "spec": spec}, self.root)
        return addr


class Freezer:
    """여러 값을 정한 간격마다 되돌려 쓰는 '고정'. key 마다 켜고 끈다."""

    def __init__(self, writer: ProcessWriter, interval: float = 0.1):
        self.w = writer
        self.interval = max(0.01, float(interval))
        self.items: Dict[str, Tuple[dict, object]] = {}
        self.errors: Dict[str, str] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._th: Optional[threading.Thread] = None

    def set(self, key: str, spec: dict, value):
        with self._lock:
            self.items[key] = (dict(spec), value)
            self.errors.pop(key, None)
        _log({"pid": self.w.pid, "program": self.w.exe, "freeze_on": key, "value": value, "spec": spec}, self.w.root)
        self._ensure()

    def clear(self, key: str):
        with self._lock:
            if self.items.pop(key, None) is not None:
                _log({"pid": self.w.pid, "program": self.w.exe, "freeze_off": key}, self.w.root)

    def toggle(self, key: str, spec: dict, value) -> bool:
        if key in self.items:
            self.clear(key)
            return False
        self.set(key, spec, value)
        return True

    def active(self):
        return sorted(self.items)

    def _ensure(self):
        if self._th is None or not self._th.is_alive():
            self._stop.clear()
            self._th = threading.Thread(target=self._loop, name="memory-freeze", daemon=True)
            self._th.start()

    def _loop(self):
        while not self._stop.is_set():
            with self._lock:
                items = list(self.items.items())
            for key, (spec, value) in items:
                try:
                    self.w.write(spec, value, log=False)
                except MemoryError_ as e:
                    self.errors[key] = str(e)
                    with self._lock:
                        self.items.pop(key, None)        # 쓸 수 없게 되면(프로그램 꺼짐 등) 그 고정은 끔
            self._stop.wait(self.interval)

    def stop(self):
        self._stop.set()
        if self._th is not None:
            self._th.join(2)
        with self._lock:
            self.items.clear()

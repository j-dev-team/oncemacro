"""
실제 입력 백엔드.

- SendInputBackend (기본): Win32 SendInput 직접 호출. 키보드는 스캔코드로 보냄.
- PyAutoGUIBackend: 비교용.
- EmergencyStop: 엔진이 직접 듣는 비상 정지 핫키 (GUI 없이 CLI·MCP 로 돌 때도 동작).
"""
from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes
from typing import Callable, Optional

from .backends import Input, Pos
from .i18n import t

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
_BTN = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79

# 키 이름 → VK 코드
VK = {
    "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "cmd": 0x5B,
    "lctrl": 0xA2, "rctrl": 0xA3, "lshift": 0xA0, "rshift": 0xA1, "lalt": 0xA4, "ralt": 0xA5,
    "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "space": 0x20,
    "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "ins": 0x2D,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdn": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91, "printscreen": 0x2C, "pause": 0x13,
    "hangul": 0x15, "hanja": 0x19,
    "multiply": 0x6A, "add": 0x6B, "subtract": 0x6D, "decimal": 0x6E, "divide": 0x6F,
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF, "`": 0xC0,
    "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
}
for _i in range(1, 25):
    VK[f"f{_i}"] = 0x6F + _i
for _i in range(10):
    VK[f"num{_i}"] = 0x60 + _i
    VK[f"numpad{_i}"] = 0x60 + _i
    VK[str(_i)] = 0x30 + _i
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK[_c] = ord(_c.upper())

# 스캔코드에 확장 플래그가 필요한 키
_EXTENDED = {0x2D, 0x2E, 0x24, 0x23, 0x21, 0x22, 0x25, 0x26, 0x27, 0x28, 0x6F, 0x90,
             0xA3, 0xA5, 0x5B, 0x5C, 0x2C}


def vk_of(key: str) -> int:
    k = key.strip().lower()
    if k not in VK:
        raise ValueError(t("알 수 없는 키 이름: {key}", key=repr(key)))
    return VK[k]


LAST_SYNTHETIC = [0.0]      # 이 프로그램이 마지막으로 보낸 진짜 입력 시각(사람 입력과 구분하려고)


def mark_synthetic() -> None:
    import time as _time
    LAST_SYNTHETIC[0] = _time.time()


def _send(*inputs: INPUT):
    arr = (INPUT * len(inputs))(*inputs)
    n = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    mark_synthetic()
    if n != len(inputs):
        err = ctypes.get_last_error()
        raise OSError(t("SendInput 실패 (보낸 {n}/{total}, 오류 {err}) — "
                        "대상이 관리자 권한이거나 입력이 차단됨", n=n, total=len(inputs), err=err))


class SendInputBackend(Input):
    def move(self, x, y):
        vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        vw = max(1, user32.GetSystemMetrics(SM_CXVIRTUALSCREEN) - 1)
        vh = max(1, user32.GetSystemMetrics(SM_CYVIRTUALSCREEN) - 1)
        nx = int(round((x - vx) * 65535 / vw))
        ny = int(round((y - vy) * 65535 / vh))
        i = INPUT(type=INPUT_MOUSE)
        i.mi = MOUSEINPUT(nx, ny, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, 0, 0)
        _send(i)
        # 정규화 반올림으로 1px 어긋나는 것 보정
        if self.position() != (x, y):
            user32.SetCursorPos(int(x), int(y))

    def _btn(self, button, up: bool):
        flags = _BTN[button][1 if up else 0]
        i = INPUT(type=INPUT_MOUSE)
        i.mi = MOUSEINPUT(0, 0, 0, flags, 0, 0)
        _send(i)

    def down(self, button):
        self._btn(button, False)

    def up(self, button):
        self._btn(button, True)

    def _key(self, key, up: bool):
        vk = vk_of(key)
        scan = user32.MapVirtualKeyW(vk, 0)   # MAPVK_VK_TO_VSC
        flags = KEYEVENTF_KEYUP if up else 0
        if scan:                       # 게임은 스캔코드 입력을 더 잘 받음
            flags |= KEYEVENTF_SCANCODE
            vk_field = 0
        else:                          # 스캔코드가 없는 키는 VK 로
            vk_field = vk
        if vk in _EXTENDED:
            flags |= KEYEVENTF_EXTENDEDKEY
        i = INPUT(type=INPUT_KEYBOARD)
        i.ki = KEYBDINPUT(vk_field, scan, flags, 0, 0)
        _send(i)

    def key_down(self, key):
        self._key(key, False)

    def key_up(self, key):
        self._key(key, True)

    def type_text(self, text):
        _paste_text(text, self)

    def scroll(self, amount, horizontal=False):
        """휠: amount 칸(+ 위/오른쪽, - 아래/왼쪽)."""
        i = INPUT(type=INPUT_MOUSE)
        i.mi = MOUSEINPUT(0, 0, ctypes.c_ulong(int(amount) * 120 & 0xFFFFFFFF).value,
                          0x01000 if horizontal else 0x0800, 0, 0)      # MOUSEEVENTF_HWHEEL / WHEEL
        _send(i)

    def position(self) -> Pos:
        p = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(p))
        return (p.x, p.y)


class PyAutoGUIBackend(Input):
    def __init__(self):
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0
        self.pg = pyautogui

    def move(self, x, y):
        self.pg.moveTo(x, y)

    def down(self, button):
        self.pg.mouseDown(button=button)

    def up(self, button):
        self.pg.mouseUp(button=button)

    def key_down(self, key):
        self.pg.keyDown(key)

    def key_up(self, key):
        self.pg.keyUp(key)

    def type_text(self, text):
        _paste_text(text, self)

    def scroll(self, amount, horizontal=False):
        (self.pg.hscroll if horizontal else self.pg.scroll)(int(amount) * 120)

    def position(self):
        p = self.pg.position()
        return (p[0], p[1])


def make_input(backend: str) -> Input:
    return PyAutoGUIBackend() if backend == "pyautogui" else SendInputBackend()


# ---------------------------------------------------------------- 클립보드 붙여넣기

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]


def _open_clipboard():
    for _ in range(20):
        if user32.OpenClipboard(None):
            return
        time.sleep(0.02)
    raise OSError(t("클립보드를 열 수 없음"))


def get_clipboard_text() -> Optional[str]:
    _open_clipboard()
    try:
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = kernel32.GlobalLock(h)
        try:
            return ctypes.wstring_at(p)
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text: str) -> None:
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)
    h = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
    p = kernel32.GlobalLock(h)
    ctypes.memmove(p, data, size)
    kernel32.GlobalUnlock(h)
    _open_clipboard()
    try:
        user32.EmptyClipboard()
        user32.SetClipboardData(CF_UNICODETEXT, h)
    finally:
        user32.CloseClipboard()


def _paste_text(text: str, inp: Input):
    """한글 포함 문자열 입력: 클립보드에 넣고 Ctrl+V, 원래 클립보드(텍스트)는 되돌림.
    원래 클립보드가 텍스트가 아니었으면(이미지 등) 되돌리지 못함."""
    old = get_clipboard_text()
    set_clipboard_text(text)
    time.sleep(0.03)
    inp.key_down("ctrl")
    inp.key_down("v")
    time.sleep(0.03)
    inp.key_up("v")
    inp.key_up("ctrl")
    time.sleep(0.15)          # 붙여넣기가 끝나기 전에 클립보드를 바꾸면 안 됨
    if old is not None:
        set_clipboard_text(old)


# ---------------------------------------------------------------- 비상 정지

DEFAULT_EMERGENCY_HOTKEY = "ctrl+shift+f12"


def _to_pynput(hotkey: str) -> str:
    parts = []
    for p in hotkey.lower().split("+"):
        p = p.strip()
        if len(p) == 1:
            parts.append(p)
        else:
            parts.append(f"<{p}>")
    return "+".join(parts)


class EmergencyStop:
    """전역 핫키를 누르면 stop 이벤트를 세운다. with 문으로 사용."""

    def __init__(self, stop: threading.Event, hotkey: str = DEFAULT_EMERGENCY_HOTKEY,
                 on_fire: Optional[Callable[[], None]] = None):
        self.stop = stop
        self.hotkey = hotkey
        self.on_fire = on_fire
        self._listener = None

    def _fire(self):
        self.stop.set()
        if self.on_fire:
            try:
                self.on_fire()
            except Exception:
                pass

    def __enter__(self):
        # pynput GlobalHotKeys 는 이 환경에서 조합을 인식하지 못함(실측) → 눌린 키를 직접 추적
        from pynput import keyboard
        target = set()
        for part in self.hotkey.lower().split("+"):
            part = part.strip()
            if hasattr(keyboard.Key, part):
                target.add(getattr(keyboard.Key, part))
            elif len(part) == 1:
                target.add(keyboard.KeyCode.from_char(part))
            else:
                raise ValueError(t("비상 정지 핫키를 해석할 수 없음: {hotkey}", hotkey=repr(self.hotkey)))
        pressed = set()
        holder = {}

        def canon(k):
            lst = holder.get("l")
            return lst.canonical(k) if lst is not None else k

        def on_press(k):
            pressed.add(canon(k))
            if target <= pressed:
                self._fire()

        def on_release(k):
            pressed.discard(canon(k))

        lst = keyboard.Listener(on_press=on_press, on_release=on_release)
        holder["l"] = lst
        # canonical: ctrl_l→ctrl, f12→KeyCode(123) 처럼 바뀌므로 비교 대상도 같은 형태로
        target = {lst.canonical(k) for k in target}
        lst.daemon = True
        lst.start()
        lst.wait()                      # 훅이 실제로 설치될 때까지
        self._listener = lst
        return self

    def __exit__(self, *exc):
        if self._listener:
            self._listener.stop()
            self._listener = None

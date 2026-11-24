"""사람 입력만 세는 자리 비움 확인(프로그램이 보낸 클릭·키는 빼고).

    python scripts\\human_idle.py wait 180 [최대초]   → 사람 입력이 180초 없을 때까지 기다렸다 끝("조용함 N초")
    python scripts\\human_idle.py watch 결과파일       → 계속 돌며 마지막 사람 입력 시각(time.time())을 파일에 씀

자동운영이 클릭을 보내면 윈도우의 '마지막 입력 시각'이 계속 새로 바뀌어서 design\\idle.py 로는 자리 비움을 못 잰다.
저수준 훅에서 '주입된 입력' 표시(LLMHF_INJECTED / LLKHF_INJECTED)가 없는 것만 사람 입력으로 본다.
"""
import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
WM_MOUSEMOVE = 0x0200
LLKHF_INJECTED, LLMHF_INJECTED = 0x10, 0x01


class KBD(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MSE(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK

LAST = [time.time()]                 # 시작 시각을 마지막 사람 입력으로 침(안전하게)


def _kb(n, w, l):
    if n == 0 and not (ctypes.cast(l, ctypes.POINTER(KBD)).contents.flags & LLKHF_INJECTED):
        LAST[0] = time.time()
    return user32.CallNextHookEx(None, n, w, l)


def _ms(n, w, l):
    if n == 0 and not (ctypes.cast(l, ctypes.POINTER(MSE)).contents.flags & LLMHF_INJECTED):
        LAST[0] = time.time()
    return user32.CallNextHookEx(None, n, w, l)


_KB, _MS = HOOKPROC(_kb), HOOKPROC(_ms)


def _pump():
    h1 = user32.SetWindowsHookExW(WH_KEYBOARD_LL, _KB, None, 0)
    h2 = user32.SetWindowsHookExW(WH_MOUSE_LL, _MS, None, 0)
    if not h1 or not h2:
        raise SystemExit("훅을 못 걸었음")
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def human_idle() -> float:
    return time.time() - LAST[0]


if __name__ == "__main__":
    threading.Thread(target=_pump, daemon=True).start()
    mode = sys.argv[1] if len(sys.argv) > 1 else "wait"
    if mode == "watch":
        out = sys.argv[2]
        while True:
            tmp = out + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(f"{LAST[0]:.1f}")
            os.replace(tmp, out)
            time.sleep(2)
    need = float(sys.argv[2]) if len(sys.argv) > 2 else 180
    cap = float(sys.argv[3]) if len(sys.argv) > 3 else 7200
    t0 = time.time()
    while human_idle() < need and time.time() - t0 < cap:
        time.sleep(2)
    print(f"조용함 {human_idle():.0f}초" if human_idle() >= need else f"시간 초과(사람 입력 {human_idle():.0f}초 전)")

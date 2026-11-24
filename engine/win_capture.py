"""가려진 창 화면 찍기(PrintWindow)와 창 좌표 도우미. '뒤에서 실행'의 화면 쪽(11-24 win_background 에서 나눔)."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Tuple

import numpy as np

from .backends import Pos

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

HWND = wintypes.HWND
user32.IsChild.argtypes = [HWND, HWND]
user32.GetWindow.argtypes = [HWND, ctypes.c_uint]
user32.GetWindow.restype = HWND
user32.GetWindowRect.argtypes = [HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetAncestor.argtypes = [HWND, ctypes.c_uint]
user32.GetAncestor.restype = HWND
user32.ScreenToClient.argtypes = [HWND, ctypes.POINTER(wintypes.POINT)]
user32.GetClassLongW.argtypes = [HWND, ctypes.c_int]
user32.GetClassLongW.restype = wintypes.DWORD
user32.GetDC.argtypes = [HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [HWND, wintypes.HDC]
user32.PrintWindow.argtypes = [HWND, wintypes.HDC, wintypes.UINT]
user32.GetClientRect.argtypes = [HWND, ctypes.POINTER(wintypes.RECT)]
user32.ClientToScreen.argtypes = [HWND, ctypes.POINTER(wintypes.POINT)]
user32.PostMessageW.argtypes = [HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.ChildWindowFromPointEx.argtypes = [HWND, wintypes.POINT, wintypes.UINT]
user32.ChildWindowFromPointEx.restype = HWND
user32.MapWindowPoints.argtypes = [HWND, HWND, ctypes.c_void_p, wintypes.UINT]
user32.SendMessageTimeoutW.argtypes = [HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                       wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetForegroundWindow.restype = HWND
user32.IsWindow.argtypes = [HWND]
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                            ctypes.c_void_p, wintypes.UINT]

PW_CLIENTONLY, PW_RENDERFULLCONTENT = 0x1, 0x2


class BackgroundError(RuntimeError):
    pass


def client_origin(hwnd: int) -> Pos:
    p = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(p))
    return (p.x, p.y)


def client_size(hwnd: int) -> Tuple[int, int]:
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    return (r.right - r.left, r.bottom - r.top)


def capture_window(hwnd: int) -> np.ndarray:
    """창 클라이언트 영역 BGR 이미지. 다른 창에 가려져 있어도 그 창 내용이 나온다."""
    w, h = client_size(hwnd)
    if w <= 0 or h <= 0:
        return np.zeros((0, 0, 3), np.uint8)
    hdc = user32.GetDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mem, bmp)
    try:
        user32.PrintWindow(hwnd, mem, PW_CLIENTONLY | PW_RENDERFULLCONTENT)

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                        ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                        ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]
        bi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = np.empty((h, w, 4), np.uint8)
        gdi32.GetDIBits(mem, bmp, 0, h, buf.ctypes.data, ctypes.byref(bi), 0)
        return buf[:, :, :3].copy()
    finally:
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(hwnd, hdc)


def looks_blank(img: np.ndarray) -> bool:
    """PrintWindow 가 지원 안 되는 창은 전부 검정(또는 흰색)으로 나온다."""
    if img.size == 0:
        return True
    return float(img.std()) < 1.0

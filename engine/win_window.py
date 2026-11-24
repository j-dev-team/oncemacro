"""
Win32 창 백엔드: DPI 설정, 창 찾기, 창 기준 좌표, 활성화, 관리자 권한 점검.
"""
from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .backends import Pos, Window, WindowNotFound
from .i18n import t

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

HWND = wintypes.HWND
user32.GetWindowTextLengthW.argtypes = [HWND]
user32.GetWindowTextW.argtypes = [HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [HWND]
user32.IsWindow.argtypes = [HWND]
user32.IsIconic.argtypes = [HWND]
user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetClientRect.argtypes = [HWND, ctypes.POINTER(wintypes.RECT)]
user32.ClientToScreen.argtypes = [HWND, ctypes.POINTER(wintypes.POINT)]
user32.SetForegroundWindow.argtypes = [HWND]
user32.PostMessageW.argtypes = [HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
user32.GetLastActivePopup.argtypes = [HWND]
user32.GetLastActivePopup.restype = HWND
user32.IsWindowEnabled.argtypes = [HWND]
user32.GetForegroundWindow.restype = HWND
user32.GetMenu.argtypes = [HWND]
user32.GetMenu.restype = wintypes.HMENU
user32.GetSubMenu.argtypes = [wintypes.HMENU, ctypes.c_int]
user32.GetSubMenu.restype = wintypes.HMENU
user32.GetMenuItemCount.argtypes = [wintypes.HMENU]
user32.GetMenuItemID.argtypes = [wintypes.HMENU, ctypes.c_int]
user32.GetMenuItemID.restype = wintypes.UINT
user32.GetMenuState.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
user32.GetMenuState.restype = wintypes.UINT
user32.GetMenuStringW.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.LPWSTR, ctypes.c_int, wintypes.UINT]
user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
user32.GetWindow.argtypes = [HWND, ctypes.c_uint]
user32.GetWindow.restype = HWND
user32.BringWindowToTop.argtypes = [HWND]
user32.SetActiveWindow.argtypes = [HWND]
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]
advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                         wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TokenElevation = 20
GW_OWNER = 4
SW_RESTORE = 9

_dpi_done = False


def set_dpi_awareness() -> str:
    """프로세스를 Per-Monitor DPI aware 로. 좌표를 물리 픽셀로 통일한다. 한 번만 적용."""
    global _dpi_done
    if _dpi_done:
        return "already"
    _dpi_done = True
    try:
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):  # PER_MONITOR_AWARE_V2
            return "per_monitor_v2"
    except Exception:
        pass
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return "per_monitor"
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
        return "system"
    except Exception:
        return "unaware"


# ---------------------------------------------------------------- 프로세스 정보

def _process_path(pid: int) -> Optional[str]:
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return None
    finally:
        kernel32.CloseHandle(h)


def is_process_elevated(pid: int) -> Optional[bool]:
    """True/False, 확인할 수 없으면 None."""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        tok = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(tok)):
            return None
        try:
            val = wintypes.DWORD()
            ret = wintypes.DWORD()
            if not advapi32.GetTokenInformation(tok, TokenElevation, ctypes.byref(val),
                                                ctypes.sizeof(val), ctypes.byref(ret)):
                return None
            return bool(val.value)
        finally:
            kernel32.CloseHandle(tok)
    finally:
        kernel32.CloseHandle(h)


def self_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# ---------------------------------------------------------------- 창 목록

@dataclass
class WinInfo:
    hwnd: int
    title: str
    pid: int
    process: str           # exe 파일 이름 (확인 불가면 "")
    client: Tuple[int, int, int, int]   # 화면좌표 x, y, 너비, 높이
    minimized: bool
    owned: bool = False                  # 대화상자처럼 다른 창에 딸린 창

    def to_dict(self):
        return {"hwnd": self.hwnd, "title": self.title, "pid": self.pid, "process": self.process,
                "client": list(self.client), "minimized": self.minimized}


def _title(hwnd) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def client_rect(hwnd) -> Tuple[int, int, int, int]:
    r = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(r)):
        raise WindowNotFound(t("창 영역을 읽을 수 없음"))
    p = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(p))
    return (p.x, p.y, r.right - r.left, r.bottom - r.top)


def _info(hwnd) -> WinInfo:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    path = _process_path(pid.value) or ""
    try:
        rect = client_rect(hwnd)
    except WindowNotFound:
        rect = (0, 0, 0, 0)
    return WinInfo(int(hwnd), _title(hwnd), pid.value, os.path.basename(path), rect,
                   bool(user32.IsIconic(hwnd)))


_SHELL_TITLES = {"Program Manager", "Microsoft Text Input Application", "NVIDIA GeForce Overlay"}


def _cloaked(hwnd) -> bool:
    """DWM 이 숨긴 창(백그라운드 UWP 앱, 다른 가상 데스크톱 등)은 IsWindowVisible 이어도 화면에 없다."""
    val = wintypes.DWORD(0)
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute(HWND(hwnd), 14, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        return False
    return bool(val.value)


def list_windows(include_owned: bool = False) -> List[WinInfo]:
    """화면에 실제로 보이는(최소화 포함) 제목 있는 최상위 창 목록.
    include_owned=True 면 대화상자처럼 다른 창에 딸린 창도 포함."""
    out: List[WinInfo] = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and _title(hwnd) and (
                include_owned or not user32.GetWindow(hwnd, GW_OWNER)) \
                and _title(hwnd) not in _SHELL_TITLES and not _cloaked(hwnd):
            info = _info(hwnd)
            info.owned = bool(user32.GetWindow(hwnd, GW_OWNER))
            out.append(info)
        return True

    user32.EnumWindows(proc(cb), 0)
    return out


def find_window(cfg: dict) -> WinInfo:
    title = (cfg.get("title") or "").lower()
    process = (cfg.get("process") or "").lower()
    def match(ws):
        return [w for w in ws if (not title or title in w.title.lower())
                and (not process or w.process.lower() == process)]
    cands = match(list_windows())
    if not cands:                        # 대화상자처럼 다른 창에 딸린 창도 이름으로 찾을 수 있게
        cands = match(list_windows(include_owned=True))
    if not cands:
        raise WindowNotFound(t("조건에 맞는 창 없음 (title={title}, process={process})",
                               title=repr(cfg.get('title')), process=repr(cfg.get('process'))))
    # 최소화 안 된 창 우선, 그다음 큰 창
    cands.sort(key=lambda w: (w.minimized, -(w.client[2] * w.client[3])))
    return cands[0]


# ---------------------------------------------------------------- 창 백엔드

class ElevationMismatch(WindowNotFound):
    pass


def _menu_text(s: str) -> str:
    """'서식(&O)' → '서식', '글꼴(&F)...\tCtrl+F' → '글꼴'. 비교용으로 정리."""
    import re
    s = s.split("\t")[0].replace("&", "")
    s = re.sub(r"\([A-Za-z0-9]\)", "", s)
    return s.replace("...", "").replace("…", "").strip().lower()


def menu_command_id(hwnd: int, path: str) -> int:
    """창의 표준 메뉴에서 'A > B > C' 경로의 명령 번호. 없으면 WindowNotFound 계열 대신 ValueError."""
    MF_POPUP, MF_GRAYED, MF_DISABLED = 0x10, 0x1, 0x2
    menu = user32.GetMenu(hwnd)
    if not menu:
        raise ValueError(t("이 창에는 표준 메뉴가 없음(메뉴 스텝을 쓸 수 없음 — '이 스텝만 잠깐 앞에서' 클릭을 쓸 것)"))
    parts = [p for p in (x.strip() for x in path.replace("→", ">").split(">")) if p]
    if not parts:
        raise ValueError(t("메뉴 경로가 비었음(예: 서식 > 글꼴)"))
    for depth, want in enumerate(parts):
        wn = _menu_text(want)
        n = user32.GetMenuItemCount(menu)
        names, hit = [], None
        for i in range(max(0, n)):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetMenuStringW(menu, i, buf, 256, 0x400)          # MF_BYPOSITION
            name = _menu_text(buf.value)
            if name:
                names.append(buf.value.split("\t")[0].replace("&", ""))
            if name and (name == wn or (hit is None and name.startswith(wn))):
                hit = i
                if name == wn:
                    break
        if hit is None:
            raise ValueError(t("메뉴에 '{name}' 이 없음 (있는 것: {names})", name=want, names=", ".join(names)))
        state = user32.GetMenuState(menu, hit, 0x400)
        last = depth == len(parts) - 1
        if state != 0xFFFFFFFF and state & (MF_GRAYED | MF_DISABLED) and last:
            raise ValueError(t("메뉴 '{name}' 이 지금 꺼져 있음(누를 수 없는 상태)", name=want))
        sub = user32.GetSubMenu(menu, hit)
        if last:
            if sub:
                raise ValueError(t("'{name}' 은 하위 메뉴임 — 그 안의 항목까지 적을 것", name=want))
            cid = user32.GetMenuItemID(menu, hit)
            if cid in (0xFFFFFFFF, -1):
                raise ValueError(t("메뉴 '{name}' 의 명령 번호를 못 읽음", name=want))
            return cid
        if not sub:
            raise ValueError(t("'{name}' 아래에 하위 메뉴가 없음", name=want))
        menu = sub
    raise ValueError("menu")


def foreground_snapshot() -> Tuple[int, Tuple[int, int]]:
    """지금 활성 창과 진짜 커서 자리."""
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return int(user32.GetForegroundWindow() or 0), (p.x, p.y)


def activate_hwnd(hwnd: int) -> bool:
    """아무 창이나 맨 앞으로(포커스 잠금 우회는 Win32Window.activate 와 같은 방법)."""
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    if user32.GetForegroundWindow() == hwnd:
        return True
    me = kernel32.GetCurrentThreadId()
    fg = user32.GetForegroundWindow()
    tids = {user32.GetWindowThreadProcessId(fg, None) if fg else 0, user32.GetWindowThreadProcessId(hwnd, None)}
    attached = []
    try:
        for tid in tids - {0, me}:
            if user32.AttachThreadInput(me, tid, True):
                attached.append(tid)
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)
        _mark_synthetic()
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        for tid in attached:
            user32.AttachThreadInput(me, tid, False)
    for _ in range(20):
        if user32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.025)
    return False


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def _mark_synthetic() -> None:
    try:
        from .win_input import mark_synthetic
        mark_synthetic()
    except Exception:
        pass


def idle_seconds() -> float:
    """사람이 마지막으로 마우스·키보드를 쓴 뒤 지난 초. 마지막 입력이 이 프로그램이 보낸 것이면 사람 입력으로 안 침."""
    li = _LASTINPUTINFO()
    li.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(li)):
        return 999.0
    age = max(0.0, (kernel32.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000.0
    try:
        from .win_input import LAST_SYNTHETIC
        if LAST_SYNTHETIC[0] and abs((time.time() - LAST_SYNTHETIC[0]) - age) < 0.3:
            return 999.0
    except Exception:
        pass
    return age


def user_active(window_s: float = 0.25) -> bool:
    """사람이 지금 마우스·키보드를 쓰는 중인지: 짧은 시간 동안 진짜 커서가 움직였거나 키·버튼이 눌려 있으면 True.
    (GetLastInputInfo 는 화면 꺼짐 방지 프로그램·원격 접속 등이 계속 입력을 넣는 컴퓨터에서 항상 '방금 입력'이라 못 씀)"""
    p1 = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p1))
    time.sleep(window_s)
    p2 = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p2))
    if abs(p1.x - p2.x) + abs(p1.y - p2.y) > 2:
        return True
    for vk in list(range(0x01, 0x07)) + list(range(0x08, 0xFF)):
        if vk in (0x5B, 0x5C) or 0x88 <= vk <= 0x8F:
            continue
        if user32.GetAsyncKeyState(vk) & 0x8000:
            return True
    return False


def _modal_popup(hwnd: int) -> Optional[int]:
    """창이 대화상자 때문에 막혀 있으면(비활성) 그 대화상자 창. 없으면 None."""
    try:
        if user32.IsWindowEnabled(hwnd):
            return None
        p = user32.GetLastActivePopup(hwnd)
        if p and p != hwnd and user32.IsWindowVisible(p):
            return p
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, HWND, ctypes.c_ssize_t)
        def cb(h, _):
            if user32.GetWindow(h, 4) == hwnd and user32.IsWindowVisible(h) and user32.IsWindowEnabled(h):   # GW_OWNER
                found.append(h)
                return False
            return True
        user32.EnumWindows(cb, 0)
        return found[0] if found else None
    except Exception:
        return None


_HIDES: dict = {}


class Win32Window(Window):
    def __init__(self, cfg: dict):
        self.cfg = cfg
        info = find_window(cfg)
        self.hwnd = info.hwnd
        self.info = info
        self._warnings: List[str] = []
        if cfg.get("background"):
            try:
                from .win_hide import recover_stale
                recover_stale()                  # 전에 죽은 실행이 숨긴 채 남긴 창이 있으면 되돌림
            except Exception:
                pass
        target = is_process_elevated(info.pid)
        me = self_elevated()
        if target is True and not me:
            raise ElevationMismatch(
                t("'{title}'({process})가 관리자 권한으로 실행 중임. 입력이 전부 무시되므로 "
                  "매크로 프로그램도 관리자 권한으로 실행해야 함", title=info.title, process=info.process))
        if target is None:
            self._warnings.append(t("'{title}'의 권한을 확인할 수 없음(보안 프로그램 등). "
                                    "클릭이 안 먹히면 관리자 권한으로 실행해 볼 것", title=info.title))
        size = cfg.get("size")
        if size and (info.client[2], info.client[3]) != (int(size[0]), int(size[1])):
            self._warnings.append(t("창 크기가 녹화 때와 다름: 지금 {now}, 녹화 {rec} — 이미지·좌표가 어긋날 수 있음",
                                    now=f"{info.client[2]}x{info.client[3]}", rec=f"{int(size[0])}x{int(size[1])}"))

    def _ensure(self):
        if not user32.IsWindow(self.hwnd):
            info = find_window(self.cfg)       # 창이 다시 열렸으면 새로 잡는다
            self.hwnd, self.info = info.hwnd, info

    # ---- '숨겨서 실행'(11-24): 창을 안 보이게 둔 채로 그림·위치·화면 찍기까지
    # 숨긴 창은 창 객체가 아니라 창 핸들로 모아 둔다: 뒤에서 실행 입력은 다음 실행에서도 재사용돼
    # 예전 창 객체로 숨기는 일이 있어서(11-24 메모장 최소화 10/15). 값 = (숨김, 숨긴 스레드)
    def hide(self) -> None:
        """대상 창을 화면에 안 보이게(최소화돼 있으면 앞으로 안 가져오고 되살려서). 끝나면 unhide."""
        self._ensure()
        cur = _HIDES.get(self.hwnd)
        if cur is not None and cur[0].path:
            return
        from .win_hide import HiddenWindow
        h = HiddenWindow(self.hwnd)
        h.apply()
        if h.path:
            _HIDES[self.hwnd] = (h, threading.get_ident())
        elif not h.nested:
            raise WindowNotFound(t("창을 숨기지 못함"))

    def unhide(self) -> None:
        """이 창과, 이 스레드(같은 실행·하위 매크로)가 숨긴 창을 모두 원래대로."""
        me = threading.get_ident()
        for hwnd, (h, tid) in list(_HIDES.items()):
            if hwnd == self.hwnd or tid == me:
                _HIDES.pop(hwnd, None)
                try:
                    h.restore()
                except Exception:
                    pass

    def show_for_now(self) -> None:
        cur = _HIDES.get(self.hwnd)
        if cur is not None:
            cur[0].show_for_now()

    def hide_again(self) -> None:
        cur = _HIDES.get(self.hwnd)
        if cur is not None:
            cur[0].hide_again()

    def _drawable(self) -> None:
        """뒤에서 실행 중 대상 창이 최소화돼 있으면 숨겨서 실행으로 이어 감(지원하는 판에서만)."""
        if not self.cfg.get("background") or not user32.IsIconic(self.hwnd):
            return
        try:
            from .win_hide import supported
            if supported():
                self.hide()
        except Exception as e:
            raise WindowNotFound(t("대상 창이 최소화되어 있고 숨겨서 이어 가지도 못함: {error}", error=e))

    def origin(self) -> Pos:
        self._ensure()
        self._drawable()
        if user32.IsIconic(self.hwnd):
            raise WindowNotFound(t("대상 창이 최소화되어 있음"))
        x, y, _, _ = client_rect(self.hwnd)
        return (x, y)

    def element_hwnd(self) -> Optional[int]:
        self._ensure()
        return self.hwnd

    def client_size(self) -> Tuple[int, int]:
        self._ensure()
        _, _, w, h = client_rect(self.hwnd)
        return (w, h)

    def activate(self) -> bool:
        """맨 앞으로 가져온다. 실제로 맨 앞이 됐는지 돌려준다.
        Windows 는 백그라운드 프로세스가 포커스를 가져가는 걸 막으므로(foreground lock),
        현재 포커스 창의 입력 스레드에 잠깐 붙어서(AttachThreadInput) 요청한다."""
        self._ensure()
        hwnd = self.hwnd
        # 이 창이 띄운 대화상자(모달)가 떠 있으면 그 대화상자를 앞으로(키 입력이 대화상자로 가게). 2026-11-17
        popup = _modal_popup(hwnd)
        if popup:
            ok_set = {popup}                      # 막힌 본창이 앞이면 키가 안 먹으므로 대화상자가 앞이어야 함
            hwnd = popup
        else:
            ok_set = {hwnd}
        if user32.GetForegroundWindow() in ok_set:
            return True
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        fg = user32.GetForegroundWindow()
        me = kernel32.GetCurrentThreadId()
        fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        tgt_tid = user32.GetWindowThreadProcessId(hwnd, None)
        attached = []
        try:
            for tid in {fg_tid, tgt_tid} - {0, me}:
                if user32.AttachThreadInput(me, tid, True):
                    attached.append(tid)
            # Alt 를 한 번 눌렀다 떼면 포커스 잠금이 풀린다
            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x12, 0, 2, 0)
            _mark_synthetic()
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
        finally:
            for tid in attached:
                user32.AttachThreadInput(me, tid, False)
        for _ in range(20):
            if user32.GetForegroundWindow() in ok_set:
                return True
            time.sleep(0.025)
        return False

    def warnings(self) -> List[str]:
        return list(self._warnings)

    def process_window_titles(self) -> List[str]:
        """대상 프로그램(같은 프로세스)의 보이는 '다른' 창 제목들(대화상자·팝업 등). 대상 본창은 뺀다 —
        본창 제목은 문서 이름·'*'(수정됨) 표시처럼 저절로 바뀌어서 '처음 보는 창'으로 잘못 잡히므로."""
        self._ensure()
        pid, me = self.info.pid, self.hwnd
        return sorted({w.title for w in list_windows(include_owned=True) if w.pid == pid and w.title and w.hwnd != me})

    # ---- 메뉴 스텝·'이 스텝만 잠깐 앞에서'
    def menu_command(self, path: str) -> int:
        """표준 메뉴 항목을 이름으로 골라 그 명령을 창에 보낸다(창을 앞으로 안 가져옴)."""
        self._ensure()
        cid = menu_command_id(self.hwnd, path)
        user32.PostMessageW(self.hwnd, 0x0111, cid, 0)                  # WM_COMMAND
        return cid

    def focus_snapshot(self):
        return foreground_snapshot()

    def focus_restore(self, snap) -> None:
        fg, (x, y) = snap
        activate_hwnd(fg)
        user32.SetCursorPos(int(x), int(y))

    def user_active(self) -> bool:
        return user_active()

    # ---- '뒤에서 실행' 중 대상 프로그램이 사용자의 앞 창을 가져가면 되돌림(11-23)
    def _pid_of(self, h) -> int:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        return pid.value

    _POPUP_CLASSES = ("#32768", "net ui tool window", "net ui tool window layered", "combolbox",
                      "dropdown", "popupmenu")

    def _popup_open(self, pid: int) -> bool:
        """대상 프로그램에 펼침 메뉴·드롭다운이 떠 있나."""
        found = []
        proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(h, _):
            if user32.IsWindowVisible(h) and self._pid_of(h) == pid:
                buf = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(h, buf, 64)
                if buf.value.lower() in self._POPUP_CLASSES:
                    found.append(h)
                    return False
            return True
        user32.EnumWindows(proto(cb), 0)
        return bool(found)

    def user_foreground(self) -> Optional[int]:
        """지금 사람이 쓰는 앞 창(대상 프로그램 창이면 None)."""
        self._ensure()
        fg = user32.GetForegroundWindow()
        if not fg or self._pid_of(fg) == self._pid_of(self.hwnd):
            return None
        return int(fg)

    def keep_user_foreground(self, user_fg: int) -> bool:
        """대상 프로그램(뜬 대화상자 포함)이 앞 창을 가져갔으면 사람이 쓰던 창으로 돌리고, 대상 창들은 그 뒤로.
        사람이 직접 다른 창으로 옮긴 경우(앞 창이 대상 프로그램이 아님)는 건드리지 않는다. 되돌렸으면 True."""
        fg = user32.GetForegroundWindow()
        if fg == user_fg or not user32.IsWindow(user_fg):
            return False
        mine = self._pid_of(self.hwnd)
        if not fg:
            # 대상 프로그램의 대화상자가 닫히면서 앞 창이 아무것도 아닌 채로 남는 경우(메모장 '글꼴' 창 확인).
            # 사람이 창을 바꾸는 중의 잠깐 빈 틈일 수 있어 한 번 더 보고 그래도 비었을 때만 되돌림
            time.sleep(0.15)
            if user32.GetForegroundWindow():
                return False
            activate_hwnd(user_fg)
            return True
        if self._pid_of(fg) != mine:
            return False
        if self._popup_open(mine):
            return False             # 펼침 메뉴가 떠 있으면 미룸(앞 창을 돌리면 메뉴가 닫힘 — 엑셀 리본 '표시' 확인)
        activate_hwnd(user_fg)
        hs = []
        proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(h, _):
            if user32.IsWindowVisible(h) and self._pid_of(h) == mine:
                hs.append(h)
            return True
        user32.EnumWindows(proto(cb), 0)
        for h in hs:     # 사람 창 바로 뒤로(크기·자리·활성 그대로)
            user32.SetWindowPos(h, user_fg, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
        return True

    def describe(self) -> str:
        return f"{self.info.title} ({self.info.process})"

    def is_open(self) -> bool:
        try:
            self._ensure()
            if self.cfg.get("background") and user32.IsWindow(self.hwnd):
                return True                      # 뒤에서 실행은 최소화돼 있어도 됨(창 요소·숨겨서 이어 감)
            return bool(user32.IsWindow(self.hwnd)) and not user32.IsIconic(self.hwnd)
        except WindowNotFound:
            return False

    def close(self, timeout: float) -> bool:
        """WM_CLOSE 로 정상 종료 요청(강제 종료 아님) 후 창이 사라질 때까지 기다림."""
        if not user32.IsWindow(self.hwnd):
            return True
        user32.PostMessageW(self.hwnd, 0x0010, 0, 0)
        end = time.time() + timeout
        while time.time() < end:
            if not user32.IsWindow(self.hwnd):
                return True
            time.sleep(0.25)
        return False

    def current_hwnd(self) -> int:
        self._ensure()
        self._drawable()
        if user32.IsIconic(self.hwnd):
            raise WindowNotFound(t("대상 창이 최소화되어 있어 그림 찾기·위치 클릭·화면 보기를 할 수 없음(창 요소 스텝만 됨). 창을 되살리세요 — 다른 창 뒤에 둬도 됨"))
        return self.hwnd

    def input_hwnd(self) -> int:
        """뒤에서 보내는 키용. 최소화된 창은 글자 칸에 초점이 없어 키가 안 먹으므로(11-24 메모장 0/5)
        숨겨서 실행이 있는 판에서는 안 보이게 되살려서 보낸다. 없는 판은 그대로(메시지는 창에 감)."""
        self._ensure()
        try:
            self._drawable()
        except WindowNotFound:
            pass
        return self.hwnd

    def is_minimized(self) -> bool:
        self._ensure()
        return bool(user32.IsIconic(self.hwnd))

    def background_input(self):
        from .win_background import background_input_for
        return background_input_for(self.hwnd, self.input_hwnd, self.cfg.get("wrapper", True) is not False)

    def capture_source(self):
        return self.current_hwnd


def window_factory(cfg: Optional[dict]) -> Window:
    set_dpi_awareness()
    if not cfg:
        return Window()
    return Win32Window(cfg)

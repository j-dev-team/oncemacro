"""매크로가 켠 엑셀·워드·한글이 남지 않게 지키기(2026-11-18 숨은 엑셀이 남아 다음 실행이 꼬인 일 재발 방지).

- 매크로가 프로그램을 켜면 그 번호(PID)를 logs/office_started.json 에 적어 둔다.
- 다음에 오피스 단계를 쓸 때, 적어 둔 것 중 아직 살아 있는 '남은 것'을 찾는다:
  주인(그걸 켠 매크로 프로그램)이 이미 꺼졌거나, 닫으라고 한 지 1분이 지났는데도 살아 있는 것.
  · 창이 안 보이고 문서 이름도 없으면 → 창 닫기 요청(WM_CLOSE). 강제 종료는 절대 하지 않는다.
  · 문서가 열려 있거나 보이는 창이면 → 닫지 않고 알림 기록만.
- 사람이 직접 켠 엑셀·워드는 적혀 있지 않으므로 건드리지 않는다.
"""
import json
import os
import threading
import time
from typing import Dict, List, Optional

from .i18n import t

EXE = {"엑셀": "EXCEL.EXE", "워드": "WINWORD.EXE", "한글": "HWP.EXE"}
MAIN_CLASS = {"엑셀": "XLMAIN", "워드": "OpusApp", "한글": "HwpFrame"}
QUIT_GRACE = 60.0            # 닫으라고 한 뒤 이만큼 지나도 살아 있으면 '남은 것'
_lock = threading.Lock()


def _root() -> str:
    try:
        from .real import PROJECT_ROOT
        return PROJECT_ROOT
    except Exception:
        return os.getcwd()


def record_path(root: Optional[str] = None) -> str:
    return os.path.join(root or _root(), "logs", "office_started.json")


def _load(path: str) -> List[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return [r for r in data if isinstance(r, dict) and isinstance(r.get("pid"), int)]
    except (OSError, ValueError):
        return []


def _save(path: str, rows: List[dict]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ------------------------------------------------------------ 윈도우 조회(바꿔 끼울 수 있게 함수로)
def processes(names=None) -> Dict[int, str]:
    """{pid: 실행 파일 이름(대문자)}. names 를 주면 그 이름만."""
    import ctypes
    from ctypes import wintypes
    TH32CS_SNAPPROCESS = 0x2

    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]
    k = ctypes.windll.kernel32
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    out: Dict[int, str] = {}
    want = {n.upper() for n in names} if names else None
    try:
        e = PE()
        e.dwSize = ctypes.sizeof(PE)
        ok = k.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            n = e.szExeFile.upper()
            if want is None or n in want:
                out[int(e.th32ProcessID)] = n
            ok = k.Process32NextW(snap, ctypes.byref(e))
    finally:
        k.CloseHandle(snap)
    return out


def windows(pid: int) -> List[dict]:
    """그 프로그램의 맨 위 창들: [{hwnd, cls, title, visible}]"""
    import win32gui
    import win32process
    out: List[dict] = []

    def cb(h, _):
        try:
            if win32process.GetWindowThreadProcessId(h)[1] == pid:
                out.append({"hwnd": h, "cls": win32gui.GetClassName(h), "title": win32gui.GetWindowText(h),
                            "visible": bool(win32gui.IsWindowVisible(h))})
        except Exception:
            pass
        return True
    win32gui.EnumWindows(cb, None)
    return out


def post_close(hwnd: int):
    import win32con
    import win32gui
    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)


def pid_of_hwnd(hwnd: int) -> Optional[int]:
    try:
        import win32process
        return int(win32process.GetWindowThreadProcessId(int(hwnd))[1]) or None
    except Exception:
        return None


# ------------------------------------------------------------ 기록
def started(app: str, pid: Optional[int], root: Optional[str] = None):
    """매크로가 켠 프로그램을 적어 둠."""
    if not pid:
        return
    path = record_path(root)
    with _lock:
        rows = [r for r in _load(path) if r["pid"] != pid]
        rows.append({"pid": int(pid), "app": app, "owner": os.getpid(), "at": time.time(), "quit_at": None})
        _save(path, rows)


def quit_sent(pid: Optional[int], root: Optional[str] = None):
    """닫으라고 했음(Quit). 진짜 꺼졌는지는 다음 점검 때 본다."""
    if not pid:
        return
    path = record_path(root)
    with _lock:
        rows = _load(path)
        for r in rows:
            if r["pid"] == pid:
                r["quit_at"] = time.time()
        _save(path, rows)


def new_pid(app: str, before: Dict[int, str]) -> Optional[int]:
    """켜기 전 목록과 비교해 새로 생긴 그 프로그램 번호(하나일 때만)."""
    try:
        now = processes([EXE[app]])
    except Exception:
        return None
    new = [p for p in now if p not in before]
    return new[0] if len(new) == 1 else None


def has_document(app: str, wins: List[dict]) -> bool:
    """문서가 열려 있어 보이는지: 보이는 창이 있거나, 주 창 제목에 문서 이름(' - ')이 있으면."""
    if any(w["visible"] for w in wins):
        return True
    main = [w for w in wins if w["cls"] == MAIN_CLASS.get(app)]
    return any(" - " in (w["title"] or "") for w in main)


def cleanup(root: Optional[str] = None, now: Optional[float] = None, notify=None) -> List[dict]:
    """남은 것 점검. 돌려줌: [{pid, app, done: 'closed'|'kept'|'gone'}]. 강제 종료는 하지 않는다."""
    path = record_path(root)
    now = time.time() if now is None else now
    report: List[dict] = []
    with _lock:
        rows = _load(path)
        if not rows:
            return report
        try:
            alive = processes(set(EXE.values()) | {"MACROMANAGER.EXE", "PYTHON.EXE", "PYTHONW.EXE"})
        except Exception:
            return report
        keep: List[dict] = []
        for r in rows:
            pid, app = r["pid"], r.get("app", "")
            if alive.get(pid) != EXE.get(app):
                report.append({"pid": pid, "app": app, "done": "gone"})
                continue                                    # 이미 꺼짐(또는 번호가 다른 프로그램에 다시 쓰임)
            owner_alive = r.get("owner") in alive and r.get("owner") != pid
            quit_old = r.get("quit_at") is not None and now - r["quit_at"] >= QUIT_GRACE
            if owner_alive and not quit_old:
                keep.append(r)                              # 주인이 아직 쓰는 중
                continue
            try:
                wins = windows(pid)
            except Exception:
                wins = []
            main = [w for w in wins if w["cls"] == MAIN_CLASS.get(app)] or wins
            if main and not has_document(app, wins):
                for w in main:
                    try:
                        post_close(w["hwnd"])
                    except Exception:
                        pass
                r["close_at"] = now
                report.append({"pid": pid, "app": app, "done": "closed"})
                keep.append(r)                              # 진짜 꺼졌는지는 다음에 확인(꺼졌으면 gone)
            else:
                report.append({"pid": pid, "app": app, "done": "kept"})
                if not r.get("noticed"):
                    r["noticed"] = now
                    if notify:
                        try:
                            notify(app, pid)
                        except Exception:
                            pass
                keep.append(r)
        _save(path, keep)
    return report


def default_notify(app: str, pid: int, root: Optional[str] = None):
    from . import notify as nt
    nt.send(t("오피스가 남아 있음"), t("매크로가 켰던 {app}(번호 {pid})가 아직 켜져 있음. 문서가 열려 있어 닫지 않았음 — 작업 관리자에서 확인 후 직접 닫아 주세요.", app=t(app), pid=pid),
            channels=("log",), level="warn", source=t("오피스 지킴이"),
            root=root or _root())

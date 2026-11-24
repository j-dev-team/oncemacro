"""창 요소(버튼·입력칸 등)를 이름으로 찾기 — 윈도우 UI 자동화(Qt 없음).

그림 찾기와 달리 해상도·배율·테마가 바뀌어도 이름이 같으면 찾는다.
대상 모양: {"element": {"name": "확인", "type": "button", "id": "...", "match": "exact|contains", "index": 0}}
- name/id 중 하나는 있어야 함. type 은 아래 TYPES 의 이름(없으면 아무 종류).
- 찾는 범위: 매크로의 창 + 같은 프로그램의 다른 창(뜬 대화상자). 창이 없으면 맨 앞 창.
"""
from __future__ import annotations

import ctypes
import sys
import threading
from typing import Dict, List, Optional, Tuple

from .i18n import t

TYPES: Dict[str, int] = {
    "button": 50000, "calendar": 50001, "checkbox": 50002, "combo": 50003, "edit": 50004, "link": 50005,
    "image": 50006, "listitem": 50007, "list": 50008, "menu": 50009, "menubar": 50010, "menuitem": 50011,
    "progress": 50012, "radio": 50013, "scrollbar": 50014, "slider": 50015, "spinner": 50016,
    "statusbar": 50017, "tab": 50018, "tabitem": 50019, "text": 50020, "toolbar": 50021, "tooltip": 50022,
    "tree": 50023, "treeitem": 50024, "custom": 50025, "group": 50026, "thumb": 50027, "datagrid": 50028,
    "dataitem": 50029, "document": 50030, "splitbutton": 50031, "window": 50032, "pane": 50033,
    "header": 50034, "headeritem": 50035, "table": 50036, "titlebar": 50037, "separator": 50038,
}
_NAMES = {v: k for k, v in TYPES.items()}
SPEC_KEYS = {"name", "type", "id", "match", "index"}
MAX_LIST = 400

_local = threading.local()


class ElementError(RuntimeError):
    pass


def available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import comtypes.client  # noqa: F401
        return True
    except Exception:
        return False


def _ua():
    """스레드마다 COM 초기화 + UI 자동화 객체 하나."""
    ua = getattr(_local, "ua", None)
    if ua is not None:
        return ua, _local.U
    if not available():
        raise ElementError(t("창 요소 찾기 부품이 없음"))
    import comtypes
    import comtypes.client
    try:
        comtypes.CoInitializeEx(comtypes.COINIT_APARTMENTTHREADED)
    except OSError:
        pass                                    # 이미 다른 방식으로 초기화된 스레드
    try:
        from comtypes.gen import UIAutomationClient as U
    except ImportError:
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as U
    ua = comtypes.client.CreateObject(U.CUIAutomation, interface=U.IUIAutomation)
    _local.ua, _local.U = ua, U
    return ua, U


def check_spec(spec) -> List[str]:
    """대상 모양 검사. 오류 문장 목록(빈 목록 = 괜찮음)."""
    if not isinstance(spec, dict):
        return [t("element 는 객체여야 함 {{\"name\": ..}}")]
    errs = []
    extra = set(spec) - SPEC_KEYS
    if extra:
        errs.append(t("모르는 키: {keys}", keys=", ".join(sorted(extra))))
    has = False
    for k in ("name", "id"):
        if k in spec:
            if not isinstance(spec[k], str) or not spec[k].strip():
                errs.append(t("{k} 는 비어 있지 않은 글자여야 함", k=k))
            else:
                has = True
    if not has:
        errs.append(t("name(보이는 이름) 이나 id 중 하나가 필요"))
    if "type" in spec and spec["type"] not in TYPES and spec["type"] != "any":
        errs.append(t("type 은 {types} 중 하나", types=" / ".join(["button", "edit", "text", "checkbox", "menuitem", "tabitem",
                                                                 "listitem", "link", "…"])))
    if "match" in spec and spec["match"] not in ("exact", "contains"):
        errs.append(t("match 는 exact 또는 contains"))
    if "index" in spec and not (isinstance(spec["index"], int) and not isinstance(spec["index"], bool)
                                and spec["index"] >= 0):
        errs.append(t("index 는 0 이상 정수"))
    return errs


def label(spec: dict) -> str:
    s = spec.get("name") or spec.get("id") or "?"
    ty = spec.get("type")
    return f"'{s}'" + (f" {ty}" if ty and ty != "any" else "") + (f" #{spec['index']}" if spec.get("index") else "")


def _norm(s) -> str:
    return " ".join(str(s or "").split())


def _same_process_windows(hwnd: int) -> List[int]:
    """같은 프로그램의 보이는 최상위 창들(뜬 대화상자 포함), 앞에 있는 순서."""
    user32 = ctypes.windll.user32
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    out: List[int] = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    owner_min = bool(user32.IsIconic(hwnd))

    def cb(h, _):
        p = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid.value and h != hwnd and not user32.IsIconic(h):
            # 주인 창이 최소화되면 윈도우가 그 창이 띄운 대화상자도 숨김 → 그때는 숨은 대화상자도 본다(11-23)
            if user32.IsWindowVisible(h) or (owner_min and user32.GetWindow(h, 4) == hwnd):
                out.append(int(h))
        return True
    user32.EnumWindows(proto(cb), 0)
    return out


def _foreground() -> int:
    return int(ctypes.windll.user32.GetForegroundWindow() or 0)


def _rect(e) -> Tuple[int, int, int, int]:
    r = e.CurrentBoundingRectangle
    return (int(r.left), int(r.top), int(r.right - r.left), int(r.bottom - r.top))


def _matches(e, spec: dict) -> bool:
    if "id" in spec and _norm(e.CurrentAutomationId) != _norm(spec["id"]):
        return False
    if "name" in spec:
        have, want = _norm(e.CurrentName), _norm(spec["name"])
        if spec.get("match") == "contains":
            if want.lower() not in have.lower():
                return False
        elif have != want:
            return False
    return True


def _candidates(root, spec: dict):
    ua, U = _ua()
    conds = []
    ty = spec.get("type")
    if ty and ty != "any":
        conds.append(ua.CreatePropertyCondition(U.UIA_ControlTypePropertyId, TYPES[ty]))
    # 이름은 여기서 거르지 않는다: 프로그램이 앞뒤 빈칸을 붙인 이름(' 정지')도 _matches 에서 정리해 맞춘다
    if not conds:
        cond = ua.CreateTrueCondition()
    elif len(conds) == 1:
        cond = conds[0]
    else:
        cond = ua.CreateAndCondition(conds[0], conds[1])
        for c in conds[2:]:
            cond = ua.CreateAndCondition(cond, c)
    arr = root.FindAll(U.TreeScope_Descendants, cond)
    for i in range(arr.Length):
        yield arr.GetElement(i)


def find(hwnd: Optional[int], spec: dict) -> Optional[Tuple[int, int, int, int]]:
    """찾으면 화면 기준 (x, y, 너비, 높이), 없으면 None. 안 보이는(화면 밖·크기 0) 요소는 뺀다.
    hwnd 가 없으면 맨 앞 창에서 찾는다. 같은 프로그램의 대화상자도 같이 본다(대화상자가 먼저)."""
    hit = _find_element(hwnd, spec)
    return hit[1] if hit else None


def invoke(hwnd: Optional[int], spec: dict, open_: bool = False) -> bool:
    """요소를 마우스 없이 '누르기'(윈도우 UI 자동화의 누르기·고르기·켜고 끄기 기능). 되면 True.
    11-23: '뒤에서 실행'은 창에 마우스 메시지를 보내는데, 스토어 앱(계산기 등)은 이걸 자주 무시함(계산기 1/3)."""
    hit = _find_element(hwnd, spec)
    if not hit:
        return False
    e = hit[0]
    _ua_, U = _ua()
    # 고를 수 있는 항목(목록·탭·트리)은 '고르기'가 한 번 클릭과 같음 — '누르기'(Invoke)는 탐색기 목록에서 파일을 열어 버림.
    # 더블클릭(open_)은 '누르기'(열기)를 먼저.
    sel = (U.UIA_SelectionItemPatternId, U.IUIAutomationSelectionItemPattern, "Select")
    inv = (U.UIA_InvokePatternId, U.IUIAutomationInvokePattern, "Invoke")
    for pid, iface, call in ((inv, sel) if open_ else (sel, inv)) + (
                             (U.UIA_TogglePatternId, U.IUIAutomationTogglePattern, "Toggle"),
                             (U.UIA_LegacyIAccessiblePatternId, U.IUIAutomationLegacyIAccessiblePattern, "DoDefaultAction")):
        if open_ and call in ("Select", "Toggle"):
            continue
        try:
            pat = e.GetCurrentPattern(pid)
            if not pat:
                continue
            getattr(pat.QueryInterface(iface), call)()
            return True
        except Exception:
            continue
    return False


def set_value(hwnd: Optional[int], spec: dict, text: str) -> bool:
    """입력 칸에 글자를 키보드 없이 넣는다(윈도우 UI 자동화의 '값 바꾸기'). 되면 True.
    11-23: 뒤에서 실행 중 뜬 대화상자의 입력 칸은 키 신호가 다른 곳으로 가서 글자가 안 들어갔음."""
    hit = _find_element(hwnd, spec)
    if not hit:
        return False
    e = hit[0]
    try:
        if e.CurrentIsPassword:
            raise ElementError(t("비밀번호 칸에는 글자를 넣지 않음"))
    except ElementError:
        raise
    except Exception:
        pass
    # 보통 입력 칸(Edit 창)은 그 칸에 직접 글자 신호를 보낸다: 값만 바꾸면(WM_SETTEXT) 칸에는 보여도
    # 파일 저장 창 같은 대화상자는 사람이 친 글로 안 쳐서 원래 이름으로 저장했음(11-23 메모장 확인)
    try:
        nh = int(e.CurrentNativeWindowHandle or 0)
    except Exception:
        nh = 0
    if nh:
        user32 = ctypes.windll.user32
        buf = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(nh, buf, 64)
        if buf.value.lower() in ("edit", "richedit20w", "richedit50w"):
            user32.SendMessageW(nh, 0x00B1, 0, -1)                       # EM_SETSEL 전체 선택
            for ch in str(text):
                user32.SendMessageW(nh, 0x0102, ord(ch), 1)               # WM_CHAR (선택된 글은 바뀜)
            return True
    _ua_, U = _ua()
    try:
        pat = e.GetCurrentPattern(U.UIA_ValuePatternId)
        if not pat:
            return False
        vp = pat.QueryInterface(U.IUIAutomationValuePattern)
        if vp.CurrentIsReadOnly:
            return False
        vp.SetValue(str(text))
        try:                                          # 엑셀 대화상자처럼 조용히 무시하는 칸도 있음 → 다시 읽어 확인
            return _norm(vp.CurrentValue) == _norm(text)
        except Exception:
            return True
    except Exception:
        return False


def _find_element(hwnd: Optional[int], spec: dict):
    """(요소, 화면 기준 사각형) 또는 None."""
    ua, _U = _ua()
    main = int(hwnd or 0) or _foreground()
    if not main:
        return None
    want = int(spec.get("index", 0))
    seen = 0
    # 최소화된 창은 요소가 전부 '화면 밖'으로 나옴 → 그때는 화면 밖·크기 0 도 찾음(누르기·글자 넣기는 화면이 필요 없음, 11-23)
    iconic = bool(ctypes.windll.user32.IsIconic(main))
    for h in _same_process_windows(main) + [main]:
        try:
            root = ua.ElementFromHandle(h)
        except Exception:
            continue
        for e in _candidates(root, spec):
            try:
                if not _matches(e, spec) or (e.CurrentIsOffscreen and not iconic):
                    continue
                r = _rect(e)
            except Exception:
                continue
            if (r[2] <= 0 or r[3] <= 0) and not iconic:
                continue
            if seen == want:
                return e, r
            seen += 1
    return None


def list_elements(hwnd: Optional[int], filter_text: str = "", types: Optional[List[str]] = None,
                  limit: int = MAX_LIST) -> List[dict]:
    """창 안의 이름 있는 요소 목록(AI·화면에서 고르기용). 각 줄에 바로 쓸 element 대상이 붙는다."""
    ua, U = _ua()
    main = int(hwnd or 0) or _foreground()
    if not main:
        return []
    want_types = {TYPES[t] for t in (types or []) if t in TYPES}
    out: List[dict] = []
    counts: Dict[tuple, int] = {}
    ft = _norm(filter_text).lower()
    for h in _same_process_windows(main) + [main]:          # find() 와 같은 순서(대화상자 먼저) — index 가 맞게
        try:
            root = ua.ElementFromHandle(h)
            arr = root.FindAll(U.TreeScope_Descendants, ua.CreateTrueCondition())
        except Exception:
            continue
        for i in range(arr.Length):
            try:
                e = arr.GetElement(i)
                ct = int(e.CurrentControlType)
                name, aid = _norm(e.CurrentName), _norm(e.CurrentAutomationId)
                if want_types and ct not in want_types:
                    continue
                if not name or e.CurrentIsOffscreen:
                    continue
                r = _rect(e)
            except Exception:
                continue
            if r[2] <= 0 or r[3] <= 0:
                continue
            ty = _NAMES.get(ct, "any")
            key = (name, ty)
            idx = counts.get(key, 0)
            counts[key] = idx + 1
            if ft and ft not in name.lower() and ft not in ty:
                continue
            spec = {"name": name, "type": ty}
            if idx:
                spec["index"] = idx
            out.append({"name": name, "type": ty, "id": aid, "rect": list(r),
                        "enabled": bool(e.CurrentIsEnabled), "target": {"element": spec},
                        "dialog": h != main})
            if len(out) >= limit:
                return out
    return out


def at_point(x: int, y: int) -> Optional[dict]:
    """화면 (x, y) 밑의 요소 → {"name","type","rect","target"} (이름 없는 건 이름 있는 부모까지 올라감)."""
    ua, U = _ua()
    from comtypes.gen.UIAutomationClient import tagPOINT
    try:
        e = ua.ElementFromPoint(tagPOINT(int(x), int(y)))
    except Exception:
        return None
    walker = ua.ControlViewWalker
    for _ in range(6):
        if e is None:
            return None
        try:
            name = _norm(e.CurrentName)
            if name:
                ty = _NAMES.get(int(e.CurrentControlType), "any")
                return {"name": name, "type": ty, "id": _norm(e.CurrentAutomationId), "rect": list(_rect(e)),
                        "target": {"element": {"name": name, "type": ty}}}
            e = walker.GetParentElement(e)
        except Exception:
            return None
    return None


def top_window_at(x: int, y: int) -> int:
    """그 점을 덮는 맨 위 창(이 프로그램 창·숨긴 창은 뺌). 위에서 아래 순서로 본다."""
    import os
    user32 = ctypes.windll.user32
    me = os.getpid()
    found = [0]
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    class R(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]

    def cb(h, _):
        if found[0] or not user32.IsWindowVisible(h) or user32.IsIconic(h):
            return not found[0]                   # 찾았으면 그만(False 가 안 먹는 경우도 덮어쓰지 않게)
        p = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == me or user32.GetWindowLongW(h, -20) & 0x20:      # 마우스가 지나가는 창
            return True
        r = R()
        user32.GetWindowRect(h, ctypes.byref(r))
        if r.l <= x < r.r and r.t <= y < r.b:
            found[0] = int(h)
            return False
        return True
    user32.EnumWindows(proto(cb), 0)
    return found[0]


def element_at(x: int, y: int, hwnd: Optional[int] = None) -> Optional[dict]:
    """화면 (x, y) 를 덮는 이름 있는 요소 중 가장 작은 것(같은 이름이 여러 개면 index 까지 맞춤).
    hwnd 가 없으면 그 점의 최상위 창에서 찾는다. 못 찾으면 None."""
    if not hwnd:
        hwnd = top_window_at(x, y)
        if not hwnd:
            return None
    best = None
    for row in list_elements(hwnd, limit=5000):
        rx, ry, rw, rh = row["rect"]
        if rx <= x < rx + rw and ry <= y < ry + rh:
            if best is None or rw * rh < best["rect"][2] * best["rect"][3]:
                best = row
    return best

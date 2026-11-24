"""영어 화면 전수 점검 도구(시험이 별도 프로세스로 실행).

MACRO_LANG=en 으로 새 화면(gui/v3)의 창·대화상자·편집기 입력칸·메뉴·알림창을 가짜 화면으로 띄워 보고,
눈에 보이는 글(글·제목·풍선 도움말·입력 안내·메뉴·콤보·표·트리·상태줄·메시지 상자)에 한글이 있으면 모아서 출력한다.
실제 입력·실제 대화상자 없음(exec 는 막고 내용만 읽음).

    venv\\Scripts\\python.exe tests\\gui_v3\\english_scan.py        # 목록 출력
"""
from __future__ import annotations

import faulthandler
import json
import os
import re
import sys
import tempfile

os.environ["MACRO_LANG"] = os.environ.get("SCAN_LANG", "en")
os.environ["MACRO_ROOT_DIR"] = tempfile.mkdtemp(prefix="macro_en_root_")      # 모듈이 불러지기 전에 정해야 함
faulthandler.dump_traceback_later(int(os.environ.get("SCAN_DUMP", "0")) or 10**6, repeat=True)
os.environ.setdefault("MACRO_NO_GUARD", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import shiboken6  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent, QModelIndex, QSettings, Qt  # noqa: E402

QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp(prefix="macro_en_settings_"))

from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QApplication, QComboBox, QDialog,  # noqa: E402
                               QFileDialog, QGroupBox, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox,
                               QPlainTextEdit, QSpinBox, QDoubleSpinBox, QStatusBar, QTabBar, QTextEdit,
                               QToolBar, QWidget, QSystemTrayIcon)

HAN = re.compile(r"[가-힣]")
FOUND: dict = {}            # 글 -> {어디}
_scanned = set()


ALLOWED = ("한국어",)            # 언어 고르는 이름은 그 나라 말로 둔다
ALLOWED_FRAGMENT = ("언어를 바꿨습니다",)   # '한국어로 바꾸면' 고른 언어의 말로 묻는 안내(일부러)


PATH = re.compile(r"[A-Za-z]:[\\/]\S*")     # 파일 경로(폴더 이름)는 사용자가 따로 다룸


def add(text, where):
    if isinstance(text, str):
        text = PATH.sub("", text)
    if isinstance(text, str) and HAN.search(text):
        if text.strip() in ALLOWED or any(f in text for f in ALLOWED_FRAGMENT):
            return
        FOUND.setdefault(text, set()).add(where)


# ---------------------------------------------------------------- 훑기
def _model_walk(view, where):
    m = view.model()
    if m is None:
        return
    try:
        for c in range(m.columnCount()):
            for role in (Qt.DisplayRole, Qt.ToolTipRole, Qt.StatusTipRole):
                add(m.headerData(c, Qt.Horizontal, role), where + ":header")
    except Exception:
        pass
    seen = [0]

    def rec(parent):
        for r in range(m.rowCount(parent)):
            for c in range(max(1, m.columnCount(parent))):
                if seen[0] > 3000:
                    return
                seen[0] += 1
                idx = m.index(r, c, parent)
                for role in (Qt.DisplayRole, Qt.ToolTipRole, Qt.StatusTipRole):
                    add(m.data(idx, role), where + ":item")
            idx0 = m.index(r, 0, parent)
            if m.rowCount(idx0) > 0:
                rec(idx0)
    rec(QModelIndex())


def _menu_walk(menu, where, depth=0):
    add(menu.title(), where + ":menu")
    for a in menu.actions():
        add(a.text(), where + ":action")
        add(a.toolTip(), where + ":action-tip")
        add(a.statusTip(), where + ":action-tip")
        if a.menu() is not None and depth < 6:
            _menu_walk(a.menu(), where, depth + 1)


def scan_widget(root: QWidget, where: str, seen: set = None):
    """root 와 그 아래 모든 위젯(안 보이는 쪽 포함)의 글을 모은다. seen 을 주면 이미 훑은 위젯은 건너뜀."""
    if root is None:
        return
    ws = [root] + root.findChildren(QWidget)
    for w in ws:
        if seen is not None:
            ptr = shiboken6.getCppPointer(w)[0]
            if ptr in seen:
                continue
            seen.add(ptr)
        k = type(w).__name__
        loc = f"{where}/{k}"
        add(w.windowTitle() if w.isWindow() else "", loc + ":title")
        add(w.toolTip(), loc + ":tooltip")
        add(w.statusTip(), loc + ":statusTip")
        add(w.whatsThis(), loc + ":whatsThis")
        add(w.accessibleName(), loc + ":accName")
        add(w.accessibleDescription(), loc + ":accDesc")
        if isinstance(w, QLabel):
            add(w.text(), loc + ":text")
        if isinstance(w, QAbstractButton):
            add(w.text(), loc + ":text")
        if isinstance(w, QGroupBox):
            add(w.title(), loc + ":title")
        if isinstance(w, QLineEdit):
            add(w.placeholderText(), loc + ":placeholder")
            add(w.text(), loc + ":text")
        if isinstance(w, (QTextEdit, QPlainTextEdit)):
            add(w.placeholderText(), loc + ":placeholder")
            add(w.toPlainText(), loc + ":text")
        if isinstance(w, (QSpinBox, QDoubleSpinBox)):
            add(w.prefix(), loc + ":prefix")
            add(w.suffix(), loc + ":suffix")
            add(w.specialValueText(), loc + ":special")
        if isinstance(w, QComboBox):
            for i in range(w.count()):
                add(w.itemText(i), loc + ":item")
                add(w.itemData(i, Qt.ToolTipRole), loc + ":item-tip")
            add(w.placeholderText(), loc + ":placeholder")
        if isinstance(w, QTabBar):
            for i in range(w.count()):
                add(w.tabText(i), loc + ":tab")
                add(w.tabToolTip(i), loc + ":tab-tip")
        if isinstance(w, QAbstractItemView):
            _model_walk(w, loc)
        if isinstance(w, QStatusBar):
            add(w.currentMessage(), loc + ":message")
        if isinstance(w, QMenu):
            _menu_walk(w, loc)
        if isinstance(w, QToolBar):
            add(w.windowTitle(), loc + ":title")
        for a in w.actions():
            add(a.text(), loc + ":widget-action")
            add(a.toolTip(), loc + ":widget-action-tip")
            if a.menu() is not None:
                _menu_walk(a.menu(), loc)


def scan_all_toplevels(where="top"):
    for w in QApplication.topLevelWidgets():
        scan_widget(w, f"{where}:{type(w).__name__}")


# ---------------------------------------------------------------- 막기(실제 창·실제 동작 없이 내용만)
MESSAGES = []


def _box(kind):
    def f(parent=None, title="", text="", *a, **k):
        add(title, f"msgbox-{kind}:title")
        add(text, f"msgbox-{kind}:text")
        return QMessageBox.No if kind == "question" else QMessageBox.Ok
    return staticmethod(f)


def install_hooks(app):
    for kind in ("information", "warning", "critical", "question"):
        setattr(QMessageBox, kind, _box(kind))

    def get_text(parent=None, title="", label="", *a, **k):
        add(title, "inputdlg:title")
        add(label, "inputdlg:label")
        return "", False
    QInputDialog.getText = staticmethod(get_text)
    QInputDialog.getItem = staticmethod(lambda *a, **k: ("", False))
    QInputDialog.getInt = staticmethod(lambda *a, **k: (0, False))

    def fd(parent=None, caption="", *a, **k):
        add(caption, "filedlg:title")
        for x in a:
            if isinstance(x, str):
                add(x, "filedlg:filter")
        add(k.get("filter", ""), "filedlg:filter")
        return ("", "")
    QFileDialog.getOpenFileName = staticmethod(fd)
    QFileDialog.getSaveFileName = staticmethod(fd)
    QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([], ""))
    QFileDialog.getExistingDirectory = staticmethod(lambda parent=None, caption="", *a, **k: (add(caption, "filedlg:title"), "")[1])

    def dlg_exec(self, *a):
        scan_widget(self, f"dialog:{type(self).__name__}")
        return 0
    QDialog.exec = dlg_exec
    QDialog.exec_ = dlg_exec

    def msg_exec(self, *a):
        add(self.windowTitle(), "msgbox:title")
        add(self.text(), "msgbox:text")
        add(self.informativeText(), "msgbox:text")
        add(self.detailedText(), "msgbox:text")
        for b in self.buttons():
            add(b.text(), "msgbox:button")
        return QMessageBox.No
    QMessageBox.exec = msg_exec

    def menu_exec(self, *a, **k):
        _menu_walk(self, "popup-menu")
        return None
    QMenu.exec = menu_exec
    QMenu.popup = lambda self, *a, **k: _menu_walk(self, "popup-menu")

    # 윈도 알림(풍선)·밖으로 나가는 동작 막기
    QSystemTrayIcon.showMessage = lambda self, title, msg, *a, **k: (add(title, "tray:title"), add(msg, "tray:text"))
    QSystemTrayIcon.show = lambda self: None
    os.startfile = lambda *a, **k: None
    import subprocess
    subprocess.Popen = lambda *a, **k: (_ for _ in ()).throw(OSError("blocked in scan"))
    from PySide6.QtGui import QDesktopServices
    QDesktopServices.openUrl = staticmethod(lambda *a, **k: True)
    try:
        import webbrowser
        webbrowser.open = lambda *a, **k: True
    except Exception:
        pass


def rss_mb():
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                           "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                           "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    pmc = PMC()
    pmc.cb = ctypes.sizeof(pmc)
    ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return pmc.WorkingSetSize // (1024 * 1024)


def pump():
    app = QApplication.instance()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def safe(label, fn, errors):
    if os.environ.get("SCAN_VERBOSE"):
        print(">>", label, rss_mb(), file=sys.stderr, flush=True)
    try:
        return fn()
    except SystemExit:
        return None
    except Exception as e:                       # 못 띄운 곳은 따로 알린다(한글 목록과 별개)
        import traceback
        errors.append(f"{label}: {type(e).__name__}: {e}\n{traceback.format_exc(limit=4)}")
        return None


# ---------------------------------------------------------------- 가짜 환경
def make_env():
    from engine.backends import FakeClock, FakeInput, FakeVision, FakeWindow
    from engine.library import DictLibrary
    from engine import Runner

    class Env:
        def __init__(self):
            self.clock = FakeClock()
            self.vision = FakeVision(self.clock)
            self.input = FakeInput(self.clock)
            self.window = FakeWindow((0, 0))
            self.library = DictLibrary()

        def runner(self, macro, on_event=None):
            return Runner(macro, vision=self.vision, input=self.input, clock=self.clock,
                          library=self.library, window_factory=lambda cfg: self.window, on_event=on_event)
    return Env()


def macro(name, steps, **kw):
    d = {"version": 2, "name": name, "repeat": {"times": 1}, "steps": steps}
    d.update(kw)
    return d


# ---------------------------------------------------------------- 본체
def run() -> dict:
    app = QApplication.instance() or QApplication([])
    from gui.v2 import i18n
    i18n.set_language(os.environ["MACRO_LANG"])
    install_hooks(app)
    errors: list = []
    tmp = os.environ["MACRO_ROOT_DIR"]          # 진짜 로그·이미지·설정을 건드리지 않게
    os.environ["MACRO_SETTINGS_DIR"] = os.path.join(tmp, "settings")
    import engine.real as _real
    _real.PROJECT_ROOT = tmp
    for sub in ("logs", "image"):
        os.makedirs(os.path.join(tmp, sub), exist_ok=True)
    import engine.win_window as _ww
    _ww.list_windows = lambda *a, **k: []
    root = os.path.join(tmp, "macros_v2")
    os.makedirs(root)

    from gui.v2.store import MacroStore
    from gui.v3.main_window import MainWindowV2
    store = MacroStore(root)
    store.save(macro("Click", [{"type": "click", "target": {"point": [10, 20]}},
                               {"type": "if", "cond": {"var": "x", "is_set": True},
                                "then": [{"type": "delay", "seconds": 1}],
                                "else": [{"type": "key", "keys": "a"}]}], run_hotkey="f9", stop_hotkey="f9"))
    store.save(macro("Slow", [{"type": "repeat", "forever": True, "steps": [{"type": "delay", "seconds": 0.5}]}]))
    store.save(macro("Fails", [{"type": "click", "target": {"image": "nothing.png"}, "timeout": 0.1}]))
    store.save(macro("Empty", []))
    store.move_to_group("Click", "Work")
    # 스텝 종류마다 기본값 하나씩 든 매크로(스텝 줄 글을 모두 보려고). 검증을 못 넘어도 파일로 직접 쓴다
    from gui.v2.describe import STEP_ORDER as _ORDER
    from gui.v2.model import default_step as _def
    _all = macro("AllSteps", [_def(t) for t in _ORDER])
    try:
        store.save(_all)
    except Exception:
        with open(store.path("AllSteps"), "w", encoding="utf-8") as _f:
            json.dump(_all, _f, ensure_ascii=False)

    # 고침 기록·승인 대기함·AI 도우미 기록에 줄이 있게 심어 둔다(엔진이 만든 문장이 화면에 어떻게 나오는지)
    def seed():
        from engine import repairs, proposals
        rdir = os.path.join(tmp, "logs", "repairs")
        os.makedirs(rdir, exist_ok=True)
        det = {"image": "a.png", "target": "a.png", "avg": 0.81, "confidence": 0.8, "old": 0.8, "new": 0.77,
               "why": "slow", "step": "steps[0]"}
        for kind in ("proposal", "stall", "score_low", "new_window", "slow", "recapture", "confidence", "timeout"):
            for st in ("notified", "trial", "applied", "reverted", "pending", "approved", "rejected", "blocked"):
                repairs.append(rdir, "Click", kind, st, dict(det))
        proposals.add(store.root, "Click", "insert_before", "steps[0]",
                      [{"type": "delay", "seconds": 1}, {"type": "key", "keys": "a"}], "why", "ai", "summary")
        proposals.add(store.root, "Click", "insert_before", "steps[1]",
                      [{"type": "if", "cond": {"exists": {"image": "a.png"}}, "then": [{"type": "key", "keys": "b"}]}],
                      "why", "ai", "")
        adir = os.path.join(tmp, "logs", "ai_rescue")
        os.makedirs(adir, exist_ok=True)
        with open(os.path.join(adir, "log.jsonl"), "w", encoding="utf-8") as fh:
            for how in ("ai_saved", "ai_rejected", "ai_failed", "ai_error", "blocked", "rule", "rule_off", "no_consent"):
                fh.write(json.dumps({"at": "2026-01-01 09:00:00", "macro": "Click", "step": "steps[0]", "how": how,
                                     "why": "x", "steps": [{"type": "key", "keys": "a"}], "problems": ["p"]}) + "\n")
    safe("seed logs", seed, errors)

    # ------ 처음 화면(매크로 없음) 먼저: 빈 저장소
    empty_root = os.path.join(tmp, "empty_root")
    os.makedirs(empty_root)
    env = make_env()
    w0 = safe("main(empty)", lambda: MainWindowV2(store=MacroStore(empty_root), env_factory=lambda: env, hotkeys=False,
                                                  emergency_hotkey=None, write_trace=False), errors)
    if w0 is not None:
        w0.show(); pump()
        scan_all_toplevels("empty-main")
        w0.close(); w0.deleteLater(); pump()

    env = make_env()
    w = MainWindowV2(store=store, env_factory=lambda: env, hotkeys=False, emergency_hotkey=None, write_trace=False)
    w.show()
    pump()
    scan_all_toplevels("main")

    # 메뉴 줄 전체
    mb = w.menuBar()
    for a in mb.actions():
        if a.menu():
            _menu_walk(a.menu(), "menubar")

    # 매크로를 고른 상태
    safe("select", lambda: w.select_macro("Click"), errors)
    pump()
    scan_widget(w, "main-selected")

    safe("select AllSteps", lambda: (w.reload_list(), w.select_macro("AllSteps")), errors)
    pump()
    scan_widget(w, "main-allsteps")
    safe("select Click", lambda: w.select_macro("Click"), errors)

    # 우클릭 메뉴(매크로·그룹·빈 곳)
    def ctx():
        for i in range(w.macro_list.topLevelItemCount()):
            it = w.macro_list.topLevelItem(i)
            _menu_walk(w.build_context_menu(it), "ctx")
            for j in range(it.childCount()):
                _menu_walk(w.build_context_menu(it.child(j)), "ctx")
        _menu_walk(w.build_context_menu(None), "ctx")
    safe("context menus", ctx, errors)

    # 메뉴의 모든 항목 눌러 보기(창은 내용만 읽음). 종료·언어 바꾸기·실제 열기는 위에서 막음
    skip_words = ("Exit", "Quit", "한국어", "English")
    acts = []

    def collect(menu):
        for a in menu.actions():
            if a.menu():
                collect(a.menu())
            elif a.text() and not a.isSeparator():
                acts.append(a)
    for a in mb.actions():
        if a.menu():
            collect(a.menu())
    for a in acts:
        if any(s in a.text() for s in skip_words):
            continue
        if a.text().startswith("Record") or "Start recording" in a.text():
            pass
        def trig(a=a):
            if a.isEnabled():
                a.trigger()
            else:
                print("DISABLED action:", a.text(), file=sys.stderr)
        safe(f"menu action {a.text()!r}", trig, errors)
        pump()
        scan_all_toplevels("after-" + a.text()[:20])

    # 편집창(매크로 편집) — 단계마다 입력칸
    from gui.v3.editor.macro_editor import MacroEditorDialog
    from gui.v2.describe import STEP_ORDER
    ed = safe("editor", lambda: MacroEditorDialog(store, "Click", parent=w), errors)
    if ed is not None:
        scan_widget(ed, "editor")
        types = list(STEP_ORDER) if STEP_ORDER else []
        for t in types:
            def one(t=t):
                ed.add_step(t)
                pump()
                _cur = ed.tree.currentItem()
                if _cur is not None:
                    add(_cur.text(0), f"editor:{t}:steprow")
                seen = set()
                scan_widget(ed.form, f"editor:{t}", seen)
                _explore_combos(ed.form, f"editor:{t}", errors, seen, ed)
                for x in ed.validate():
                    add(x, f"editor:{t}:validate")
                ed.delete_selected()
                pump()
            safe(f"step {t}", one, errors)
            if os.environ.get("SCAN_VERBOSE"):
                print(t, rss_mb(), file=sys.stderr, flush=True)
        safe("editor validate", lambda: [add(x, "editor:validate") for x in ed.validate()], errors)
        for name in ("Click", "Slow", "Fails", "Empty"):
            pass
        scan_widget(ed, "editor-final")
        ed.close(); ed.deleteLater(); pump()

    # 단독 대화상자·패널
    _direct_dialogs(w, store, errors)
    _run_flows(w, store, errors)

    # 실제로 돌려 보기(가짜 화면): 기록·단계 상태·실패 이유
    return {"found": {k: sorted(v) for k, v in FOUND.items()}, "errors": errors}


def _explore_combos(root, where, errors, seen, ed=None):
    """입력칸 안의 종류 고르기(콤보)를 하나씩 바꿔 가며 바뀌는 입력칸도 훑는다. 같은 모양의 콤보는 한 번만."""
    if os.environ.get("SCAN_NOCOMBO"):
        return
    done = set()
    for _round in range(4):
        todo = []
        for c in root.findChildren(QComboBox):
            if c.count() < 2 or not c.isEnabled():
                continue
            sig = (type(c.parent()).__name__, tuple(c.itemText(i) for i in range(c.count())))
            if sig in done:
                continue
            done.add(sig)
            todo.append(c)
        if not todo:
            return
        for c in todo[:12]:
            try:
                orig = c.currentIndex()
                for i in range(c.count()):
                    if i == orig:
                        continue
                    c.setCurrentIndex(i)
                    QApplication.instance().processEvents()
                    scan_widget(root, where + f"/combo={c.itemText(i)}", seen)
                    if ed is not None:
                        cur = ed.tree.currentItem()
                        if cur is not None:
                            add(cur.text(0), where + "/steprow:text")
                            add(cur.toolTip(0), where + "/steprow:tip")
                c.setCurrentIndex(orig)
            except RuntimeError:
                break          # 입력칸이 새로 만들어져 지워짐
            except Exception as e:
                errors.append(f"combo {where}: {e}")


def _direct_dialogs(w, store, errors):
    from PySide6.QtWidgets import QApplication
    from gui.v3 import hotkey_dialog, macro_picker, ask_dialog, errors as v3errors, hwp_setup, ai_connect
    from gui.v3.welcome import WelcomePanel

    def show(label, make):
        d = safe(label, make, errors)
        if d is not None:
            try:
                d.show()
                pump()
                scan_widget(d, label)
                d.close()
                d.deleteLater()
            except RuntimeError:
                pass
        pump()

    show("welcome-wide", lambda: WelcomePanel(True))
    show("welcome-narrow", lambda: WelcomePanel(False))
    show("hotkey", lambda: hotkey_dialog.HotkeyDialog(w, "", "ctrl+f1"))
    show("hotkey-pair", lambda: hotkey_dialog.HotkeyPairDialog(w, "Click", "f5", "f6", others={"Slow": "f7"}))
    safe("hotkey names", lambda: [add(hotkey_dialog.display(k), "hotkey:display") for k in (
        "f5", "ctrl+shift+f12", "numpad7", "numpad_multiply", "num0", "num_plus", "esc", "space", "enter", "tab",
        "backspace", "delete", "insert", "home", "end", "pageup", "pagedown", "left", "up", "right", "down", "ctrl+a",
        "alt+f4", "win+d", "shift+tab", "num1", "num5", "numpad *", "numpad_decimal", "capslock", "printscreen",
        "scrolllock", "pause", "mouse_left", "xbutton1")], errors)
    show("picker", lambda: macro_picker.MacroPickerDialog(macro_picker.PickerSource.from_store(store), "Click"))
    for kind in ("input", "confirm", "choose", "file", "folder"):
        req = {"kind": kind, "message": "hello", "choices": ["a", "b"], "default": "a", "timeout": 30}
        show("ask-" + kind, lambda req=req: ask_dialog.AskDialog(req))
    box = safe("show_unexpected", lambda: v3errors.show_unexpected(ValueError, ValueError("x"), None, w, exec_box=False), errors)
    if box is not None:
        add(box.windowTitle(), "unexpected:title"); add(box.text(), "unexpected:text")
        add(box.informativeText(), "unexpected:text")
    for et in (ModuleNotFoundError, FileNotFoundError, KeyError):
        safe("plain_reason", lambda et=et: add(v3errors.plain_reason(et, et("x")), "plain_reason"), errors)
    safe("hwp guide", lambda: add(hwp_setup.guide_text(), "hwp:guide"), errors)
    safe("ai request text", lambda: add(ai_connect.request_text(), "ai:request"), errors)
    safe("ai entries", lambda: [add(" ".join(e), "ai:entries") for e in ai_connect.entries()], errors)

    # 도움말·정보 글
    from gui.v3 import help_text, build_info
    safe("help", lambda: (add(help_text.main_help(), "help:main"), add(help_text.background_help(), "help:bg")), errors)
    safe("about", lambda: add(build_info.text(), "about"), errors)
    from gui.v3 import env_check
    safe("env checks", lambda: [add(f"{c}", "env_check") for c in env_check.run_checks(store.root)], errors)
    safe("env summary", lambda: add(env_check.summary(env_check.run_checks(store.root)), "env_check:summary"), errors)

    # 예약 글(예약 목록 한 줄 설명)
    from gui.v2 import schedule as sch
    for it in ({"macro": "Click", "kind": "daily", "time": "09:30"}, {"macro": "Click", "kind": "interval", "minutes": 10},
               {"macro": "Click", "kind": "once", "at": "2026-01-01 09:00"}, {"macro": "Click", "every": 5}):
        safe("sched describe", lambda it=it: add(sch.describe(it), "schedule:describe"), errors)


def _run_flows(w, store, errors):
    """가짜 화면으로 실제로 돌려 본다: 성공·실패·멈춤. 실행 기록·상태 글·알림창."""
    import time
    app = QApplication.instance()

    def wait(pred, timeout=8.0):
        end = time.time() + timeout
        while time.time() < end:
            app.processEvents()
            if pred():
                return True
            time.sleep(0.01)
        return pred()
    for name in ("Click", "Fails", "Empty"):
        safe(f"run {name}", lambda name=name: w.run_macro(name), errors)
        wait(lambda: w.run_thread is None)
        pump()
        scan_widget(w, f"run:{name}")
    safe("run Slow", lambda: w.run_macro("Slow"), errors)
    for _ in range(30):
        app.processEvents(); time.sleep(0.01)
    scan_widget(w, "run:Slow-running")
    safe("stop Slow", lambda: w.stop_macro(), errors)
    wait(lambda: w.run_thread is None)
    pump()
    scan_widget(w, "run:Slow-stopped")


if __name__ == "__main__":
    res = run()
    out = sys.argv[1] if len(sys.argv) > 1 else None
    txt = json.dumps(res, ensure_ascii=False, indent=1)
    if out:
        open(out, "w", encoding="utf-8").write(txt)
    else:
        sys.stdout.buffer.write(txt.encode("utf-8"))

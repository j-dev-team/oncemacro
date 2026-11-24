"""묶음 점검(--selftest): '파이썬으로 돌릴 땐 되는데 실행 묶음에선 죽는' 문제를 잡는다.

화면 밖에서(QT_QPA_PLATFORM=offscreen 권장) 임시 자료 폴더로 주 창을 만들고,
메뉴 줄·도구 줄의 모든 항목, 우클릭 메뉴, 핫키 창, 녹화 시작/끝, 편집기를 한 번씩 연다.
대화상자는 열자마자 닫고(exec 를 바로 돌려줌), 진짜 키·마우스 입력은 보내지 않는다.
결과: 표준 출력과 logs/시험/selftest.txt 에 '됨/안 됨' 목록. 안 됨이 있으면 끝 코드 1.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import sys
import tempfile
import traceback

SKIP = {"끝내기", "종료", "Exit", "Quit"}           # 프로그램을 닫거나 다시 켜는 항목은 빼고


def _own_tmp() -> str:
    """우리 임시 자리(자료 폴더/logs/시험/임시). 이 PC는 TMPDIR 이 다른 회사 프로그램 폴더라 거기 두지 않는다."""
    try:
        from engine.real import PROJECT_ROOT
        from engine.fsnames import pick
        d = os.path.join(pick(os.path.join(PROJECT_ROOT, "logs"), "시험"), "tmp")
        os.makedirs(d, exist_ok=True)
        for x in os.listdir(d):                 # 지난번에 못 지운 것 정리(탐색기로 열려 있지 않으면)
            p = os.path.join(d, x)
            if x.startswith("selftest_") and not _shown_in_explorer(p):
                shutil.rmtree(p, ignore_errors=True)
        return d
    except OSError:
        return tempfile.gettempdir()


def _shown_in_explorer(path: str) -> bool:
    try:
        import win32com.client
        want = os.path.normcase(os.path.abspath(path))
        for w in win32com.client.Dispatch("Shell.Application").Windows():
            try:
                loc = os.path.normcase(w.Document.Folder.Self.Path)
            except Exception:
                continue
            if loc == want or loc.startswith(want + os.sep):
                return True
    except Exception:
        return False
    return False


def _neutralize(log):
    """막는 창들을 '바로 닫힘'으로. 돌려줌: 되돌리기 함수."""
    from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMenu, QMessageBox
    saved = []

    def patch(obj, name, fn):
        saved.append((obj, name, obj.__dict__.get(name, getattr(obj, name))))
        setattr(obj, name, fn)

    def dlg_exec(self, *a, **k):
        log.append(("창 열림", type(self).__name__ + ":" + (self.windowTitle() or "")))
        return 0
    patch(QDialog, "exec", dlg_exec)
    patch(QMenu, "exec", lambda self, *a, **k: None)
    for n in ("information", "warning", "critical"):
        patch(QMessageBox, n, staticmethod(lambda *a, **k: QMessageBox.Ok))
    patch(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.No))
    patch(QMessageBox, "exec", lambda self, *a, **k: 0)
    patch(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False)))
    patch(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("", False)))
    for n in ("getOpenFileName", "getSaveFileName"):
        patch(QFileDialog, n, staticmethod(lambda *a, **k: ("", "")))
    patch(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    # 탐색기·브라우저·다른 프로그램을 띄우는 길도 막는다(11-18: 점검이 임시 폴더를 탐색기로 열고, 폴더를 지운 뒤
    # '위치를 사용할 수 없습니다' 창이 사용자 화면에 뜸)
    import os as _os
    import webbrowser as _wb

    from PySide6.QtCore import QProcess
    from PySide6.QtGui import QDesktopServices

    def outside(kind):
        def f(*a, **k):
            log.append(("바깥 열기 막음", f"{kind}: {a[0] if a else ''}"))
            return True
        return f
    patch(_os, "startfile", outside("파일·폴더 열기"))
    patch(QDesktopServices, "openUrl", staticmethod(outside("주소 열기")))
    patch(QProcess, "startDetached", staticmethod(outside("프로그램 켜기")))
    patch(_wb, "open", outside("브라우저"))

    def undo():
        for obj, name, old in reversed(saved):
            setattr(obj, name, old)
    return undo


def run(app=None) -> int:
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication

    from gui.v2.store import MacroStore
    app = app or QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp(prefix="selftest_", dir=_own_tmp())
    os.environ["MACRO_SETTINGS_DIR"] = os.path.join(tmp, "settings")
    store = MacroStore(os.path.join(tmp, "macros_v2"))
    store.save({"version": 2, "name": "점검", "repeat": {"times": 1}, "run_hotkey": "ctrl+alt+shift+f11",
                "steps": [{"type": "delay", "seconds": 0}]})
    results = []                     # (항목, 됨?, 설명)
    opened: list = []
    errors: list = []
    old_hook = sys.excepthook
    sys.excepthook = lambda et, v, tb: errors.append("".join(traceback.format_exception(et, v, tb)))
    undo = _neutralize(opened)
    w = None

    def check(name, fn):
        errors.clear()
        try:
            fn()
            QCoreApplication.processEvents()
            ok = not errors
            results.append((name, ok, errors[0].strip().splitlines()[-1] if errors else ""))
        except Exception as e:
            results.append((name, False, f"{type(e).__name__}: {e}"))

    try:
        from gui.v3.main_window import MainWindowV2
        w = MainWindowV2(store=store, write_trace=False)
        w.show()
        QCoreApplication.processEvents()
        w.select_macro("점검")
        hm = w.hotkey_manager
        results.append(("전역 핫키 준비", bool(hm is not None and hm.is_available()),
                        "" if hm is not None else "핫키 관리자 없음"))

        def uia():                                   # 창 요소 찾기 부품이 묶음에 들어왔는지(이 창의 버튼을 찾아 봄)
            from engine import win_uia
            from PySide6.QtGui import QGuiApplication
            target = int(w.winId())
            if QGuiApplication.platformName() == "offscreen":
                # 화면 없는 점검에서는 이 창이 윈도우가 모르는 가짜 창이라 요소가 하나도 안 잡힘(11-23 원인).
                # 부품이 들어왔는지는 진짜 창(작업 표시줄)의 요소를 읽어 확인한다.
                target = ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None)
                if not target:
                    return
            rows = win_uia.list_elements(target)
            if not rows:
                raise RuntimeError("창 요소를 하나도 못 읽음")
        check("창 요소 찾기(버튼 이름)", uia)
        for act in w.menuBar().actions():
            menu = act.menu()
            if menu is None:
                continue
            for a in menu.actions():
                if a.isSeparator() or a.menu() is not None or not a.text() or a.text() in SKIP:
                    continue
                if any(k in a.text() for k in ("다시 켜", "끝내", "종료", "언어", "Language", "English", "한국어")):
                    continue
                label = f"메뉴 {act.text()} › {a.text()}"
                check(label, lambda a=a: (a.setEnabled(True), a.trigger()))
                w.select_macro("점검")
        for key, a in getattr(w, "tool_actions", {}).items():
            if key in ("실행", "정지"):
                continue
            check(f"도구 줄 {key}", a.trigger)
            w.select_macro("점검")
        check("우클릭 메뉴", lambda: w.build_context_menu(w.macro_list.currentItem()))
        from gui.v3.hotkey_dialog import HotkeyDialog
        check("핫키 창", lambda: HotkeyDialog(w, "점검", "f6").get_hotkey())

        def rec():
            from gui.v2.recorder import Recorder
            r = Recorder(on_stop=lambda steps: None)
            r.start()                # 훅만 걸었다가 바로 풂(입력은 안 보냄)
            r.stop()
        check("녹화 시작·끝(훅 등록)", rec)

        def editor():
            from gui.v3.editor.macro_editor import MacroEditorDialog
            d = MacroEditorDialog(store, "점검")
            for t in ("click", "if", "excel", "mail", "pdf", "list", "web", "each"):
                try:
                    d.add_step(t)
                except Exception as e:
                    raise RuntimeError(f"스텝 {t}: {e}")
            d.close()
        check("편집기·스텝 칸", editor)

        def run_once():
            w.run_macro("점검")
            import time
            end = time.time() + 5
            while w.is_running() and time.time() < end:
                QCoreApplication.processEvents()
                time.sleep(0.02)
            w._sync_run_ui()
        check("실행(빈 매크로)", run_once)
    except Exception as e:
        results.append(("주 창 만들기", False, f"{type(e).__name__}: {e}"))
    finally:
        undo()
        sys.excepthook = old_hook
        if w is not None:
            try:
                w.close()
            except Exception:
                pass
        if not _shown_in_explorer(tmp):         # 열어 둔 탐색기 창이 있으면 지우지 않음(다음에 정리)
            shutil.rmtree(tmp, ignore_errors=True)
    bad = [r for r in results if not r[1]]
    lines = [f"{'됨' if ok else '안 됨'}  {name}" + (f"  — {why}" if why else "") for name, ok, why in results]
    blocked = [x for x in opened if x[0] == "바깥 열기 막음"]
    lines.append(f"창 {len(opened) - len(blocked)}개 열어 봄 · 바깥 열기 {len(blocked)}번 막음 / 항목 {len(results)}개 중 안 됨 {len(bad)}개")
    text = "\n".join(lines)
    try:
        from engine.real import PROJECT_ROOT
        from engine.fsnames import pick
        d = pick(os.path.join(PROJECT_ROOT, "logs"), "시험")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "selftest.txt"), "w", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass
    try:                            # 창 프로그램(묶음)은 출력 창이 없거나 한글을 못 찍을 수 있음 → 파일이 기준
        if sys.stdout is not None:
            print(text)
    except Exception:
        pass
    return 1 if bad else 0

"""'파이썬으로는 되는데 실행 묶음에선 죽는' 종류 막기(11-18 핫키 창이 옛 화면 부품(PyQt5)을 불러 묶음에서 죽음).

1) 새 화면이 부르는 모든 모듈(함수 안 가져오기 포함)을 따라가며 PyQt5·옛 대화상자 묶음이 없는지 정적 검사
2) PyQt5 를 아예 못 불러오게 막은 새 프로세스에서 --selftest(모든 메뉴·단추·창 열어 보기)가 다 되는지
3) 핫키 창 값 모양, 예기치 못한 오류 창이 쉬운 말 + 접힌 자세히 + 기록 파일인지
"""
import ast
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _imports(path):
    t = ast.parse(open(path, encoding="utf-8").read())
    rel = os.path.relpath(os.path.dirname(path), ROOT).replace(os.sep, ".")
    for n in ast.walk(t):
        if isinstance(n, ast.ImportFrom):
            base = n.module or ""
            if n.level:
                pkg = rel
                for _ in range(n.level - 1):
                    pkg = pkg.rsplit(".", 1)[0]
                base = pkg + ("." + base if base else "")
            yield base, n.lineno
            for a in n.names:                         # from gui import dialogs 같은 꼴
                yield base + "." + a.name, n.lineno
        elif isinstance(n, ast.Import):
            for a in n.names:
                yield a.name, n.lineno


def _file_of(mod):
    p = os.path.join(ROOT, *mod.split("."))
    for c in (p + ".py", os.path.join(p, "__init__.py")):
        if os.path.exists(c):
            return c
    return None


def test_v3_never_reaches_pyqt5_or_old_dialogs():
    bad, seen = [], set()
    # gui/v2/i18n.py 는 PySide6 가 있으면 PySide6 를 쓰는 갈래(PyQt5 는 옛 화면 때만)라서 허용
    allowed = {os.path.join(ROOT, "gui", "v2", "i18n.py")}

    def visit(f, chain):
        if f in seen:
            return
        seen.add(f)
        for mod, ln in _imports(f):
            where = f"{os.path.relpath(f, ROOT)}:{ln}"
            if mod.startswith("PyQt5") and f not in allowed:
                bad.append(" <- ".join([where] + chain[::-1][:3]))
            if mod.startswith(("gui.dialogs", "gui.editor", "gui.ribbon", "gui.managers", "gui.main_window")):
                bad.append(f"옛 화면 부품 {mod}: " + " <- ".join([where] + chain[::-1][:3]))
            fo = _file_of(mod)
            if fo and os.path.relpath(fo, ROOT).split(os.sep)[0] in ("gui", "utils", "engine"):
                visit(fo, chain + [where])
    for base, _, files in os.walk(os.path.join(ROOT, "gui", "v3")):
        for x in files:
            if x.endswith(".py"):
                visit(os.path.join(base, x), [])
    visit(os.path.join(ROOT, "launch_v3.py"), [])
    assert not bad, "\n".join(bad)


def test_selftest_without_pyqt5(tmp_path):
    code = ("import sys; sys.modules['PyQt5'] = None; sys.argv = ['x', '--v3', '--selftest']\n"
            "import main; main.main()")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8",
               MACRO_SETTINGS_DIR=str(tmp_path / "s"))
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=200)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out[-3000:]
    assert "안 됨  " not in out and "창 " in out, out[-3000:]


def test_hotkey_dialog_values(qapp):
    from PySide6.QtCore import Qt

    from gui.v3.hotkey_dialog import HotkeyDialog, combo_from_event, display
    assert combo_from_event(Qt.Key_F1, Qt.ShiftModifier | Qt.ControlModifier, 0, "") == "ctrl+shift+f1"
    assert combo_from_event(Qt.Key_Asterisk, Qt.NoModifier, 106, "*") == "numpad_*"
    assert combo_from_event(Qt.Key_Control, Qt.ControlModifier, 17, "") is None
    assert display("numpad_+") == "넘버패드 +" and display("ctrl+f1") == "Ctrl+F1"
    d = HotkeyDialog(None, "t", "f6")
    assert d.get_hotkey() == "f6"
    d.set_hotkey("f5")
    assert "이미 씀" in d.warn.text()
    d.set_hotkey("")
    assert d.get_hotkey() == ""


def test_unexpected_error_box_is_plain(qapp, monkeypatch, tmp_path):
    from gui.v3 import errors
    monkeypatch.setattr(errors, "log_dir", lambda: str(tmp_path))
    try:
        import PyQt5_없는_부품  # noqa: F401
    except ModuleNotFoundError:
        et, v, tb = sys.exc_info()
    box = errors.show_unexpected(et, v, tb, exec_box=False)
    assert "Traceback" not in box.text() and "부품" in box.text()
    assert "Traceback" in box.detailedText()            # 자세히(접힘)에만
    assert os.listdir(tmp_path)                          # 기록 파일


def test_set_hotkeys_uses_new_dialog(qapp, tmp_path, monkeypatch):
    from gui.v2.store import MacroStore
    from gui.v3 import hotkey_dialog as hd
    from gui.v3.main_window import MainWindowV2
    store = MacroStore(str(tmp_path))
    store.save({"version": 2, "name": "a", "repeat": {"times": 1}, "steps": [{"type": "delay", "seconds": 0}]})
    w = MainWindowV2(store=store, hotkeys=False, emergency_hotkey=None, write_trace=False)
    try:
        def fake_exec(self):
            self.toggle.setChecked(True)
            self.run_row.set("ctrl+f6")
            return 1
        monkeypatch.setattr(hd.HotkeyPairDialog, "exec", fake_exec)
        w.select_macro("a")
        w.set_hotkeys()
        assert store.hotkeys()["a"] == ("ctrl+f6", "ctrl+f6")
        assert "Ctrl+F6" in w.info_label.text() and "같은 키로 켜고 끄기" in w.info_label.text()
    finally:
        w.close()


def test_hotkey_pair_dialog(qapp):
    from gui.v3.hotkey_dialog import HotkeyPairDialog
    d = HotkeyPairDialog(None, "가게", "f6", "f7", {"가게": ("f6", "f7"), "다른것": ("f8", "")})
    assert d.windowTitle() == "핫키 정하기 — 가게"
    assert d.run_row.edit.text() == "F6" and d.stop_row.edit.text() == "F7" and not d.toggle.isChecked()
    assert d.keys() == ("f6", "f7")
    d.stop_row.set("f8")
    assert "다른것" in d.stop_row.warn.text()                 # 다른 매크로와 겹침
    d.run_row.set("f5")
    assert "프로그램 단축키" in d.run_row.warn.text()          # F5 = 실행
    d.toggle.setChecked(True)                                  # 같은 키로 켜고 끄기 → 정지 키가 따라감
    assert d.keys() == ("f5", "f5") and not d.stop_row.capture.isEnabled()
    d.toggle.setChecked(False)
    d.stop_row.set("")
    assert d.keys() == ("f5", "")

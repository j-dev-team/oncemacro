"""메모리 매크로는 부가 기능: 꺼져 있으면 부품 상자·추가 메뉴·조건 종류·AI 설명서에 안 보이고, 켜면 보인다."""
import pytest

from engine import memory as mm


@pytest.fixture
def addon_root(tmp_path, monkeypatch):
    monkeypatch.setattr(mm, "_root", lambda root=None: root or str(tmp_path))
    from engine import memwatch
    monkeypatch.setattr(memwatch, "_root", lambda root=None: root or str(tmp_path))   # 진짜 자료 폴더에 안 남게
    return str(tmp_path)


def test_memory_steps_hidden_even_when_on(qapp, addon_root):
    """11-19: 메모리는 '메모리 에디터' 창만. 매크로 부품 상자·조건 종류에는 켜도 안 보임."""
    from gui.v3.editor.cond_editor import CondEditor
    from gui.v3.icons import palette
    mm.set_enabled(True)
    assert not any("memory" in types for _, types in palette())
    ce = CondEditor()
    assert ce.kind.findData("memory") < 0
    ce.set_cond({"memory": {"value": "돈", "ge": 100}})                 # 예전에 쓴 조건은 그대로 열림
    assert ce.cond() == {"memory": {"value": "돈", "ge": 100}}


def test_existing_memory_cond_opens_even_when_off(qapp, addon_root):
    from gui.v3.editor.cond_editor import CondEditor
    ce = CondEditor()
    ce.set_cond({"memory": {"value": "돈", "changed": True}})
    assert ce.cond() == {"memory": {"value": "돈", "changed": True}}


def test_ai_reference_has_no_memory_steps(addon_root):
    from engine import mcp_server
    mm.set_enabled(True)
    ref = mcp_server.macro_reference()
    assert "메모리 매크로" not in ref and "Memory macro" not in ref


def test_step_form_and_describe(qapp, addon_root):
    from gui.v2.describe import cond_text, step_text
    from gui.v3.editor.step_form import StepForm
    assert "돈" in step_text({"type": "memory", "value": "돈", "var": "x"})
    assert "바뀌면" in cond_text({"memory": {"value": "돈", "changed": True}})
    mm.save_value("에너지", {"offset": 16, "kind": "int32"})
    from gui.v2.model import StepNode
    f = StepForm()
    f.set_node(StepNode({"type": "memory", "action": "read", "value": "", "var": "값"}))
    from PySide6.QtWidgets import QComboBox
    combo = next(c for c in f.findChildren(QComboBox) if c.isEditable())
    assert combo.findText("에너지") >= 0


def test_finder_window_finds_and_saves(qapp, addon_root, monkeypatch):
    """값 찾기 창: 시험용 프로그램에서 처음 찾기 → 다시 찾기 → 이름 붙여 저장 → 고정."""
    import json
    import os
    import subprocess
    import sys
    import time
    from tests.gui_v3.conftest import wait_until
    from gui.v3 import memory_finder as mf
    here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine")
    p = subprocess.Popen([sys.executable, os.path.join(here, "memtarget.py"), "0"], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, text=True)
    a = json.loads(p.stdout.readline())
    try:
        monkeypatch.setattr(mf, "programs", lambda: [("시험", a["pid"], "python.exe")])
        d = mf.MemoryFinder(None, pid=a["pid"], exe="python.exe")
        d.kind.setCurrentIndex(d.kind.findData("int32"))
        d.start_first(100)
        assert wait_until(qapp, lambda: not d._busy, 30)
        p.stdin.write("\n")
        p.stdin.flush()
        time.sleep(0.2)
        d.mode.setCurrentIndex(d.mode.findData("eq"))
        d.next_value.setText("107")
        d.start_next()
        assert wait_until(qapp, lambda: not d._busy, 30)
        rows = [r["address"] for r in d._rows]
        assert a["int"] in rows
        d.table.selectRow(rows.index(a["int"]))
        monkeypatch.setattr(mf.QInputDialog, "getText", staticmethod(lambda *x, **k: ("체력", True)))
        d.save_selected()
        assert mm.load_values()["체력"]["process"] == "python.exe"
        d.freeze_selected()
        p.stdin.write("\n\n")
        p.stdin.flush()
        time.sleep(0.3)
        assert d.reader.value({"offset": a["int"], "kind": "int32"}) == 107
        d.done(0)
    finally:
        p.stdin.close()
        p.wait(5)


def test_saved_values_export_import_and_hotkey_toggle(qapp, addon_root, tmp_path, monkeypatch):
    """저장한 값: 프로그램별 보기·파일로 내보내기/가져오기·지우기, 값 핫키 → 고정 켜기/끄기(프로그램 전체에서)."""
    import json
    import os
    import subprocess
    import sys
    import time
    here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine")
    p = subprocess.Popen([sys.executable, os.path.join(here, "memtarget.py"), "0"], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, text=True)
    a = json.loads(p.stdout.readline())
    try:
        mm.set_enabled(True)
        mm.save_value("체력", {"process": "python.exe", "offset": a["int"], "kind": "int32", "hotkey": "ctrl+alt+f11"})
        mm.save_value("남의것", {"process": "other.exe", "offset": 1, "kind": "int32"})
        assert set(mm.values_for("python.exe")) == {"체력"}
        out = str(tmp_path / "묶음.json")
        assert mm.export_values("python.exe", out) == 1
        mm.delete_value("체력")
        assert "체력" not in mm.load_values()
        assert mm.import_values(out) == 1 and mm.load_values()["체력"]["hotkey"] == "ctrl+alt+f11"

        from gui.v2.store import MacroStore
        from gui.v3.main_window import MainWindowV2
        monkeypatch.setattr(mm, "pid_of_process", lambda name: a["pid"])
        w = MainWindowV2(store=MacroStore(str(tmp_path / "m")), hotkeys=False, emergency_hotkey=None, write_trace=False)
        try:
            regs = []

            class HM:
                def register_hotkey(self, key, cb):
                    regs.append((key, cb))
            w._register_memory_hotkeys(HM())
            assert [k for k, _ in regs] == ["ctrl+alt+f11"]
            w.toggle_memory_freeze("체력")                     # 핫키 누른 것과 같음
            p.stdin.write("\n\n")
            p.stdin.flush()
            time.sleep(0.4)
            rd = mm.ProcessReader(a["pid"])
            assert rd.value({"offset": a["int"], "kind": "int32"}) == 100     # 고정 켜짐
            w.toggle_memory_freeze("체력")                                     # 끔
            p.stdin.write("\n")
            p.stdin.flush()
            time.sleep(0.3)
            assert rd.value({"offset": a["int"], "kind": "int32"}) == 107
            rd.close()
        finally:
            for fz in getattr(w, "_mem_freezers", {}).values():
                fz.stop()
            w.close()
    finally:
        p.stdin.close()
        p.wait(5)


def test_savefile_dialog(qapp, addon_root, tmp_path, monkeypatch):
    import json
    from gui.v3 import memory_finder as mf
    p = tmp_path / "sv" / "save.json"
    p.parent.mkdir()
    p.write_text(json.dumps({"gold": 10, "hp": 3}), encoding="utf-8")
    d = mf.SaveFileDialog(None, path=str(p))
    assert d.table.rowCount() == 2
    d.search.setText("gold")
    assert d.table.rowCount() == 1
    d.table.selectRow(0)
    monkeypatch.setattr(mf.QInputDialog, "getText", staticmethod(lambda *a, **k: ("777", True)))
    d.change()
    assert json.loads(p.read_text(encoding="utf-8"))["gold"] == 777 and "원본" in d.status.text()


def test_watch_dialog_adds_rule(qapp, addon_root):
    from engine import memwatch as mw
    from gui.v3.memory_watch import MemoryWatchDialog
    mm.save_value("돈", {"offset": 1, "kind": "int32"})
    d = MemoryWatchDialog(None, lambda: ["팔기"])
    d.name.setCurrentText("돈")
    d.op.setCurrentIndex(d.op.findData("ge"))
    d.val.setText("100000")
    d.macro.setCurrentIndex(d.macro.findData("팔기"))
    d.add_rule()
    assert mw.load_rules() == [{"name": "돈", "every": 5.0, "on": True, "when": {"op": "ge", "value": 100000},
                                "do": {"macro": "팔기", "notify": True}}]
    assert d.table.rowCount() == 1 and "팔기" in d.table.item(0, 2).text()
    d.table.selectRow(0)
    d.toggle_rule()
    assert mw.load_rules()[0]["on"] is False
    d.done(0)


def test_guard_dialog_saves_setting(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QCheckBox, QDialog
    from engine import guard
    from gui.v2.store import MacroStore
    from gui.v3.main_window import MainWindowV2
    monkeypatch.setattr(guard, "_root", lambda root=None: root or str(tmp_path))
    store = MacroStore(str(tmp_path / "m"))
    store.save({"version": 2, "name": "팜", "repeat": {"times": 1}, "steps": [{"type": "delay", "seconds": 0}]})
    w = MainWindowV2(store=store, hotkeys=False, emergency_hotkey=None, write_trace=False)
    try:
        w.select_macro("팜")

        def fake_exec(self):
            self.findChild(QCheckBox).setChecked(True)
            return 1
        monkeypatch.setattr(QDialog, "exec", fake_exec)
        w.show_guard()
        assert guard.load_settings()["팜"]["on"] is True
    finally:
        w.close()


def test_finder_by_clicking_buttons(qapp, addon_root, monkeypatch):
    """값 찾기 창을 단추로 끝까지: 처음 찾기 → 다시 찾기 → 저장 → 값 바꾸기 → 고정 → 목표 맞추기(결과 = 다른 저장 값)."""
    import json
    import os
    import subprocess
    import sys
    import time
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from tests.gui_v3.conftest import wait_until
    from gui.v3 import memory_finder as mf
    here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine")
    p = subprocess.Popen([sys.executable, os.path.join(here, "memtarget.py"), "0"], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, text=True)
    a = json.loads(p.stdout.readline())
    try:
        monkeypatch.setattr(mf, "programs", lambda: [("시험", a["pid"], "python.exe")])
        answers = []
        monkeypatch.setattr(mf.QInputDialog, "getText", staticmethod(lambda *x, **k: (answers.pop(0), True)))
        monkeypatch.setattr(mf.QInputDialog, "getItem", staticmethod(lambda *x, **k: ("결과", True)))
        d = mf.MemoryFinder(None, pid=a["pid"], exe="python.exe")
        d.kind.setCurrentIndex(d.kind.findData("int32"))
        QTest.keyClicks(d.value, "100")
        QTest.mouseClick(d.first_btn, Qt.LeftButton)
        assert wait_until(qapp, lambda: not d._busy and d.next_btn.isEnabled(), 30)
        p.stdin.write("\n")
        p.stdin.flush()
        time.sleep(0.2)
        d.mode.setCurrentIndex(d.mode.findData("eq"))
        QTest.keyClicks(d.next_value, "107")
        QTest.mouseClick(d.next_btn, Qt.LeftButton)
        assert wait_until(qapp, lambda: not d._busy, 30)
        rows = [r["address"] for r in d._rows]
        d.table.selectRow(rows.index(a["int"]))
        answers[:] = ["점수"]
        QTest.mouseClick(d.save_btn, Qt.LeftButton)
        assert mm.load_values()["점수"]["process"] == "python.exe"
        answers[:] = ["5000"]
        QTest.mouseClick(d.set_btn, Qt.LeftButton)
        assert d.reader.value({"offset": a["int"], "kind": "int32"}) == 5000
        QTest.mouseClick(d.freeze_btn, Qt.LeftButton)
        p.stdin.write("\n\n")
        p.stdin.flush()
        time.sleep(0.3)
        assert d.reader.value({"offset": a["int"], "kind": "int32"}) == 5000          # 고정
        QTest.mouseClick(d.freeze_btn, Qt.LeftButton)                                   # 고정 끔
        # 결과 값: 같은 칸을 '결과'로도 저장(가짜로 결과 = 점수 // 100)해 목표 맞추기
        mm.save_value("결과", {"process": "python.exe", "offset": a["int"], "kind": "int32"})
        d.fill_saved()
        d.saved.selectRow(d._saved.index("점수"))
        monkeypatch.setattr(d, "read_screen_number", lambda: None)
        answers[:] = ["4200", "100000"]
        d.saved_goal()
        assert wait_until(qapp, lambda: not d._busy, 30)
        assert d.reader.value({"offset": a["int"], "kind": "int32"}) == 4200
        d.done(0)
    finally:
        p.stdin.close()
        p.wait(5)


def test_refind_saved_value_after_restart(qapp, addon_root, monkeypatch):
    """게임을 다시 켠 것처럼: 저장 값(옛 주소)을 '다시 찾기' → 하나로 좁혀지면 새 자리로 저장(핫키는 그대로)."""
    import json
    import os
    import subprocess
    import sys
    from tests.gui_v3.conftest import wait_until
    from gui.v3 import memory_finder as mf
    here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine")
    p = subprocess.Popen([sys.executable, os.path.join(here, "memtarget.py"), "0"], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, text=True)
    a = json.loads(p.stdout.readline())
    try:
        mm.save_value("실수값", {"process": "python.exe", "offset": "0x10", "kind": "double", "hotkey": "f7"})
        monkeypatch.setattr(mf, "programs", lambda: [("시험", a["pid"], "python.exe")])
        monkeypatch.setattr(mf.QInputDialog, "getText", staticmethod(lambda *x, **k: ("3.5", True)))
        d = mf.MemoryFinder(None, pid=a["pid"], exe="python.exe")
        d.saved.selectRow(d._saved.index("실수값"))
        d.saved_refind()
        assert wait_until(qapp, lambda: not d._busy, 60)
        rows = [r["address"] for r in d._rows]
        if a["double"] in rows and len(rows) > 1:          # 후보가 여럿이면 고른 줄로
            d.table.selectRow(rows.index(a["double"]))
            d.saved_replace_with_selected()
        sp = mm.load_values()["실수값"]
        assert int(sp["offset"], 16) == a["double"] and sp["hotkey"] == "f7" and sp["kind"] == "double"
        d.done(0)
    finally:
        p.stdin.close()
        p.wait(5)


def test_editor_first_look_is_simple(qapp, addon_root, monkeypatch):
    """처음 보는 사람용: 빈 표 대신 세 걸음 안내, 도우미는 '더 보기'로 접힘, 못 누르는 단추는 숨김,
    후보가 수천 개면 표는 200개만·글로 요약."""
    import numpy as np
    from gui.v3 import memory_finder as mf
    monkeypatch.setattr(mf, "programs", lambda: [("시험  (a.exe)", 1, "a.exe")])
    d = mf.MemoryFinder(None)
    d.show()
    qapp.processEvents()
    assert d.table_stack.currentWidget() is d.empty_hint and "처음 찾기" in d.empty_hint.text()
    assert d.savefile_btn.isVisible() and not d.more_box.isVisible()
    d.more_btn.setChecked(True)
    qapp.processEvents()
    assert d.ocr_btn.isVisible() and d.renpy_btn.isVisible()
    assert not d.ocr_read_btn.isVisible() and not d.auto_btn.isVisible()   # 숫자 칸 고르기 전엔 숨김

    class Big:
        kinds = ["int32"]
        cands = {"int32": (np.arange(5000, dtype=np.uint64) * 4 + 0x10000, np.full(5000, 7, dtype=np.int32))}
        count = lambda self: 5000                                          # noqa: E731
        guess_kind = lambda self: "int32"                                  # noqa: E731
    from engine.memscan import Scan
    Big.results = Scan.results                                             # 진짜 꺼내기 코드(앞 200개만 자름)
    d.scan = Big()
    d._on_scan_done(5000, None)
    qapp.processEvents()
    assert d.table.rowCount() == 200 and d.table_stack.currentWidget() is d.table
    assert "5,000" in d.count.text() and "200" in d.count.text()
    d.close()


def test_value_text_parsing_and_empty_first(qapp, addon_root, monkeypatch):
    """'2.1k'·'2000~2200' 범위, 빈칸으로 '처음 찾기'를 누르면 몰래 '모르는 값'으로 가지 않고 알려 줌."""
    from gui.v3 import memory_finder as mf
    assert mf._parse_value("2.1k") == (2050.0, 2150.0)
    assert mf._parse_value("2000~2200") == (2000.0, 2200.0)
    assert mf._parse_value("1,101") == 1101 and mf._parse_value("") is None
    monkeypatch.setattr(mf, "programs", lambda: [("시험  (a.exe)", 1, "a.exe")])
    d = mf.MemoryFinder(None)
    started, told = [], []
    monkeypatch.setattr(d, "start_first", lambda v: started.append(v))
    monkeypatch.setattr(mf.QMessageBox, "information", lambda *a, **k: told.append(a[2]))
    d.first_clicked()
    assert not started and "모르는 값" in told[-1]
    d.value.setText("abc")
    d.first_clicked()
    assert not started and "숫자" in told[-1]
    d.value.setText("2.1k")
    d.first_clicked()
    assert started == [(2050.0, 2150.0)]
    d.close()


def test_program_list_skips_itself(monkeypatch):
    import os
    from gui.v3 import memory_finder as mf
    from engine import win_window

    class W:
        def __init__(self, pid, title, proc):
            self.pid, self.title, self.process = pid, title, proc
    monkeypatch.setattr(win_window, "list_windows",
                        lambda: [W(os.getpid(), "매크로 관리자", "MacroManager.exe"), W(5, "게임", "Game.exe")])
    assert [p[2] for p in mf.programs()] == ["Game.exe"]

"""v2 편집기: 안 고치고 저장하면 그대로, 고치면 반영, 트리 편집 동작."""
import glob
import json
import os
import shutil

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt

from gui.v3.editor.macro_editor import MacroEditorDialog, error_step_path, _CLIPBOARD
from gui.v2.model import StepNode
from gui.v2.store import MacroStore

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "macros_v2")
NAMES = sorted(os.path.basename(f)[:-5] for f in glob.glob(os.path.join(ROOT, "*.json"))
               if not os.path.basename(f).startswith("_"))


@pytest.fixture
def copy_store(tmp_path):
    for f in glob.glob(os.path.join(ROOT, "*.json")):
        shutil.copy(f, tmp_path)
    return MacroStore(str(tmp_path))


@pytest.mark.parametrize("name", NAMES)
def test_open_and_save_unchanged_is_identical(qapp, copy_store, name):
    before = open(copy_store.path(name), encoding="utf-8").read()
    dlg = MacroEditorDialog(copy_store, name)
    # 모든 스텝을 한 번씩 골라 입력칸을 만들어 본다(만들기만 해도 값이 바뀌면 안 됨)
    # 시험에는 이벤트 루프가 없어 버린 입력칸(deleteLater)이 안 지워지고 쌓인다(PySide6).
    # 스텝 1600개짜리 하나에 2.6GB → 전체 시험이 15GB 까지 커져 컴퓨터가 꺼졌다(2026-11-17). 그래서 매번 비운다.
    # 스텝 1600개를 다 고르면 매크로 하나에 2분이 넘어, 종류마다 앞의 3개씩만 고른다(입력칸은 종류별로 같다).
    seen = {}

    def visit(it):
        d = it.data(0, Qt.UserRole)
        kind = d[1].type if isinstance(d, tuple) and d and d[0] == "step" else None
        if kind is not None and seen.get(kind, 0) < 3:
            seen[kind] = seen.get(kind, 0) + 1
            dlg.tree.setCurrentItem(it)
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        for i in range(it.childCount()):
            visit(it.child(i))
    for i in range(dlg.tree.topLevelItemCount()):
        visit(dlg.tree.topLevelItem(i))
    assert dlg.validate() == []
    dlg.save()
    assert dlg.saved_name == name
    after_obj = json.load(open(copy_store.path(name), encoding="utf-8"))
    assert after_obj == json.loads(before)
    assert list(after_obj) == list(json.loads(before))
    dlg.close()
    dlg.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _new(store, name="m", steps=None, **kw):
    m = {"version": 2, "name": name, "repeat": {"times": 1}, "steps": steps or []}
    m.update(kw)
    store.save(m)
    return name


@pytest.fixture
def store(tmp_path):
    return MacroStore(str(tmp_path))


def _select_node(dlg, node):
    dlg.rebuild_tree(node)


def test_add_edit_and_save(qapp, store):
    _new(store)
    dlg = MacroEditorDialog(store, "m")
    dlg.add_step("click")
    node = dlg.model.steps[0]
    # 입력칸으로 바꾼 것처럼 직접 고치고 저장
    node.data["target"] = {"image": "a/b.png", "region": [1, 2, 3, 4]}
    node.data["on_fail"] = "skip"
    dlg.add_step("delay")
    dlg.win_combo.setCurrentText("메모장")
    dlg.rep_mode.setCurrentIndex(1)
    dlg.save()
    m = store.load("m")
    assert m["window"] == {"title": "메모장"} and m["repeat"] == {"forever": True}
    assert [s["type"] for s in m["steps"]] == ["click", "delay"]
    assert m["steps"][0]["on_fail"] == "skip"


def test_background_checkbox_sets_and_clears_window_flag(qapp, store):
    _new(store)
    dlg = MacroEditorDialog(store, "m")
    assert not dlg.bg_check.isEnabled()              # 창이 없으면 못 켬
    dlg.win_combo.setCurrentText("메모장")
    assert dlg.bg_check.isEnabled()
    dlg.bg_check.setChecked(True)
    dlg.save()
    assert store.load("m")["window"] == {"title": "메모장", "background": True}
    dlg = MacroEditorDialog(store, "m")
    assert dlg.bg_check.isChecked()
    dlg.bg_check.setChecked(False)
    dlg.save()
    assert store.load("m")["window"] == {"title": "메모장"}


def test_invalid_blocks_save_and_marks_step(qapp, store, monkeypatch):
    _new(store)
    dlg = MacroEditorDialog(store, "m")
    dlg.add_step("click")
    dlg.model.steps[0].data["target"] = {"kind": "oops"}
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)    # '이대로 저장할까요?' → 아니
    errs = dlg.validate()
    assert errs and error_step_path(errs[0]) == "steps[0]"
    dlg.save()
    assert dlg.saved_name is None
    assert store.load("m")["steps"] == []
    it = dlg.tree.topLevelItem(0)
    assert it.foreground(0).color().name() == "#c62828"


def test_tree_ops_inside_wrap_unwrap_move_copy(qapp, store):
    _new(store, steps=[{"type": "delay", "seconds": 1}, {"type": "key", "keys": "a"}])
    dlg = MacroEditorDialog(store, "m")
    a, b = dlg.model.steps
    _select_node(dlg, a)
    dlg.wrap_selected("repeat")
    rep = dlg.model.steps[0]
    assert rep.type == "repeat" and rep.children("steps") == [a]
    _select_node(dlg, rep)
    dlg.add_inside("key")
    assert [n.type for n in rep.children("steps")] == ["delay", "key"]
    _select_node(dlg, a)
    dlg.unwrap_selected()
    assert [n.type for n in dlg.model.steps] == ["repeat", "delay", "key"]
    _select_node(dlg, b)
    dlg.move_selected(-1)
    assert dlg.model.steps[1] is b
    dlg.copy_selected()
    dlg.paste()
    assert [n.type for n in dlg.model.steps] == ["repeat", "key", "key", "delay"]
    assert dlg.validate() == []


def test_if_branches_and_type_change_keeps_children(qapp, store, monkeypatch):
    _new(store, steps=[{"type": "if", "cond": {"var": "a", "eq": 1}, "then": [{"type": "delay", "seconds": 1}]}])
    dlg = MacroEditorDialog(store, "m")
    node = dlg.model.steps[0]
    dlg.rebuild_tree((node, "else"))
    dlg.add_step("key")                  # '아니면' 가지를 고른 상태 → 그 안에 추가
    assert [n.type for n in node.children("else")] == ["key"]
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    dlg.rebuild_tree(node)
    dlg._change_type("repeat")
    assert node.type == "repeat" and [n.type for n in node.children("steps")] == ["delay"]
    assert "times" in node.data and dlg.validate() == []


def test_rename_in_editor_updates_callers(qapp, store):
    _new(store, "하위")
    _new(store, "상위", steps=[{"type": "call", "macro": "하위"}])
    dlg = MacroEditorDialog(store, "하위")
    dlg.name_edit.setText("하위새이름")
    dlg.save()
    assert dlg.saved_name == "하위새이름" and dlg.updated_callers == ["상위"]
    assert store.load("상위")["steps"][0]["macro"] == "하위새이름"


def test_error_path_parse():
    assert error_step_path("steps[1].then[0].target.region: x") == "steps[1].then[0]"
    assert error_step_path("steps[0]: 알 수 없는 스텝") == "steps[0]"
    assert error_step_path("steps[2].steps[0].steps[3].cond: x") == "steps[2].steps[0].steps[3]"
    assert error_step_path("name: 비어 있음") is None


def test_concealed_keeps_modal_dialog_running(qapp):
    """hide() 는 exec_ 중인 대화상자를 닫아 버린다 → Concealed 로 숨겨야 대화상자가 살아 있다."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog
    from gui.v3.editor.screen_picker import Concealed
    d = QDialog()
    seen = {}

    def during():
        with Concealed([d]):
            seen["visible_inside"] = d.isVisible()
        seen["visible_after"] = d.isVisible()
        d.accept()
    QTimer.singleShot(50, during)
    assert d.exec() == QDialog.Accepted          # hide() 였다면 Rejected 로 먼저 끝남
    assert seen == {"visible_inside": True, "visible_after": True}

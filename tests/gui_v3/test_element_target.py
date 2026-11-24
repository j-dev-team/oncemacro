"""대상 편집기의 '버튼 이름(창 요소)' — 실제 화면 없이."""
from PySide6.QtWidgets import QMessageBox

from gui.v3.editor.target_editor import TargetEditor


def test_element_roundtrip_keeps_unknown_keys(qapp):
    te = TargetEditor(None)
    t = {"element": {"name": "확인", "type": "button", "index": 1, "id": "btnOk"}, "offset": [2, 0]}
    te.set_target(t)
    assert te.kind.currentData() == "element"
    assert te.target() == t
    te.el_contains.setChecked(True)
    te.el_type.setCurrentIndex(te.el_type.findData(""))
    assert te.target() == {"element": {"name": "확인", "index": 1, "id": "btnOk", "match": "contains"},
                           "offset": [2, 0]}


def test_pick_element_from_unset(qapp):
    class Tools:
        def pick_element(self):
            return {"name": "저장", "type": "button", "target": {"element": {"name": "저장", "type": "button"}}}
    te = TargetEditor(Tools())
    te.set_target(None)
    got = []
    te.changed.connect(lambda: got.append(te.target()))
    te._pick_element_from_unset()
    assert te.target() == {"element": {"name": "저장", "type": "button"}} and got


def test_pick_element_nothing_found_tells_user(qapp, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))

    class Tools:
        def pick_element(self):
            return {}
    te = TargetEditor(Tools())
    te.set_target(None)
    te._pick_element_from_unset()
    assert te.target() is None and shown and "그림으로 찾기" in shown[0]


def test_unknown_element_type_is_kept(qapp):
    te = TargetEditor(None)
    te.set_target({"element": {"name": "a", "type": "splitbutton"}})
    assert te.target() == {"element": {"name": "a", "type": "splitbutton"}}

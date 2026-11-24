"""처음 쓰는 사람 걸음: 첫 화면 안내·예시 넣기·빈 대상 기본값·쉬운 오류 말."""
import json
import os

import pytest
from PySide6.QtWidgets import QMessageBox

from engine.model import validate_macro
from gui.v2.store import MacroStore
from gui.v3 import examples as ex
from gui.v3.editor.friendly import friendly, step_number
from gui.v3.editor.macro_editor import MacroEditorDialog, new_step_data
from gui.v3.editor.target_editor import TargetEditor
from gui.v3.main_window import MainWindowV2


@pytest.fixture
def store(tmp_path):
    return MacroStore(str(tmp_path / "macros_v2"))


@pytest.fixture
def quiet(monkeypatch):
    shown = []
    for n in ("information", "warning", "question"):
        monkeypatch.setattr(QMessageBox, n, staticmethod(lambda *a, _n=n, **k: shown.append((_n, a[2] if len(a) > 2 else ""))
                                                          or QMessageBox.Yes))
    return shown


# ---------------------------------------------------------------- 빈 대상 기본값
@pytest.mark.parametrize("t,keys", [("click", ["target"]), ("move", ["target"]), ("drag", ["from", "to"])])
def test_new_pointer_steps_have_no_default_point(t, keys):
    d = new_step_data(t)
    assert all(k not in d for k in keys)
    errs = validate_macro({"version": 2, "name": "a", "steps": [d]})
    assert errs, "대상이 비면 엔진 검사가 막아야 함(저장·시험·실행 모두)"


def test_editor_new_click_saves_as_draft_but_cannot_run(qapp, store, quiet, fake_env):
    store.create("m")
    dlg = MacroEditorDialog(store, "m")
    dlg.add_step("click")
    assert "target" not in dlg.model.steps[0].data
    txt = dlg.status.text()
    assert "고칠 곳 1개" in txt and "누를 곳" in txt and "steps[" not in txt
    dlg.save()                                       # 물어보고(예) 중간 저장
    assert quiet and quiet[-1][0] == "question" and "누를 곳" in quiet[-1][1]
    assert dlg.saved_name == "m" and store.load("m")["steps"] == [{"type": "click"}]
    w = MainWindowV2(store=store, env_factory=lambda: fake_env, hotkeys=False, emergency_hotkey=None, write_trace=False)
    try:
        w.run_macro("m")                              # 실행은 막힘(엔진 검사)
        assert not w.running_name
        assert quiet[-1][0] == "warning" and "누를 곳" in quiet[-1][1]
    finally:
        w.close()
    from engine.library import FileLibrary
    from engine.model import MacroError
    with pytest.raises(MacroError):                   # 다른 매크로가 부르거나 AI·예약이 불러도 막힘
        FileLibrary(store.root).load("m")


def test_editor_shows_ready_when_valid(qapp, store):
    store.create("m")
    dlg = MacroEditorDialog(store, "m")
    assert "할 일을 더블클릭" in dlg.status.text()
    dlg.add_step("delay")
    assert "바로 실행할 수 있어요" in dlg.status.text()


def test_target_editor_unset_then_pick(qapp):
    class Tools:
        def pick_point(self):
            return (12, 34)
    te = TargetEditor(Tools())
    te.set_target(None)
    assert te.is_unset() and te.target() is None
    got = []
    te.changed.connect(lambda: got.append(te.target()))
    te._pick_from_unset()
    assert te.target() == {"point": [12, 34]} and got
    assert te.kind.findData("unset") < 0, "정한 뒤에는 '정하기 전' 고르기가 사라짐"


def test_target_editor_kind_change_alone_is_not_a_target(qapp):
    te = TargetEditor(None)
    te.set_target(None)
    te.kind.setCurrentIndex(te.kind.findData("point"))
    assert te.target() is None, "종류만 바꾸면 (0,0)이 되면 안 됨"
    te.pt.x.setValue(5)
    assert te.target() == {"point": [5, 0]}


def test_target_editor_keeps_existing_target(qapp):
    te = TargetEditor(None)
    te.set_target({"image": "a.png", "confidence": 0.9, "foo": 1})
    assert te.target() == {"image": "a.png", "confidence": 0.9, "foo": 1}
    assert te.img_more.isChecked()


# ---------------------------------------------------------------- 쉬운 오류 말
def test_friendly_messages():
    m = {"steps": [{"type": "click"}, {"type": "if", "cond": {}, "then": [{"type": "wait", "until": {"exists": {"image": ""}}}]}]}
    assert step_number("steps[1].then[0]") == "2-1"
    a = friendly("steps[0].target: 대상(target)은 객체여야 함", m)
    assert a.startswith("1번 클릭:") and "누를 곳" in a
    b = friendly("steps[1].then[0].until.exists.image: 비어 있지 않은 문자열이어야 함", m)
    assert b.startswith("2-1번 기다리기:") and "그림" in b
    assert friendly("이상한 오류", m) == "이상한 오류"


# ---------------------------------------------------------------- 예시
def test_example_templates_valid_and_have_no_fixed_paths():
    for tpl in ex.templates():
        for lang in ("ko", "en"):
            m = ex.build(tpl, r"C:\어딘가\예시", lang)
            assert validate_macro(m) == [], m["name"]
            s = json.dumps(m, ensure_ascii=False)
            assert "@DATA@" not in s and "python\\\\macro" not in s
        assert tpl["name"]["ko"] != tpl["name"]["en"]


def test_install_examples_copies_data_and_never_overwrites(store, tmp_path):
    store.create(ex.build(ex.templates()[0], "")["name"])        # 같은 이름이 이미 있음
    before = store.load(ex.build(ex.templates()[0], "")["name"])
    res = ex.install(store, str(tmp_path), lambda k: k != "hwp")
    assert len(res["made"]) == 2 and len(res["skipped"]) == 1
    assert store.load(res["skipped"][0]) == before
    assert any("hwp" in lack for _, lack in res["missing"])
    base = res["folder"]
    assert os.path.exists(os.path.join(base, "자료", "정리표_양식.xlsx"))
    assert os.path.isdir(os.path.join(base, "출력"))
    excel = [n for n in res["made"] if "엑셀" in n][0]
    assert base in json.dumps(store.load(excel), ensure_ascii=False).replace("\\\\", "\\")
    assert set(res["made"]) <= set(store.groups()[ex.group_name()])
    again = ex.install(store, str(tmp_path), None)
    assert again["made"] == []


# ---------------------------------------------------------------- 첫 화면
def test_welcome_shown_only_when_empty(qapp, store, fake_env, quiet):
    w = MainWindowV2(store=store, env_factory=lambda: fake_env, hotkeys=False, emergency_hotkey=None, write_trace=False)
    try:
        assert w._welcome_stack.currentWidget() is w.welcome
        w.install_examples()
        assert w._welcome_stack.currentWidget() is not w.welcome
        assert len(store.names()) == 3
        assert quiet and "예시 3개" in quiet[-1][1]
    finally:
        w.close()

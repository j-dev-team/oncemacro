"""매크로 고르기 부품: 검색(띄어쓰기 무시)·맨 위 매크로만·묶음·최근·높이 제한, 예약 창·호출 단계·우클릭."""
import pytest

from gui.v2.store import MacroStore
from gui.v3.macro_picker import ROLE_NAME, MacroPicker, MacroPickerDialog, PickerSource, matches


def _m(name, steps=None):
    return {"version": 2, "name": name, "repeat": {"times": 1}, "steps": steps or [{"type": "delay", "seconds": 0}]}


@pytest.fixture
def store(tmp_path):
    st = MacroStore(str(tmp_path))
    st.save(_m("가게_자동운영", [{"type": "call", "macro": "가게_모험"}, {"type": "call", "macro": "가게_제작걸기_미마_0"}]))
    st.save(_m("가게_모험", [{"type": "call", "macro": "가게_모험_깜짝"}]))
    st.save(_m("가게_모험_깜짝"))
    st.save(_m("가게_제작걸기_미마_0"))
    st.save(_m("메모장 글쓰기"))
    st.save(_m("_시험용"))
    for n in ("가게_자동운영", "가게_모험", "가게_모험_깜짝", "가게_제작걸기_미마_0"):
        st.move_to_group(n, "가게")
    return st


def _names(d):
    out = []

    def walk(it):
        if it.data(0, ROLE_NAME):
            out.append(it.data(0, ROLE_NAME))
        for i in range(it.childCount()):
            walk(it.child(i))
    for i in range(d.tree.topLevelItemCount()):
        walk(d.tree.topLevelItem(i))
    return out


def test_matches_ignores_spaces_case_underscore():
    assert matches("업무_보고서만들기_월간_0", "보고서 만들기")
    assert matches("Memo Pad", "memopad")
    assert not matches("가게_모험", "제작")


def test_roots_only_by_default_and_show_all(qapp, store):
    src = PickerSource.from_store(store, recent=["메모장 글쓰기"])
    d = MacroPickerDialog(src)
    shown = set(_names(d))
    assert shown == {"가게_자동운영", "메모장 글쓰기"}            # 부르는 쪽(맨 위)만, '_' 시험용 숨김
    assert "숨김" in d.count.text()
    d.show_all.setChecked(True)
    assert {"가게_모험", "가게_모험_깜짝", "가게_제작걸기_미마_0"} <= set(_names(d))
    top = [d.tree.topLevelItem(i).text(0) for i in range(d.tree.topLevelItemCount())]
    assert "최근 실행" in top[0] and any("가게" in t for t in top)  # 최근이 맨 위, 묶음 구조


def test_search_filters_and_enter_picks_first(qapp, store):
    d = MacroPickerDialog(PickerSource.from_store(store), roots_only=False)
    d.search.setText("미마 0")
    assert _names(d) == ["가게_제작걸기_미마_0"]
    d._accept()
    assert d.chosen == "가게_제작걸기_미마_0"


def test_current_called_macro_turns_show_all_on(qapp, store):
    d = MacroPickerDialog(PickerSource.from_store(store), current="가게_모험_깜짝")
    assert d.show_all.isChecked() and d._current() == "가게_모험_깜짝"


def test_dialog_height_fits_screen(qapp, store):
    d = MacroPickerDialog(PickerSource.from_store(store))
    h = d.screen().availableGeometry().height()
    assert d.height() <= int(h * 0.9) and d.maximumHeight() <= int(h * 0.9)


def test_schedule_uses_picker_with_preselect(qapp, store, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from gui.v3.main_window import MainWindowV2
    w = MainWindowV2(store=store, hotkeys=False, emergency_hotkey=None, write_trace=False)
    try:
        w.select_macro("메모장 글쓰기")
        seen = {}
        monkeypatch.setattr(QDialog, "exec", lambda self: seen.setdefault("p", getattr(w, "_schedule_picker", None)) and 0)
        w.open_schedules()
        p = seen["p"]
        assert isinstance(p, MacroPicker) and p.name() == "메모장 글쓰기"
        menu = w.build_context_menu(w.macro_list.currentItem())
        assert any(a.text() == "이 매크로 예약…" for a in menu.actions())
    finally:
        w.close()


def test_call_step_uses_picker(qapp, store):
    from gui.v3.editor.macro_editor import MacroEditorDialog
    dlg = MacroEditorDialog(store, "메모장 글쓰기")
    dlg.add_step("call")
    pk = dlg.form.findChild(MacroPicker)
    assert pk is not None
    src = pk.source_fn()
    assert "메모장 글쓰기" not in src.names and "가게_모험_깜짝" in src.names
    pk.set_name("가게_모험")
    assert dlg.model.steps[-1].data.get("macro") == "가게_모험"

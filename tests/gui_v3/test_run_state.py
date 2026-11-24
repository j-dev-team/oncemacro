"""실행 중 화면이 한 상태로 맞는지: 정보 칸 주 버튼(실행↔정지)·다른 매크로 실행 중 안내·도구 줄·메뉴·우클릭,
그리고 실행 기록의 쉬운 위치("12번 › 9번 › 그러면 3번 '이름'")와 그 줄을 누르면 스텝으로 가기."""
import pytest
from gui.v2.store import MacroStore
from gui.v3.editor.friendly import where
from gui.v3.main_window import MainWindowV2
from tests.gui_v3.conftest import wait_until


def _m(name, steps):
    return {"version": 2, "name": name, "repeat": {"times": 1}, "steps": steps}


@pytest.fixture
def win(qapp, tmp_path, fake_env):
    store = MacroStore(str(tmp_path))
    store.save(_m("느린것", [{"type": "repeat", "forever": True, "steps": [{"type": "delay", "seconds": 0.2}]}]))
    store.save(_m("다른것", [{"type": "delay", "seconds": 0}]))
    store.save(_m("건너뛰기", [{"type": "delay", "seconds": 0},
                              {"type": "group", "steps": [
                                  {"type": "if", "cond": {"var": "x", "is_set": True}, "then": [],
                                   "else": [{"type": "delay", "seconds": 0},
                                            {"type": "read_number", "region": [0, 0, 10, 10], "var": "n",
                                             "note": "돈 읽기", "on_fail": "skip"}]}]}]))
    w = MainWindowV2(store=store, env_factory=lambda: fake_env, hotkeys=False, emergency_hotkey=None, write_trace=False)
    yield w
    if w.is_running():
        w.run_thread.stop()
        w.run_thread.wait(3000)
    w.close()


def _menu_texts(win, monkeypatch, name):
    win.select_macro(name)
    menu = win.build_context_menu(win.macro_list.currentItem())
    return {x.text(): x.isEnabled() for x in menu.actions()}


def test_info_button_follows_run_state(qapp, win, monkeypatch):
    win.select_macro("느린것")
    assert win.info_run_btn.text().strip() == "실행" and win.info_run_btn.isEnabled()
    win.run_macro("느린것")
    assert wait_until(qapp, lambda: win.is_running())
    b = win.info_run_btn
    assert b.text().strip() == "정지" and b.objectName() == "StopPrimary" and b.isEnabled()
    assert not win.tool_actions["실행"].isEnabled() and win.tool_actions["정지"].isEnabled()
    assert not win.menu_run_action.isEnabled() and win.menu_stop_action.isEnabled()
    assert not win.info_edit_btn.isEnabled() and not win.info_run_note.isVisible()
    m = _menu_texts(win, monkeypatch, "느린것")
    assert m.get("정지 (Shift+F5)") is True and m.get("편집 (Ctrl+E)") is False

    win.select_macro("다른것")                       # 다른 매크로를 고르면: 실행 흐림 + 안내
    assert b.text().strip() == "실행" and not b.isEnabled() and b.objectName() == "Primary"
    assert not win.info_run_note.isHidden() and "느린것" in win.info_run_note.text()
    assert "느린것" in b.toolTip()
    m = _menu_texts(win, monkeypatch, "다른것")
    assert m.get("실행 (F5) — 다른 매크로 실행 중") is False

    win.select_macro("느린것")
    b.click()                                        # 정보 칸 [정지] 로 멈춤
    assert wait_until(qapp, lambda: win.run_thread is None)
    assert b.text().strip() == "실행" and b.isEnabled() and win.tool_actions["실행"].isEnabled()
    assert not win.tool_actions["정지"].isEnabled() and win.info_run_note.isHidden()


def test_where_is_friendly():
    m = _m("a", [{"type": "delay"}, {"type": "group", "steps": [
        {"type": "if", "cond": {}, "then": [{"type": "key", "keys": "a", "note": "확인 누르기"}]}]}])
    assert where(m, "steps[1].steps[0].then[0]") == "2번 › 1번 › 그러면 1번 '확인 누르기'"
    assert where({}, "steps[11].steps[8].then[2]") == "12번 › 9번 › 그러면 3번"
    assert "steps[" not in where(m, "steps[1]")


def test_log_lines_friendly_and_clickable(qapp, win):
    win.run_macro("건너뛰기")
    assert wait_until(qapp, lambda: win.run_thread is None)
    log = win.log_view.toPlainText()
    line = [ln for ln in log.splitlines() if "건너뜀" in ln]
    assert line, log
    assert "steps[" not in line[0] and "2번 › 1번 › 아니면 2번 '돈 읽기'" in line[0]
    win.select_macro("다른것")
    doc = win.log_view.document()
    blk = next(doc.findBlockByNumber(i) for i in range(doc.blockCount()) if "돈 읽기" in doc.findBlockByNumber(i).text())
    win.go_to_step(blk.userData().macro, blk.userData().path)
    assert win._shown_name == "건너뛰기"
    assert win.steps_view.currentItem() is win.path_items["steps[1].steps[0].else[1]"]

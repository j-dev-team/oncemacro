"""v2 메인 창: 목록·그룹·검색·스텝 보기·실행(가짜 화면) 흐름."""
import pytest
from PySide6.QtCore import Qt

from gui.v3.main_window import ROLE_KIND, ROLE_NAME, MainWindowV2
from gui.v2.store import MacroStore
from tests.gui_v3.conftest import wait_until


def _m(name, steps, **kw):
    d = {"version": 2, "name": name, "repeat": {"times": 1}, "steps": steps}
    d.update(kw)
    return d


@pytest.fixture
def win(qapp, tmp_path, fake_env):
    store = MacroStore(str(tmp_path))
    store.save(_m("클릭하기", [{"type": "click", "target": {"point": [10, 20]}},
                              {"type": "if", "cond": {"var": "x", "is_set": True},
                               "then": [{"type": "delay", "seconds": 1}],
                               "else": [{"type": "key", "keys": "a"}]}], run_hotkey="f9", stop_hotkey="f9"))
    store.save(_m("느린것", [{"type": "repeat", "forever": True, "steps": [{"type": "delay", "seconds": 0.5}]}]))
    store.save(_m("하위", [{"type": "key", "keys": "b"}]))
    store.move_to_group("클릭하기", "작업")
    w = MainWindowV2(store=store, env_factory=lambda: fake_env, hotkeys=False,
                     emergency_hotkey=None, write_trace=False)
    yield w
    if w.is_running():
        w.run_thread.stop()
        w.run_thread.wait(3000)
    w.close()


def _top_items(w):
    out = []
    for i in range(w.macro_list.topLevelItemCount()):
        it = w.macro_list.topLevelItem(i)
        out.append((it.data(0, ROLE_KIND), it.data(0, ROLE_NAME),
                    [it.child(j).data(0, ROLE_NAME) for j in range(it.childCount())]))
    return out


def test_list_groups_and_hotkey_label(win):
    assert _top_items(win) == [("group", "작업", ["클릭하기"]), ("macro", "느린것", []), ("macro", "하위", [])]
    grp = win.macro_list.topLevelItem(0)
    assert "[f9 실행/정지]" in grp.child(0).text(0)


def test_search_filter(win):
    win.search_edit.setText("하위")
    grp = win.macro_list.topLevelItem(0)
    assert grp.isHidden()
    assert not win.macro_list.topLevelItem(2).isHidden()
    assert win.macro_list.topLevelItem(1).isHidden()


def test_select_shows_steps_with_engine_paths(win):
    assert win.select_macro("클릭하기")
    assert win._shown_name == "클릭하기"
    assert set(win.path_items) == {"steps[0]", "steps[1]", "steps[1].then[0]", "steps[1].else[0]"}
    assert win.path_items["steps[0]"].text(0) == "클릭: 좌표 (10, 20)"


def test_run_with_fake_env_marks_steps(qapp, win, fake_env):
    win.select_macro("클릭하기")
    win.run_macro()
    assert win.running_name == "클릭하기"
    assert wait_until(qapp, lambda: win.run_thread is None)
    log = win.log_view.toPlainText()
    assert "클릭하기 완료" in log
    assert win.path_items["steps[0]"].text(1).startswith("완료")
    assert win.path_items["steps[1].else[0]"].text(1).startswith("완료")
    assert win.path_items["steps[1].then[0]"].text(1) == ""
    assert fake_env.input.clicks() == [(10, 20)]
    assert win.run_btn.isEnabled() and not win.stop_btn.isEnabled()


def test_stop_forever_macro(qapp, win):
    win.run_macro("느린것")
    assert wait_until(qapp, lambda: win.path_items["steps[0].steps[0]"].text(1) != "")
    win.stop_macro()
    assert wait_until(qapp, lambda: win.run_thread is None)
    assert "느린것 정지됨" in win.log_view.toPlainText()


def _bg(it):
    return it.background(0).color().name() if it.background(0).style() != Qt.NoBrush else None


def test_highlight_survives_switching_macros(qapp, win):
    """실행 중 다른 매크로를 눌렀다가 돌아와도 진행 중 줄 강조·완료 표시가 다시 보임(11-20 사용자 제보)."""
    from gui.v3.main_window import RUN_BG
    win.run_macro("느린것")
    assert wait_until(qapp, lambda: win.path_items["steps[0].steps[0]"].text(1) != "")
    win.select_macro("하위")
    assert win._shown_name == "하위" and win._highlighted is None
    win.select_macro("느린것")
    it = win.path_items["steps[0].steps[0]"]
    assert _bg(it) == RUN_BG.name()
    assert it.text(1).startswith("완료")
    win.stop_macro()
    assert wait_until(qapp, lambda: win.run_thread is None)
    assert win._highlighted is None and win._run_pos == {}


def test_highlight_in_called_sub_macro_view(qapp, win, fake_env):
    """불려서 도는 하위 매크로를 열어 봐도 그 안의 진행 위치가 강조됨."""
    from gui.v3.main_window import RUN_BG
    sub = _m("느린하위", [{"type": "repeat", "forever": True, "steps": [{"type": "delay", "seconds": 0.3}]}])
    win.store.save(sub)
    fake_env.library.add(sub)
    win.store.save(_m("부름", [{"type": "call", "macro": "느린하위"}]))
    win.reload_list()
    win.run_macro("부름")
    assert wait_until(qapp, lambda: win._run_pos.get("느린하위") == "steps[0].steps[0]")
    assert _bg(win.path_items["steps[0]"]) == RUN_BG.name()          # 부르는 줄이 강조됨
    win.select_macro("느린하위")
    assert wait_until(qapp, lambda: win._highlighted is not None)
    assert win._highlighted is win.path_items["steps[0].steps[0]"]
    win.select_macro("부름")
    assert win._highlighted is win.path_items["steps[0]"]
    win.stop_macro()
    assert wait_until(qapp, lambda: win.run_thread is None)


def test_move_to_group_and_rename(win):
    win._on_moved("하위", "작업")
    assert _top_items(win)[0] == ("group", "작업", ["클릭하기", "하위"])
    updated = win.store.rename("하위", "하위2")
    win.reload_list()
    assert _top_items(win)[0] == ("group", "작업", ["클릭하기", "하위2"])


def test_approval_queue_sentence_diff_and_approve(win):
    from engine import proposals as P
    from gui.v3.main_window import _StoreLib
    root = win.store.root
    p = P.add(root, "하위", "insert_before", "steps[0]",
              [{"type": "click", "target": {"point": [10, 10]}}, {"type": "delay", "seconds": 1}], "이유", "rule")
    s = win.proposal_sentence(p)
    assert "앞에 동작 2개를 추가" in s and "키 입력: b" in s and "클릭: 좌표 (10, 10)" in s
    diff = win.proposal_diff(p)
    assert "바꾸기 전" in diff and "+  클릭: 좌표 (10, 10)" in diff
    win.refresh_approval_badge()
    assert win.approval_action.text().endswith("(1)")
    assert len(win.store.load("하위")["steps"]) == 1                 # 승인 전 원본 그대로
    out = P.decide(root, _StoreLib(win.store), p["id"], approve=True)
    assert out["status"] == "approved" and [x["type"] for x in win.store.load("하위")["steps"]] == ["click", "delay", "key"]
    win.refresh_approval_badge()
    assert not win.approval_action.text().endswith(")")


def test_restart_keeps_new_screen(win, monkeypatch):
    """언어 바꿔 다시 켜기: 새 화면(--v3)으로 다시 떠야 한다(기본이 v2 인 동안)."""
    from PySide6.QtCore import QProcess
    calls = []
    monkeypatch.setattr(QProcess, "startDetached", staticmethod(lambda exe, args: calls.append(args) or True))
    win._restart_app()
    assert calls and "--v3" in calls[0] and "--run" not in calls[0]


def test_click_that_activates_window_does_not_stop(qapp, win):
    """11-23: 채팅 창을 쓰다 이 창을 누른 첫 클릭이 '정보 칸 실행/정지'에 먹어 자동운영이 꺼짐 → 앞으로 온 직후 클릭은 무시."""
    import time
    win.run_macro("느린것")
    assert wait_until(qapp, lambda: win.is_running())
    win._activated_at = time.monotonic()            # 방금 앞으로 옴
    win._info_run_clicked()
    win.stop_btn.click()
    assert win.is_running()                          # 둘 다 무시
    win._activated_at = time.monotonic() - 5        # 이미 앞에 있던 창에서 누름 → 멈춤
    win._info_run_clicked()
    assert wait_until(qapp, lambda: win.run_thread is None)

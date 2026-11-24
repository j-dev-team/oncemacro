"""사무 기능 ②: 클립보드 단계(가짜 클립보드)."""
import os

from engine import new_macro, validate_macro
from engine.clipboard import FakeClipboard
from tests.engine.test_runner import World


def run(steps, cb):
    w = World()
    r = w.runner(new_macro("m", steps))
    r.clipboard = cb
    res = r.run()
    return res, w


def test_copy_presses_ctrl_c_and_reads_new_text_then_decides():
    cb = FakeClipboard("예전 글")
    cb.on_copy = lambda: setattr(cb, "text", "주문 처리 완료")
    res, w = run([{"type": "clipboard", "action": "copy", "var": "상태"},
                  {"type": "if", "cond": {"var": "상태", "contains": "완료"},
                   "then": [{"type": "type_text", "text": "다음"}], "else": [{"type": "type_text", "text": "기록"}]}], cb)
    assert res.status == "ok"
    keys = [e[2] for e in w.input.events if e[1] == "key_down"]
    assert keys[:2] == ["ctrl", "c"]
    assert [e[2] for e in w.input.events if e[1] == "type"] == ["다음"]


def test_copy_fails_when_nothing_copied_old_text_not_reused():
    cb = FakeClipboard("예전 글")          # Ctrl+C 가 아무것도 안 넣음 → 예전 글을 잘못 쓰지 않고 실패
    res, _ = run([{"type": "clipboard", "action": "copy", "var": "x", "timeout": 0.5}], cb)
    assert res.status == "failed" and "복사한 글" in res.error["reason"]


def test_read_write_clear_files_image(tmp_path):
    cb = FakeClipboard("  A-77  ")
    out = str(tmp_path / "그림.png")
    cb.image = b"\x89PNG"
    res, w = run([{"type": "clipboard", "action": "read", "var": "글"},
                  {"type": "text", "var": "번호", "text": "{글}", "action": "trim"},
                  {"type": "clipboard", "action": "write", "text": "번호는 {번호}"},
                  {"type": "clipboard", "action": "save_image", "path": out, "var": "그림파일", "on_fail": "skip"}], cb)
    assert res.status == "ok"
    assert cb.text == "번호는 A-77"
    assert not os.path.exists(out)      # write 가 그림을 지워서 저장할 그림 없음 → 건너뜀
    cb2 = FakeClipboard()
    cb2.files = [r"C:\a\1.pdf", r"C:\a\2.pdf"]
    res2, w2 = run([{"type": "clipboard", "action": "files", "var": "파일들"},
                    {"type": "text", "var": "개수", "text": "{파일들}", "action": "split", "sep": ","},
                    {"type": "clipboard", "action": "clear"}], cb2)
    assert res2.status == "ok" and cb2.files is None
    res3, _ = run([{"type": "clipboard", "action": "read", "var": "x"}], FakeClipboard())
    assert res3.status == "failed"


def test_validate_clipboard_steps():
    assert validate_macro(new_macro("m", [{"type": "clipboard", "action": "copy", "var": "x"},
                                          {"type": "clipboard", "action": "write", "text": "a"}])) == []
    errs = validate_macro(new_macro("m", [{"type": "clipboard", "action": "read"},
                                          {"type": "clipboard", "action": "없음"},
                                          {"type": "clipboard", "action": "save_image"}]))
    assert len(errs) == 3, errs


def test_copy_presses_again_when_first_ctrl_c_is_lost():
    """11-19 실환경: 막 띄운 프로그램이 첫 Ctrl+C 를 놓치면 절반쯤 지나 한 번 더 누름."""
    cb = FakeClipboard("예전 글")
    presses = []

    def on_copy():
        presses.append(1)
        if len(presses) == 2:                # 두 번째 누름에서만 들어옴
            cb.text = "늦게 들어온 글"
    cb.on_copy = on_copy
    res, _ = run([{"type": "clipboard", "action": "copy", "var": "x", "timeout": 1}], cb)
    assert res.status == "ok" and len(presses) == 2

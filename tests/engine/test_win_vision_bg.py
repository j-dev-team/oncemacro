"""'뒤에서 실행' 캡처: 화면 전환 중 잠깐 검정이어도 창 캡처를 계속 쓴다."""
import numpy as np

import engine.win_capture as wb
import engine.win_vision as wv


def _vision(monkeypatch, frames):
    v = wv.MssVision(".")
    it = iter(frames)
    monkeypatch.setattr(wb, "capture_window", lambda h: next(it))
    monkeypatch.setattr(wb, "client_origin", lambda h: (100, 50))
    monkeypatch.setattr(wb, "client_size", lambda h: (40, 30))
    v.bind_window(lambda: 1)
    return v


def _img(val):
    a = np.zeros((30, 40, 3), np.uint8)
    a[:, :20] = val            # 왼쪽 절반만 칠해서 '빈 화면'이 아니게
    return a


def test_short_black_frame_does_not_switch_to_screen(monkeypatch):
    black = np.zeros((30, 40, 3), np.uint8)
    v = _vision(monkeypatch, [black, _img(200)])
    assert v.grab((100, 50, 40, 30)).max() == 0          # 검정 그대로
    v.new_frame()
    assert not v.source_blank
    assert v.grab((100, 50, 10, 10)).max() == 200        # 다음 프레임은 창 내용, 좌표도 창 기준으로 잘림


def test_long_black_switches_to_screen(monkeypatch):
    black = np.zeros((30, 40, 3), np.uint8)
    v = _vision(monkeypatch, [black] * wv.BLANK_FALLBACK)
    monkeypatch.setattr(wv.MssVision, "_sct", lambda self: (_ for _ in ()).throw(RuntimeError("screen")))
    for _ in range(wv.BLANK_FALLBACK - 1):
        v.grab((100, 50, 40, 30))
        v.new_frame()
    assert not v.source_blank
    try:
        v.grab((100, 50, 40, 30))
    except RuntimeError:
        pass
    assert v.source_blank

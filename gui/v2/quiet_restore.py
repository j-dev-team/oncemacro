"""실행이 끝나 최소화를 풀 때 키보드 입력(초점)을 가져가지 않게 되살린다 (Qt 없음, v2·v3 공용).
showNormal() 은 창을 앞으로 가져와 게임·다른 프로그램의 키 입력을 뺏는다(2026-11-17 사용자 결정: 안 뺏게)."""
from __future__ import annotations

import sys

SW_SHOWNOACTIVATE = 4      # 원래 크기로 되살리되 활성화(초점 가져오기)는 안 함


def restore_without_focus(win, native: bool) -> None:
    """win: Qt 창. native: 진짜 윈도우 화면에서 도는지(QApplication.platformName() == 'windows').
    윈도우가 아니면(시험용 화면 등) 보통대로 showNormal()."""
    if native and sys.platform == "win32":
        try:
            import ctypes
            u32 = ctypes.windll.user32
            h = int(win.winId())
            prev = u32.GetForegroundWindow()
            u32.ShowWindow(h, SW_SHOWNOACTIVATE)
            if prev and prev != h and u32.GetForegroundWindow() == h:
                u32.SetForegroundWindow(prev)       # 그래도 가져왔으면 쓰던 창(게임 등)에 돌려준다
            return
        except Exception:
            pass
    win.showNormal()

"""'Run in background' input.

The input part of background mode ships only in the release builds (see Releases). A build made from this
source tree has the screen side (engine/win_capture.py) but cannot send input to background windows;
macros with "window": {"background": true} report a clear error instead.
"""
from __future__ import annotations

from .i18n import t
from .win_capture import BackgroundError, capture_window, client_origin, client_size, looks_blank  # noqa: F401


def bg_standard_available() -> bool:
    """Is the standard background mode included in this build?"""
    return False


def background_input_for(hwnd: int, get_hwnd, standard: bool = True):
    raise BackgroundError(t("이 판에는 '뒤에서 실행'이 들어 있지 않아요. 배포판(Releases)을 쓰세요"))

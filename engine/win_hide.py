"""'숨겨서 실행'(창을 화면에 안 보이게 둔 채로 뒤에서 실행). 이 공개판에는 자리만 있다 — 배포판(Releases)에 들어 있음."""
from __future__ import annotations

from typing import Optional

from .i18n import t
from .win_capture import BackgroundError


def supported() -> bool:
    return False


def is_hidden(h: int) -> bool:
    return False


class HiddenWindow:
    def __init__(self, hwnd: int, root: Optional[str] = None, watch: bool = True):
        self.hwnd = int(hwnd)
        self.path = None
        self.nested = False

    def apply(self) -> None:
        raise BackgroundError(t("이 판에는 '숨겨서 실행'이 들어 있지 않아요. 배포판(Releases)을 쓰세요"))

    def show_for_now(self) -> None:
        return None

    def hide_again(self) -> None:
        return None

    def restore(self) -> None:
        return None


def recover_stale(root=None) -> int:
    return 0


def watch_main(argv=None) -> None:
    return None

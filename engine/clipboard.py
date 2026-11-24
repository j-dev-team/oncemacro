"""클립보드 단계용 통로. 진짜(윈도우)와 가짜(시험)가 같은 모양.

- 글: 읽기·넣기·비우기
- 파일: 탐색기에서 복사한 파일 경로 목록 읽기
- 그림: 복사한 그림을 PNG 로 저장
"""
from __future__ import annotations

import os
from typing import List, Optional

ACTIONS = ("read", "write", "clear", "copy", "files", "save_image")


class RealClipboard:
    def get_text(self) -> Optional[str]:
        from .win_input import get_clipboard_text
        return get_clipboard_text()

    def set_text(self, text: str) -> None:
        from .win_input import set_clipboard_text
        set_clipboard_text(text)

    def clear(self) -> None:
        import ctypes
        from .win_input import _open_clipboard
        _open_clipboard()
        try:
            ctypes.windll.user32.EmptyClipboard()
        finally:
            ctypes.windll.user32.CloseClipboard()

    def _grab(self):
        try:
            from PIL import ImageGrab
            return ImageGrab.grabclipboard()
        except Exception:
            return None

    def get_files(self) -> Optional[List[str]]:
        v = self._grab()
        return [str(p) for p in v] if isinstance(v, list) else None

    def save_image(self, path: str) -> bool:
        v = self._grab()
        if v is None or isinstance(v, list):
            return False
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        v.save(path)
        return True


class FakeClipboard:
    """시험용: 글·파일 목록·그림(아무 객체, save(path) 가 있으면 저장)."""

    def __init__(self, text: Optional[str] = None):
        self.text = text
        self.files: Optional[List[str]] = None
        self.image = None
        self.on_copy = None          # ctrl+c 를 흉내 낼 때 부를 함수(시험에서 넣음)

    def get_text(self):
        return self.text

    def set_text(self, text):
        self.text = text
        self.files = None
        self.image = None

    def clear(self):
        self.text = None
        self.files = None
        self.image = None

    def get_files(self):
        return list(self.files) if self.files is not None else None

    def save_image(self, path):
        if self.image is None:
            return False
        with open(path, "wb") as fh:
            fh.write(self.image if isinstance(self.image, bytes) else b"PNG")
        return True

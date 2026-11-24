"""글꼴(Pretendard)·아이콘(Lucide SVG) 불러오기. 아이콘은 테마 색으로 칠해 캐시한다."""
from __future__ import annotations

import os
import sys
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .tokens import FONT_FAMILIES


def assets_dir() -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "gui", "v3", "assets")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


_loaded = False


def load_fonts() -> str:
    """앱 글꼴을 등록하고 쓸 글꼴 이름을 돌려준다. 오프스크린(시험·캡처)은 시스템 글꼴을 못 봐서 몇 개를 직접 등록."""
    global _loaded
    if not _loaded:
        fd = os.path.join(assets_dir(), "fonts")
        for f in sorted(os.listdir(fd)) if os.path.isdir(fd) else []:
            if f.lower().endswith((".otf", ".ttf")):
                QFontDatabase.addApplicationFont(os.path.join(fd, f))
        from PySide6.QtGui import QGuiApplication
        if QGuiApplication.platformName() == "offscreen":
            for f in ("malgun.ttf", "malgunbd.ttf", "consola.ttf", "seguisym.ttf"):
                p = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", f)
                if os.path.exists(p):
                    QFontDatabase.addApplicationFont(p)
        _loaded = True
    have = set(QFontDatabase.families())
    for f in FONT_FAMILIES:
        if f in have:
            return f
    return QFont().defaultFamily()


@lru_cache(maxsize=1024)
def _svg_bytes(name: str, color: str, stroke: float) -> bytes:
    p = os.path.join(assets_dir(), "icons", "lucide", name + ".svg")
    try:
        s = open(p, encoding="utf-8").read()
    except OSError:
        return b""
    s = s.replace("currentColor", color).replace('stroke-width="2"', f'stroke-width="{stroke}"')
    return s.encode("utf-8")


@lru_cache(maxsize=2048)
def pixmap(name: str, color: str, size: int = 16, stroke: float = 1.75, dpr: float = 2.0) -> QPixmap:
    data = _svg_bytes(name, color, stroke)
    px = int(size * dpr)
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    if data:
        r = QSvgRenderer(QByteArray(data))
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        r.render(p, QRectF(0, 0, px, px))
        p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str, size: int = 16) -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size))
    return ic


def clear_cache():
    pixmap.cache_clear()


def has_icon(name: str) -> bool:
    return os.path.exists(os.path.join(assets_dir(), "icons", "lucide", name + ".svg"))

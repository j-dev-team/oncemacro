"""
스텝 종류별 색·아이콘(그림 파일 없이 그려서 만듦). 메인 화면·편집기 스텝 목록·부품 상자·도구 모음에서 쓴다.

색은 종류 묶음을 뜻한다: 보라 = 화면·입력, 초록 = 웹, 주황 = 흐름·변수, 회색 = 기다리기·프로그램·메모.
"""
from __future__ import annotations

from functools import lru_cache

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

from .i18n import tr

CATEGORY_COLORS = {
    "input": "#534AB7",     # 화면·입력
    "web": "#1D9E75",       # 웹
    "flow": "#D85A30",      # 흐름·변수
    "misc": "#5F5E5A",      # 기다리기·프로그램·메모
    "office": "#185FA5",    # 오피스(엑셀·한글·워드)
}
CATEGORY_NAMES = {"input": "화면·입력", "web": "웹", "flow": "흐름·변수", "misc": "기다리기·프로그램", "office": "오피스"}

# 스텝 종류 → (묶음, 아이콘 글자)
STEP_ICONS = {
    "click": ("input", "클"), "move": ("input", "이"), "drag": ("input", "끌"), "scroll": ("input", "휠"),
    "mouse_down": ("input", "누"), "mouse_up": ("input", "떼"), "key": ("input", "키"),
    "type_text": ("input", "글"), "remember": ("input", "기"), "read_number": ("input", "숫"),
    "snapshot": ("input", "찍"),
    "web": ("web", "웹"),
    "excel": ("office", "X"), "word": ("office", "W"), "hwp": ("office", "한"),
    "if": ("flow", "?"), "repeat": ("flow", "↻"), "for_each": ("flow", "≡"), "group": ("flow", "▤"),
    "break": ("flow", "⏏"), "continue": ("flow", "»"), "call": ("flow", "↗"), "return": ("flow", "■"),
    "stop": ("flow", "✕"), "set": ("flow", "="), "set_result": ("flow", "→"),
    "wait": ("misc", "…"), "delay": ("misc", "z"), "launch": ("misc", "▷"), "menu": ("input", "메"),
    "close_window": ("misc", "▢"), "wait_window": ("misc", "◫"), "comment": ("misc", "#"),
}

# 부품 상자 묶음(편집기 오른쪽)
PALETTE = [
    ("마우스", ["click", "move", "drag", "scroll", "mouse_down", "mouse_up"]),
    ("키보드", ["key", "type_text"]),
    ("그림·화면", ["remember", "read_number", "snapshot"]),
    ("웹 요소", ["web"]),
    ("오피스", ["excel", "hwp", "word"]),
    ("기다리기", ["wait", "delay"]),
    ("흐름", ["if", "repeat", "for_each", "group", "break", "continue", "call", "return", "stop"]),
    ("변수", ["set", "set_result"]),
    ("프로그램·메모", ["menu", "launch", "close_window", "wait_window", "comment"]),
]


def palette():
    """부품 상자 묶음(묶음 이름을 지금 언어로)."""
    return [(tr(title), list(types)) for title, types in PALETTE]


def category_names():
    return {k: tr(v) for k, v in CATEGORY_NAMES.items()}


@lru_cache(maxsize=256)
def glyph_icon(text: str, color: str, size: int = 32) -> QIcon:
    """색 바탕 둥근 네모에 흰 글자 하나."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(QRectF(1, 1, size - 2, size - 2), size * 0.22, size * 0.22)
    f = QFont()
    f.setBold(True)
    f.setPixelSize(int(size * (0.5 if len(text) == 1 else 0.36)))
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, text)
    p.end()
    return QIcon(pm)


def step_icon(step_type: str) -> QIcon:
    cat, ch = STEP_ICONS.get(step_type, ("misc", "·"))
    return glyph_icon(ch, CATEGORY_COLORS[cat])


def tool_icon(text: str, color: str = "#444441") -> QIcon:
    return glyph_icon(text, color, 40)

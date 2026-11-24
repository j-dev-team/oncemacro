"""
스텝 종류별 색·아이콘(그림 파일 없이 그려서 만듦). 메인 화면·편집기 스텝 목록·부품 상자·도구 모음에서 쓴다.

색은 종류 묶음을 뜻한다: 보라 = 화면·입력, 초록 = 웹, 주황 = 흐름·변수, 회색 = 기다리기·프로그램·메모.
"""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

from gui.v2.i18n import tr

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
    "text": ("flow", "가"), "date": ("flow", "일"), "calc": ("flow", "+"), "clipboard": ("input", "복"),
    "file": ("misc", "파"), "each": ("flow", "≣"),
    "ask": ("misc", "?"), "notify": ("misc", "!"), "pdf": ("office", "P"), "mail": ("office", "@"), "list": ("flow", "≡"), "memory": ("misc", "M"),
    "wait": ("misc", "…"), "delay": ("misc", "z"), "launch": ("misc", "▷"), "menu": ("input", "메"),
    "close_window": ("misc", "▢"), "wait_window": ("misc", "◫"), "comment": ("misc", "#"),
}

# 부품 상자 묶음(편집기 오른쪽)
PALETTE = [
    ("마우스", ["click", "move", "drag", "scroll", "mouse_down", "mouse_up"]),
    ("키보드", ["key", "type_text", "clipboard"]),
    ("그림·화면", ["remember", "read_number", "snapshot"]),
    ("웹 요소", ["web"]),
    ("오피스", ["excel", "hwp", "word", "pdf", "mail"]),
    ("파일", ["file"]),
    ("묻기·알림", ["ask", "notify"]),
    ("기다리기", ["wait", "delay"]),
    ("흐름", ["if", "repeat", "each", "for_each", "group", "break", "continue", "call", "return", "stop"]),
    ("변수·글자", ["set", "list", "text", "date", "calc", "set_result"]),
    ("프로그램·메모", ["menu", "launch", "close_window", "wait_window", "comment"]),
]


def palette():
    """부품 상자 묶음(묶음 이름을 지금 언어로)."""
    out = [(tr(title), list(types)) for title, types in PALETTE]
    # 11-19: 메모리는 '메모리 에디터'(혼자 하는 게임용 창)만 남기고, 매크로 단계로는 숨김
    return out


def memory_on() -> bool:
    """메모리 매크로 부가 기능이 켜져 있는지(꺼져 있으면 부품 상자·메뉴에 안 보임)."""
    try:
        from engine.memory import enabled
        return enabled()
    except Exception:
        return False


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


# 새 화면: 스텝 종류 → 선 아이콘(Lucide). 흐름 묶음은 강조색, 나머지는 흐린 글자색.
STEP_LUCIDE = {
    "click": "mouse-pointer-click", "move": "move", "drag": "hand-grab", "scroll": "mouse",
    "mouse_down": "mouse-pointer-2", "mouse_up": "mouse-pointer", "key": "keyboard", "type_text": "type",
    "remember": "map-pin", "read_number": "hash", "snapshot": "camera", "web": "globe",
    "excel": "sheet", "word": "file-type", "hwp": "file-text",
    "if": "git-branch", "repeat": "repeat", "for_each": "list-checks", "group": "folder", "break": "log-out",
    "continue": "skip-forward", "call": "corner-down-right", "return": "undo-2", "stop": "octagon-x",
    "set": "variable", "set_result": "flag", "text": "replace", "date": "calendar-clock", "calc": "scale", "clipboard": "clipboard", "file": "folder", "each": "list", "ask": "message-square", "notify": "flag", "pdf": "file-text", "mail": "message-square", "list": "list-checks", "memory": "hash", "wait": "hourglass", "delay": "timer", "launch": "rocket",
    "menu": "menu", "close_window": "square-x", "wait_window": "app-window", "comment": "message-square",
}
# 도구 모음 글자 → 선 아이콘
TOOL_LUCIDE = {"+": "plus", "✎": "pencil", "●": "circle-dot", "▶": "play", "■": "square", "⌨": "keyboard",
               "◷": "clock", "⧉": "copy", "✕": "trash", "☰": "rotate-ccw-clock", "✦": "sparkles",
               "?": "circle-question-mark"}


def _theme():
    from .design import theme
    return theme.current()


def step_icon(step_type: str) -> QIcon:
    from .design.assets import icon
    t = _theme()
    cat = STEP_ICONS.get(step_type, ("misc", ""))[0]
    return icon(STEP_LUCIDE.get(step_type, "circle"), t["accent"] if cat == "flow" else t["muted"], 16)


def tool_icon(text: str, color: str = "#444441") -> QIcon:
    from .design.assets import icon
    t = _theme()
    col = {"#A32D2D": t["bad"], "#3B6D11": t["ok"], "#185FA5": t["accent"], "#534AB7": t["accent"]}.get(color, t["text"])
    return icon(TOOL_LUCIDE.get(text, "circle"), col, 18)

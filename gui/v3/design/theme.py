"""디자인 값 → 화면 꾸밈. 시작할 때와 테마·촘촘함·글자 크기를 바꿀 때 apply() 한 번.
- 설정은 QSettings MacroManager/v3 (theme: system|light|dark, density: comfortable|compact, scale, motion: auto|on|off)
- 모든 화면 코드는 current() 값만 쓰고 색 번호를 직접 쓰지 않는다."""
from __future__ import annotations

import ctypes
import os
from typing import Optional

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette

from . import assets, tokens

_current: dict = tokens.build()
_listeners = []


def prefs() -> QSettings:
    from PySide6 import QtCore
    from gui.v2.settings_path import open_settings     # 폴더형 묶음이면 자료 폴더의 설정 파일
    return open_settings(QtCore, "v3")


def pref(key: str, default):
    v = prefs().value(key, default)
    if isinstance(default, float):
        try:
            return float(v)
        except (TypeError, ValueError):
            return default
    return v if v not in (None, "") else default


def set_pref(key: str, value) -> None:
    if not os.environ.get("MACRO_LANG"):          # 시험·캡처 실행은 사용자 설정을 안 바꿈
        prefs().setValue(key, value)


def system_is_dark() -> bool:
    try:
        hints = QGuiApplication.styleHints()
        return hints.colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def reduce_motion() -> bool:
    """움직임 줄이기: 설정이 '끔'이거나, '자동'인데 윈도우 애니메이션 효과가 꺼져 있으면 참."""
    m = pref("motion", "auto")
    if m == "off":
        return True
    if m == "on":
        return False
    try:
        val = ctypes.c_int(1)
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(val), 0)   # SPI_GETCLIENTAREAANIMATION
        return not bool(val.value)
    except Exception:
        return False


def duration(kind: str) -> int:
    return 0 if reduce_motion() else tokens.MOTION.get(kind, 150)


def current() -> dict:
    return _current


def on_change(fn) -> None:
    _listeners.append(fn)


def resolve(theme: Optional[str] = None, density: Optional[str] = None, scale: Optional[float] = None) -> dict:
    th = theme or os.environ.get("MACRO_THEME") or pref("theme", "system")
    if th == "system":
        th = "dark" if system_is_dark() else "light"
    de = density or os.environ.get("MACRO_DENSITY") or pref("density", "comfortable")
    sc = scale if scale is not None else pref("scale", 1.0)
    return tokens.build(th, de, sc)


def apply(app, theme: Optional[str] = None, density: Optional[str] = None, scale: Optional[float] = None) -> dict:
    global _current
    t = resolve(theme, density, scale)
    t["family"] = assets.load_fonts()
    _current = t
    f = QFont(t["family"])
    f.setPixelSize(t["font_body"])
    f.setHintingPreference(QFont.PreferNoHinting)
    app.setFont(f)
    app.setStyle("Fusion")
    pal = QPalette()
    for role, key in ((QPalette.Window, "bg"), (QPalette.Base, "surface"), (QPalette.AlternateBase, "surface2"),
                      (QPalette.Text, "text"), (QPalette.WindowText, "text"), (QPalette.ButtonText, "text"),
                      (QPalette.Button, "surface2"), (QPalette.Highlight, "accent"),
                      (QPalette.HighlightedText, "on_accent"), (QPalette.PlaceholderText, "muted"),
                      (QPalette.ToolTipBase, "surface"), (QPalette.ToolTipText, "text"), (QPalette.Link, "accent"),
                      (QPalette.Mid, "line"), (QPalette.Midlight, "line"), (QPalette.Light, "surface"),
                      (QPalette.Dark, "line"), (QPalette.Shadow, "line"), (QPalette.BrightText, "bad")):
        pal.setColor(role, QColor(t[key]))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(t["muted"]))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor(t["muted"]))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(t["muted"]))
    app.setPalette(pal)
    t["check_png"] = _icon_png("check", t["on_accent"], 14, 3.0)
    t["down_png"] = _icon_png("chevron-down", t["muted"], 14, 2.0)
    t["up_png"] = _icon_png("chevron-up", t["muted"], 12, 2.0)
    t["down_small_png"] = _icon_png("chevron-down", t["muted"], 12, 2.0)
    app.setStyleSheet(qss(t))
    assets.clear_cache()
    for fn in list(_listeners):
        try:
            fn(t)
        except Exception:
            pass
    return t


def _icon_png(name: str, color: str, size: int, stroke: float) -> str:
    """QSS 의 image: url() 에 쓸 아이콘 그림(테마 색)을 임시 폴더에 만들어 경로를 돌려준다."""
    import tempfile
    d = os.path.join(tempfile.gettempdir(), "macro_v3_theme")
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, f"{name}_{color.lstrip('#')}_{size}.png")
    if not os.path.exists(out):
        assets.pixmap(name, color, size, stroke, 2.0).save(out)
    return out.replace("\\", "/")


def dark_title_bar(widget, dark: bool) -> None:
    """윈도우 10(2004+)·11 제목줄을 테마에 맞춤(DWMWA_USE_IMMERSIVE_DARK_MODE=20). 안 되면 조용히 넘어감."""
    try:
        hwnd = int(widget.winId())
        v = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(v), ctypes.sizeof(v))
    except Exception:
        pass


def qss(t: dict) -> str:
    rs, rm, rl, rb = t["radius_s"], t["radius_m"], t["radius_l"], t["radius_btn"]
    ch = t["control_h"]
    return f"""
* {{ font-family: '{t['family']}'; }}
QWidget {{ color: {t['text']}; }}
QMainWindow, QDialog, #Root {{ background: {t['bg']}; }}
QToolTip {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['line']}; border-radius: 6px; padding: 4px 8px; }}

/* 카드 */
#Card, QGroupBox {{ background: {t['surface']}; border: none; border-radius: {rm}px; }}
QGroupBox {{ margin-top: 0; padding: {t['pad'] + 10}px {t['pad'] - 6}px {t['pad'] - 8}px {t['pad'] - 6}px; }}
QGroupBox::title {{ subcontrol-origin: padding; subcontrol-position: top left; left: {t['pad'] - 6}px; top: 8px;
    color: {t['muted']}; font-size: {t['font_small']}px; font-weight: 600; }}
#Section {{ color: {t['muted']}; font-size: {t['font_small']}px; font-weight: 600; }}
#Muted {{ color: {t['muted']}; font-size: {t['font_small']}px; }}
#Title {{ font-size: {t['font_title']}px; font-weight: 600; }}
#Subtitle {{ font-size: {t['font_subtitle']}px; font-weight: 600; }}
#Nav {{ background: {t['nav']}; }}
#Bar {{ background: {t['bg']}; }}
#StatusLine {{ background: {t['bg']}; }}

/* 입력칸 */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QKeySequenceEdit, QDateTimeEdit, QTimeEdit {{
    background: {t['surface2']}; border: 1px solid {t['surface2']}; border-radius: {rs}px;
    padding: 0 10px; min-height: {ch - 4}px; selection-background-color: {t['accent']}; selection-color: {t['on_accent']};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {t['accent']}; background: {t['surface']}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {t['muted']}; background: {t['bg']}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url({t.get('down_png', '')}); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['line']}; border-radius: {rs}px;
    selection-background-color: {t['sel']}; selection-color: {t['text']}; outline: 0; padding: 4px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 18px; border: none; background: transparent; }}
QAbstractSpinBox::up-arrow {{ image: url({t.get('up_png', '')}); width: 12px; height: 12px; }}
QAbstractSpinBox::down-arrow {{ image: url({t.get('down_small_png', '')}); width: 12px; height: 12px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {t['hover']}; border-radius: 4px; }}
QPlainTextEdit, QTextEdit, QTextBrowser {{ background: {t['surface']}; border: none; border-radius: {rs}px; padding: 6px;
    selection-background-color: {t['accent']}; selection-color: {t['on_accent']}; }}

/* 버튼 */
QPushButton {{ background: {t['surface2']}; border: none; border-radius: {rb if ch >= 34 else rs}px;
    padding: 0 16px; min-height: {ch}px; }}
QPushButton:hover {{ background: {t['hover']}; }}
QPushButton:pressed {{ background: {t['accent_soft']}; }}
QPushButton:disabled {{ color: {t['muted']}; background: {t['bg']}; }}
QPushButton:default, QPushButton#Primary {{ background: {t['accent']}; color: {t['on_accent']}; font-weight: 600; }}
QPushButton#Primary:hover, QPushButton:default:hover {{ background: {t['accent']}; }}
QPushButton#Danger {{ color: {t['bad']}; }}
QPushButton#StopPrimary, QPushButton#StopPrimary:hover {{ background: {t['bad']}; color: {t['on_accent']}; font-weight: 600; }}
QPushButton#Primary:disabled, QPushButton:default:disabled {{ background: {t['surface2']}; color: {t['muted']}; }}
QToolButton {{ border: none; border-radius: {rs}px; padding: 4px 8px; background: transparent; }}
QToolButton:hover {{ background: {t['hover']}; }}
QToolButton:checked {{ background: {t['accent_soft']}; }}
QToolButton:disabled {{ color: {t['muted']}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QDialogButtonBox QPushButton {{ min-width: 72px; }}

/* 목록·트리·표 */
QTreeView, QTreeWidget, QListView, QListWidget, QTableView, QTableWidget {{
    background: {t['surface']}; border: none; border-radius: {rm}px; outline: 0;
    selection-background-color: {t['sel']}; selection-color: {t['text']}; alternate-background-color: {t['surface2']}; }}
QTreeView::item, QListView::item {{ padding: 2px 4px; border-radius: {rs}px; }}
QTreeView::item:hover, QListView::item:hover {{ background: {t['hover']}; }}
QTreeView {{ show-decoration-selected: 0; }}
QTreeView::branch {{ background: transparent; }}
QTreeView::branch:selected, QTreeView::branch:hover {{ background: transparent; }}
QTreeView::item:selected, QListView::item:selected, QTableView::item:selected {{ background: {t['sel']}; color: {t['text']}; }}
QHeaderView::section {{ background: {t['surface']}; border: none; border-bottom: 1px solid {t['line']};
    color: {t['muted']}; padding: 6px 8px; font-size: {t['font_small']}px; font-weight: 600; }}
QTableView {{ gridline-color: {t['line']}; }}
QTableView::item {{ padding: 4px 8px; }}
QTableCornerButton::section {{ background: {t['surface']}; border: none; }}

/* 메뉴 */
QMenuBar {{ background: transparent; color: {t['muted']}; padding: 2px 6px; }}
QMenuBar::item {{ padding: 4px 10px; border-radius: 6px; background: transparent; }}
QMenuBar::item:selected {{ background: {t['hover']}; color: {t['text']}; }}
QMenu {{ background: {t['surface']}; border: 1px solid {t['line']}; border-radius: {rs}px; padding: 6px; }}
QMenu::item {{ padding: 6px 28px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t['sel']}; }}
QMenu::item:disabled {{ color: {t['muted']}; }}
QMenu::separator {{ height: 1px; background: {t['line']}; margin: 4px 8px; }}

/* 기타 */
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 18px; height: 18px; }}
QCheckBox::indicator {{ border: 1.5px solid {t['muted']}; border-radius: 5px; background: {t['surface']}; }}
QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; image: url({t.get('check_png', '')}); }}
QCheckBox::indicator:disabled {{ border-color: {t['line']}; }}
QTabWidget::pane {{ border: none; background: {t['surface']}; border-radius: {rm}px; }}
QTabBar::tab {{ background: transparent; padding: 8px 16px; border-radius: {rb}px; margin: 2px; color: {t['muted']}; }}
QTabBar::tab:selected {{ background: {t['accent_soft']}; color: {t['text']}; font-weight: 600; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {t['line']}; border-radius: 3px; min-height: 30px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: {t['muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QSplitter::handle {{ background: transparent; }}
QStatusBar {{ background: {t['bg']}; color: {t['muted']}; padding-left: {t['pad']}px; font-size: {t['font_small']}px; }}
QStatusBar QLabel {{ color: {t['muted']}; font-size: {t['font_small']}px; }}
QStatusBar::item {{ border: none; }}
QProgressBar {{ background: {t['surface2']}; border: none; border-radius: 4px; height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: {t['accent']}; border-radius: 4px; }}
QScrollArea {{ background: transparent; border: none; }}
"""

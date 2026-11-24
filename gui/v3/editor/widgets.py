"""
편집기 입력 부품: 선택값(기본/값/없음), 좌표, 영역, 색, 값 입력.

'기본값'은 키를 아예 빼서 매크로 설정값을 쓰게 하고, '무한'·'끔'은 null 을 넣는다
(엔진에서 timeout: null = 무한 대기, color_check: null = 색 검사 끔).
"""
from __future__ import annotations

import json
from typing import Any, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QWidget)

from gui.v2.i18n import tr

ABSENT = object()


def fit_stack(stack) -> None:
    """QStackedWidget 은 가장 큰 쪽 크기를 차지해 빈 공간이 생긴다 → 지금 보이는 쪽만 크기를 갖게."""
    from PySide6.QtWidgets import QSizePolicy
    cur = stack.currentWidget()
    for i in range(stack.count()):
        w = stack.widget(i)
        pol = QSizePolicy.Preferred if w is cur else QSizePolicy.Ignored
        w.setSizePolicy(pol, pol)
    stack.updateGeometry()


def _row(parent: QWidget) -> QHBoxLayout:
    lay = QHBoxLayout(parent)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    return lay


def spin(lo=-99999, hi=99999, val=0, width=72) -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(val)
    s.setFixedWidth(width)
    return s


def dspin(lo=0.0, hi=99999.0, val=0.0, decimals=2, step=0.1, width=80) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setValue(val)
    s.setFixedWidth(width)
    return s


class OptValue(QWidget):
    """[기본값 | 값 | (무한/끔)] + 숫자. value() → ABSENT(키 빼기) / None / 숫자."""
    changed = Signal()

    def __init__(self, default_label="기본값", null_label: Optional[str] = None,
                 lo=0.0, hi=99999.0, decimals=2, step=0.1, initial=1.0, integer=False, parent=None):
        super().__init__(parent)
        lay = _row(self)
        self.mode = QComboBox()
        self.mode.addItem(tr(default_label), "absent")
        self.mode.addItem(tr("값"), "value")
        if null_label:
            self.mode.addItem(tr(null_label), "null")
        self.integer = integer
        self.num = spin(int(lo), int(hi), int(initial)) if integer else dspin(lo, hi, initial, decimals, step)
        lay.addWidget(self.mode)
        lay.addWidget(self.num)
        lay.addStretch(1)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.num.valueChanged.connect(lambda _=None: self.changed.emit())
        self._mode_changed()

    def _mode_changed(self, *_):
        self.num.setEnabled(self.mode.currentData() == "value")
        self.changed.emit()

    def set_value(self, v: Any = ABSENT):
        self.blockSignals(True)
        if v is ABSENT:
            self.mode.setCurrentIndex(self.mode.findData("absent"))
        elif v is None and self.mode.findData("null") >= 0:
            self.mode.setCurrentIndex(self.mode.findData("null"))
        else:
            self.mode.setCurrentIndex(self.mode.findData("value"))
            try:
                self.num.setValue(int(v) if self.integer else float(v))
            except (TypeError, ValueError):
                pass
        self.num.setEnabled(self.mode.currentData() == "value")
        self.blockSignals(False)

    def value(self) -> Any:
        m = self.mode.currentData()
        if m == "absent":
            return ABSENT
        if m == "null":
            return None
        return int(self.num.value()) if self.integer else round(float(self.num.value()), 4)


def apply_opt(d: dict, key: str, v: Any) -> None:
    """OptValue 결과를 dict 에 반영(ABSENT 면 키 삭제)."""
    if v is ABSENT:
        d.pop(key, None)
    else:
        d[key] = v


class XYEdit(QWidget):
    changed = Signal()
    pick = Signal()

    def __init__(self, pick_label: Optional[str] = "화면에서 찍기", parent=None):
        super().__init__(parent)
        lay = _row(self)
        self.x = spin()
        self.y = spin()
        lay.addWidget(QLabel("x"))
        lay.addWidget(self.x)
        lay.addWidget(QLabel("y"))
        lay.addWidget(self.y)
        self.pick_btn = None
        if pick_label:
            self.pick_btn = QPushButton(tr(pick_label))
            self.pick_btn.setMinimumWidth(0)
            self.pick_btn.clicked.connect(self.pick.emit)
            lay.addWidget(self.pick_btn)
        lay.addStretch(1)
        for s in (self.x, self.y):
            s.valueChanged.connect(lambda _=None: self.changed.emit())

    def set_xy(self, v):
        self.blockSignals(True)
        try:
            self.x.setValue(int(v[0]))
            self.y.setValue(int(v[1]))
        except Exception:
            pass
        self.blockSignals(False)

    def xy(self):
        return [self.x.value(), self.y.value()]


class RegionEdit(QWidget):
    changed = Signal()
    pick = Signal()

    def __init__(self, pick_label: Optional[str] = "화면에서 지정", parent=None):
        super().__init__(parent)
        # 두 줄: [화면에서 지정] 위, 숫자 넷은 아래 2×2 — 좁은 오른쪽 칸(1280 화면)에서도 잘리지 않게
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)
        self.x, self.y = spin(), spin()
        self.w, self.h = spin(1, 99999, 100), spin(1, 99999, 100)
        self.pick_btn = None
        top = 0
        if pick_label:
            self.pick_btn = QPushButton(tr(pick_label))
            self.pick_btn.setMinimumWidth(0)
            self.pick_btn.clicked.connect(self.pick.emit)
            grid.addWidget(self.pick_btn, 0, 0, 1, 4, Qt.AlignLeft)
            top = 1
        for i, (lab, s) in enumerate((("x", self.x), ("y", self.y), (tr("너비"), self.w), (tr("높이"), self.h))):
            grid.addWidget(QLabel(lab), top + i // 2, (i % 2) * 2)
            grid.addWidget(s, top + i // 2, (i % 2) * 2 + 1)
            s.valueChanged.connect(lambda _=None: self.changed.emit())
        grid.setColumnStretch(4, 1)

    def set_region(self, r):
        self.blockSignals(True)
        try:
            self.x.setValue(int(r[0]))
            self.y.setValue(int(r[1]))
            self.w.setValue(max(1, int(r[2])))
            self.h.setValue(max(1, int(r[3])))
        except Exception:
            pass
        self.blockSignals(False)

    def region(self):
        return [self.x.value(), self.y.value(), self.w.value(), self.h.value()]


class ColorEdit(QWidget):
    changed = Signal()
    pick = Signal()

    def __init__(self, pick_label: Optional[str] = "화면에서 색 찍기", parent=None):
        super().__init__(parent)
        lay = _row(self)
        self.r, self.g, self.b = spin(0, 255, 0, 56), spin(0, 255, 0, 56), spin(0, 255, 0, 56)
        self.swatch = QLabel()
        self.swatch.setFixedSize(28, 18)
        for lab, s in (("R", self.r), ("G", self.g), ("B", self.b)):
            lay.addWidget(QLabel(lab))
            lay.addWidget(s)
            s.valueChanged.connect(self._on_change)
        lay.addWidget(self.swatch)
        self.pick_btn = None
        if pick_label:
            self.pick_btn = QPushButton(tr(pick_label))
            self.pick_btn.setMinimumWidth(0)
            self.pick_btn.clicked.connect(self.pick.emit)
            lay.addWidget(self.pick_btn)
        lay.addStretch(1)
        self._paint()

    def _paint(self):
        c = QColor(self.r.value(), self.g.value(), self.b.value())
        self.swatch.setStyleSheet(f"background:{c.name()}; border:1px solid #999")

    def _on_change(self, *_):
        self._paint()
        self.changed.emit()

    def set_rgb(self, v):
        self.blockSignals(True)
        try:
            self.r.setValue(int(v[0]))
            self.g.setValue(int(v[1]))
            self.b.setValue(int(v[2]))
        except Exception:
            pass
        self._paint()
        self.blockSignals(False)

    def rgb(self):
        return [self.r.value(), self.g.value(), self.b.value()]


class LiteralEdit(QLineEdit):
    """값 입력: 숫자·true/false·null·"따옴표 문자열"·[목록] 은 JSON 으로, 그 밖은 글자 그대로."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.textChanged.connect(lambda _=None: self.changed.emit())
        self.setPlaceholderText(tr('예: 3, true, "글자", 그냥 글자'))

    def set_literal(self, v):
        self.blockSignals(True)
        self.setText(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
        self.blockSignals(False)

    def literal(self):
        t = self.text()
        try:
            return json.loads(t)
        except (ValueError, TypeError):
            return t


def parse_hues(text: str):
    """'0-10, 160-180' → [[0,10],[160,180]] / 빈 글자 → None."""
    text = (text or "").strip()
    if not text:
        return None
    out = []
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        lo, _, hi = part.partition("-")
        out.append([float(lo), float(hi or lo)])
    return [[int(a) if a == int(a) else a, int(b) if b == int(b) else b] for a, b in out]


def hues_text(h) -> str:
    if not h:
        return ""
    return ", ".join(f"{a}-{b}" for a, b in h)

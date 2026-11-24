"""매크로가 하나도 없을 때 보여 주는 첫 화면: 세 갈래(녹화 / AI에게 시키기 / 예시에서 시작) + 직접 만들기.

wide=True  : 목록·오른쪽 칸 자리를 통째로 차지(안 B)
wide=False : 오른쪽 칸 자리에만(안 A, 왼쪽 빈 목록은 그대로)
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QBoxLayout, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from gui.v2.i18n import tr


class _Choice(QFrame):
    def __init__(self, icon: str, title: str, text: str, button: str, primary: bool, t: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("WelcomeChoice")
        self.setStyleSheet(f"QFrame#WelcomeChoice {{ background: {t['surface2']}; border-radius: 12px; }}")
        self._t, self._icon_name = t, icon
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(8)
        self._v = v
        head = QHBoxLayout()
        head.setSpacing(10)
        ic = QLabel()
        try:
            from .design.assets import pixmap
            ic.setPixmap(pixmap(icon, t["accent"], 22))
        except Exception:
            pass
        head.addWidget(ic)
        self._ic = ic
        tl = QLabel(title)
        self._tl = tl
        tl.setObjectName("Subtitle")
        head.addWidget(tl, 1)
        v.addLayout(head)
        body = QLabel(text)
        body.setWordWrap(True)
        body.setObjectName("Muted")
        body.setMinimumHeight(body.fontMetrics().lineSpacing() * 3)
        body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._body = body
        v.addWidget(body, 1)
        self.button = QPushButton(button)
        self._primary = primary
        if primary:
            self.button.setObjectName("Primary")
            self.button.setStyleSheet(f"font-size: {t['font_body']}px; padding: 6px 16px; border: 1px solid transparent;")
        else:                               # 기본 단추 색이 카드 바탕과 같아 안 보이므로 흰 바탕으로
            self.button.setStyleSheet(self._sec_style(1.0))
        self.button.setMinimumWidth(0)
        self.button.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout()
        row.addWidget(self.button)
        row.addStretch(1)
        v.addLayout(row)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

    def _sec_style(self, k: float) -> str:
        t = self._t
        return (f"QPushButton {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['line']};"
                f" border-radius: 8px; font-size: {int(t['font_body'] * k)}px; padding: {int(6 * k)}px {int(16 * k)}px; }}"
                f"QPushButton:hover {{ border-color: {t['accent']}; }}")

    def set_scale(self, k: float):
        """큰 화면에서 카드 안 글자·여백·아이콘을 키운다(k=1 이 기본)."""
        t = self._t
        m = int(20 * k)
        self._v.setContentsMargins(m, int(18 * k), m, int(18 * k))
        self._v.setSpacing(int(8 * k))
        self._tl.setStyleSheet(f"font-size: {int(t['font_subtitle'] * k)}px; font-weight: 600;")
        self._body.setStyleSheet(f"color: {t['muted']}; font-size: {int(t['font_small'] * k)}px;")
        self._body.setMinimumHeight(int(self._body.fontMetrics().lineSpacing() * 3 * max(1.0, k)))
        fs = int(t['font_body'] * k)
        if self._primary:
            self.button.setStyleSheet(f"font-size: {fs}px; padding: {int(6 * k)}px {int(16 * k)}px; border: 1px solid transparent;")
        else:
            self.button.setStyleSheet(self._sec_style(k))
        try:
            from .design.assets import pixmap
            self._ic.setPixmap(pixmap(self._icon_name, t["accent"], int(22 * k)))
        except Exception:
            pass


class WelcomePanel(QFrame):
    record = Signal()
    ai = Signal()
    examples = Signal()
    new = Signal()

    def __init__(self, wide: bool, parent=None):
        super().__init__(parent)
        from .design import theme as _theme
        t = _theme.current()
        self.setObjectName("Card")
        self.wide = wide
        frame = QHBoxLayout(self)
        frame.setContentsMargins(32, 28, 32, 28)
        inner = QWidget()
        self._inner = inner
        self._t = t
        self._scale = 0.0
        if wide:
            inner.setMaximumWidth(1100)      # 큰 화면에서 글이 너무 길게 퍼지지 않게(크기에 맞춰 resizeEvent 에서 키움)
        frame.addStretch(0 if not wide else 1)
        frame.addWidget(inner, 100)
        frame.addStretch(0 if not wide else 1)
        outer = QVBoxLayout(inner)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(14)
        if wide:
            outer.addStretch(1)
        title = QLabel(tr("처음이세요? 이렇게 시작해 보세요"))
        title.setObjectName("Title")
        title.setWordWrap(True)
        self._title = title
        sub = QLabel(tr("매크로는 컴퓨터가 대신 하는 반복 작업이에요. 셋 중 편한 방법 하나를 고르세요."))
        sub.setWordWrap(True)
        sub.setObjectName("Muted")
        self._sub = sub
        outer.addWidget(title)
        outer.addWidget(sub)
        outer.addSpacing(6)
        self.choices = QBoxLayout(QBoxLayout.LeftToRight if wide else QBoxLayout.TopToBottom)
        self.choices.setSpacing(12)
        self.c_example = _Choice("library", tr("예시에서 시작"),
                                 tr("바로 돌려 볼 수 있는 예시 3개를 넣습니다. 지금 있는 파일은 지우거나 바꾸지 않아요."),
                                 tr("예시 넣기"), True, t)
        self.c_record = _Choice("circle-dot", tr("녹화로 만들기"),
                                tr("평소처럼 마우스·키보드로 한 번 해 보이면 그대로 따라 합니다. 끝낼 때 F9."),
                                tr("녹화 시작"), False, t)
        self.c_ai = _Choice("sparkles", tr("AI에게 시키기"),
                            tr("할 일을 말로 적으면 AI가 매크로를 만들어 줍니다. 이 컴퓨터에 Claude 같은 AI 프로그램이 있어야 해요."),
                            tr("AI 연결하기"), False, t)
        for c, sig in ((self.c_example, self.examples), (self.c_record, self.record), (self.c_ai, self.ai)):
            c.button.clicked.connect(sig.emit)
            self.choices.addWidget(c, 1)
        outer.addLayout(self.choices)
        outer.addSpacing(4)
        foot = QHBoxLayout()
        hint = QLabel(tr("직접 하나씩 만들고 싶다면:"))
        hint.setObjectName("Muted")
        self._hint = hint
        self.new_btn = QPushButton(tr("빈 매크로 만들기"))
        self.new_btn.setMinimumWidth(0)
        self.new_btn.setFlat(True)
        self.new_btn.setCursor(Qt.PointingHandCursor)
        self.new_btn.setStyleSheet(f"QPushButton {{ color: {t['accent']}; background: transparent; padding: 0 4px; }}")
        self.new_btn.clicked.connect(self.new.emit)
        foot.addWidget(hint)
        foot.addWidget(self.new_btn)
        foot.addStretch(1)
        outer.addLayout(foot)
        outer.addStretch(1 if wide else 2)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply_scale()

    def _apply_scale(self):
        """창 폭에 맞춰 키운다: 1280 폭 기준 1배, 1920 쯤 1.35배, 최대 1.6배(안 B만)."""
        if not self.wide:
            return
        k = max(1.0, min(1.6, self.width() / 1350))
        if abs(k - self._scale) < 0.03:
            return
        self._scale = k
        t = self._t
        self._inner.setMaximumWidth(int(1100 * k))
        self._title.setStyleSheet(f"font-size: {int(t['font_title'] * k * 1.1)}px; font-weight: 600;")
        self._sub.setStyleSheet(f"color: {t['muted']}; font-size: {int(t['font_small'] * k * 1.05)}px;")
        self._hint.setStyleSheet(f"color: {t['muted']}; font-size: {int(t['font_small'] * k)}px;")
        self.new_btn.setStyleSheet(f"QPushButton {{ color: {t['accent']}; background: transparent; padding: 0 4px;"
                                   f" font-size: {int(t['font_small'] * k)}px; }}")
        self.choices.setSpacing(int(12 * k))
        for c in (self.c_example, self.c_record, self.c_ai):
            c.set_scale(k)

    def texts(self) -> list:
        return [w.text() for w in self.findChildren(QLabel) + self.findChildren(QPushButton) if w.text()]

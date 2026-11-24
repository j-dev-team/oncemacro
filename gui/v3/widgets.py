"""새 화면 공통 부품: 왼쪽 레일, 카드, 명령 단추, 목록 줄 그리기(매크로·스텝), 상태 배지."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (QFrame, QLabel, QSizePolicy, QStyle, QStyledItemDelegate, QToolButton, QTreeWidget,
                               QVBoxLayout, QWidget)

from .design import theme
from .design.assets import icon, pixmap


def T() -> dict:
    return theme.current()


def soft(col: str, a: int, bg: str) -> str:
    """색 col 을 바탕 bg 위에 a(0~255) 만큼 섞은 색."""
    c, b = QColor(col), QColor(bg)
    k = a / 255
    return QColor(int(c.red() * k + b.red() * (1 - k)), int(c.green() * k + b.green() * (1 - k)),
                  int(c.blue() * k + b.blue() * (1 - k))).name()


def card() -> QFrame:
    f = QFrame()
    f.setObjectName("Card")
    return f


def label(text: str, obj: str = "") -> QLabel:
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
    return lb


class RailButton(QWidget):
    """레일 항목: 아이콘(알약 표시) 위, 글자 아래. 숫자 배지."""
    clicked = Signal()

    def __init__(self, icon_name: str, text: str, parent=None):
        super().__init__(parent)
        self.icon_name, self.text, self.on, self.badge = icon_name, text, False, 0
        self.setFixedSize(76, 60)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(text)
        self.setAccessibleName(text)
        self._hover = False

    def set_badge(self, n: int):
        self.badge = n
        self.update()

    def set_on(self, on: bool):
        self.on = on
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, e):
        t = T()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pill = QRectF((self.width() - 56) / 2, 4, 56, 30)
        if self.on or self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t["accent_soft"] if self.on else t["hover"]))
            p.drawRoundedRect(pill, 15, 15)
        col = t["text"] if self.on else t["muted"]
        p.drawPixmap(int(pill.center().x() - 10), int(pill.center().y() - 10), pixmap(self.icon_name, col, 20))
        f = QFont(self.font())
        f.setPixelSize(max(11, t["font_small"] - 1))
        f.setWeight(QFont.DemiBold if self.on else QFont.Normal)
        p.setFont(f)
        p.setPen(QColor(col))
        p.drawText(QRectF(0, 37, self.width(), 20), Qt.AlignCenter | Qt.TextSingleLine,
                   p.fontMetrics().elidedText(self.text, Qt.ElideRight, self.width() - 4))
        if self.badge:
            f.setPixelSize(10)
            f.setWeight(QFont.Bold)
            p.setFont(f)
            txt = str(self.badge) if self.badge < 100 else "99+"
            w = max(18, p.fontMetrics().horizontalAdvance(txt) + 8)
            br = QRectF(pill.right() - 14, 0, w, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t["bad"]))
            p.drawRoundedRect(br, 9, 9)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(br, Qt.AlignCenter, txt)
        p.end()


class NavRail(QFrame):
    """왼쪽 레일. items: [(키, 아이콘, 글자)], bottom: 아래쪽 항목."""
    triggered = Signal(str)

    def __init__(self, items, bottom, parent=None):
        super().__init__(parent)
        self.setObjectName("Nav")
        self.setFixedWidth(T()["nav_w"])
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 14, 4, 12)
        v.setSpacing(6)
        self.buttons = {}
        for key, ic, text in items:
            b = RailButton(ic, text)
            b.clicked.connect(lambda k=key: self.triggered.emit(k))
            v.addWidget(b, 0, Qt.AlignHCenter)
            self.buttons[key] = b
        v.addStretch(1)
        for key, ic, text in bottom:
            b = RailButton(ic, text)
            b.clicked.connect(lambda k=key: self.triggered.emit(k))
            v.addWidget(b, 0, Qt.AlignHCenter)
            self.buttons[key] = b

    def set_current(self, key: str):
        for k, b in self.buttons.items():
            b.set_on(k == key)


def command_button(action, primary: bool = False, text_beside: bool = True) -> QToolButton:
    """QAction 을 그대로 쓰는 명령 단추(사용 가능 여부·글자·말풍선이 동작과 함께 바뀜)."""
    b = QToolButton()
    b.setDefaultAction(action)
    b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if text_beside else Qt.ToolButtonIconOnly)
    b.setIconSize(QSize(18, 18))
    t = T()
    b.setFixedHeight(t["control_h"])
    b.setCursor(Qt.PointingHandCursor)
    if primary:
        b.setObjectName("PrimaryTool")
        b.setStyleSheet(f"QToolButton#PrimaryTool{{background:{t['accent']}; color:{t['on_accent']}; "
                        f"border-radius:{t['control_h'] // 2}px; padding:0 18px 0 14px; font-weight:600;}}"
                        f"QToolButton#PrimaryTool:hover{{background:{soft(t['accent'], 225, t['text'])};}}")
    return b


def separator() -> QFrame:
    s = QFrame()
    s.setFixedSize(1, 20)
    s.setStyleSheet(f"background:{T()['line']};")
    return s


def chip(p: QPainter, right: float, cy: float, text: str, fg: str, bg: str, radius: float = 10, mono=False) -> float:
    """오른쪽 끝(right)에서 왼쪽으로 칩을 그리고, 칩의 왼쪽 x 를 돌려준다."""
    f = QFont("Consolas" if mono else p.font().family())
    f.setPixelSize(11)
    f.setWeight(QFont.Normal if mono else QFont.DemiBold)
    p.setFont(f)
    w = p.fontMetrics().horizontalAdvance(text) + 16
    r = QRectF(right - w, cy - 10, w, 20)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(bg))
    p.drawRoundedRect(r, radius, radius)
    p.setPen(QColor(fg))
    p.drawText(r, Qt.AlignCenter, text)
    return r.left()


STATUS_KEY = {"ok": "ok", "running": "accent", "warn": "warn", "bad": "bad", "off": "muted"}
STATUS_ICON = {"ok": "check", "running": "play", "warn": "triangle-alert", "bad": "circle-alert", "off": "circle"}


class MacroRowDelegate(QStyledItemDelegate):
    """매크로 목록 한 줄. 아이템 역할: kind(macro/group/recent), name, 추가로 ROLE_META = {hot, last, status}."""

    def __init__(self, role_kind, role_name, role_meta, parent=None):
        super().__init__(parent)
        self.rk, self.rn, self.rm = role_kind, role_name, role_meta

    def sizeHint(self, opt, idx):
        t = T()
        kind = idx.data(self.rk)
        if kind in ("group", "recent", "parts"):     # 묶음 제목: 위에 숨 쉴 틈(첫 줄 빼고)을 두어 묶음끼리 떨어져 보이게
            first = not idx.parent().isValid() and idx.row() == 0
            return QSize(120, (36 if first else 48) if t["row_main"] >= 44 else (32 if first else 40))
        meta = idx.data(self.rm) or {}
        if t["row_main"] >= 44 and not meta.get("last"):   # 둘째 줄(기록)이 없는 줄은 낮게 → 한 화면에 더 많이
            return QSize(120, 36)
        return QSize(120, t["row_main"])

    def paint(self, p, opt, idx):
        t = T()
        kind = idx.data(self.rk)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(opt.rect).adjusted(2, 2, -6, -2)
        sel = bool(opt.state & QStyle.State_Selected)
        hov = bool(opt.state & QStyle.State_MouseOver)
        f = QFont(opt.font)
        if kind in ("group", "recent", "parts"):
            # 띠 배경은 트리(drawRow)가 줄 전체 폭으로 깐다 → 여기서는 아이콘·이름·개수만
            band = getattr(self.parent(), "group_band_rect", None)
            br = band(opt.rect, idx) if band else r
            meta = idx.data(self.rm) or {}
            x = r.left() + 4
            ic = "rotate-ccw-clock" if kind == "recent" else "folder"
            p.drawPixmap(int(x), int(br.center().y() - 8), pixmap(ic, t["text"], 16))
            x += 24
            right = r.right() - 10
            if meta.get("count") is not None:
                right = chip(p, right, br.center().y(), str(meta["count"]), t["muted"], t["surface"]) - 6
            f.setPixelSize(t["font_body"])
            f.setWeight(QFont.Bold)
            p.setFont(f)
            p.setPen(QColor(t["text"]))
            txt = idx.data(self.rn) if kind == "group" else (idx.data(Qt.DisplayRole) or "")
            txt = txt.replace("📁", "").replace("🕘", "").strip()
            p.drawText(QRectF(x, br.top(), right - x - 4, br.height()), Qt.AlignVCenter,
                       p.fontMetrics().elidedText(txt, Qt.ElideRight, int(right - x - 4)))
            p.restore()
            return
        meta = idx.data(self.rm) or {}
        part = idx.parent().isValid() and idx.parent().data(self.rk) == "macro"   # 다른 매크로가 불러 쓰는 하위 매크로
        if sel or hov:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t["accent_soft"] if sel else t["hover"]))
            p.drawRoundedRect(r, t["radius_s"] + 2, t["radius_s"] + 2)
            if sel:                                      # 고른 줄: 왼쪽 강조 막대(색만이 아니라 모양으로도)
                p.setBrush(QColor(t["accent"]))
                p.drawRoundedRect(QRectF(r.left(), r.top() + 8, 3, r.height() - 16), 1.5, 1.5)
        st = meta.get("status", "off")
        col = t[STATUS_KEY.get(st, "muted")]
        x = r.left() + 12
        p.drawPixmap(int(x), int(r.center().y() - 9), pixmap(STATUS_ICON.get(st, "circle"), col, 18))
        x += 30
        right = r.right() - 10
        stt = meta.get("status_text")
        if stt and st != "off" or (stt and t["row_main"] >= 44):
            right = chip(p, right, r.center().y(), stt, col, soft(col, 34, t["surface"])) - 6
        if meta.get("hot"):
            right = chip(p, right, r.center().y(), meta["hot"], t["muted"], t["bg"], radius=5, mono=True) - 6
        name = idx.data(self.rn) or ""
        f.setPixelSize(t["font_body"])
        # 최상위 매크로는 굵게, 불러 쓰는 하위 매크로는 보통 굵기 → 줄기와 가지가 갈려 보임
        f.setWeight(QFont.Bold if meta.get("running") else (QFont.Normal if part else QFont.DemiBold))
        p.setFont(f)
        p.setPen(QColor(t["text"]))
        avail = right - x - 4
        two = t["row_main"] >= 44 and meta.get("last")
        nm = p.fontMetrics().elidedText(name, Qt.ElideRight, int(avail))
        if two:
            p.drawText(QRectF(x, r.top() + 3, avail, r.height() / 2), Qt.AlignBottom, nm)
            f.setPixelSize(t["font_small"])
            f.setWeight(QFont.Normal)
            p.setFont(f)
            p.setPen(QColor(t["muted"]))
            p.drawText(QRectF(x, r.center().y() + 2, avail, r.height() / 2 - 3), Qt.AlignTop,
                       p.fontMetrics().elidedText(meta["last"], Qt.ElideRight, int(avail)))
        else:
            p.drawText(QRectF(x, r.top(), avail, r.height()), Qt.AlignVCenter, nm)
        p.restore()


STEP_NUM_ROLE = Qt.UserRole + 40   # 스텝 번호(같은 단계 안에서 1부터)


class StepRowDelegate(QStyledItemDelegate):
    """스텝 미리 보기 줄: 아이콘 · 굵은 이름 · 흐린 설명(첫 ':' 기준) · 결과 칸."""

    def __init__(self, run_role=None, parent=None, editor: bool = False):
        super().__init__(parent)
        self.editor = editor            # 편집기: 줄 높이 = 촘촘함 값 그대로, 오류 스텝은 빨간 글자

    def sizeHint(self, opt, idx):
        t = T()
        return QSize(100, t["row_steps"] if self.editor else max(24, t["row_steps"] - 4))

    def paint(self, p, opt, idx):
        t = T()
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(opt.rect)
        bg = idx.data(Qt.BackgroundRole)
        sel = bool(opt.state & QStyle.State_Selected)
        if bg is not None and getattr(bg, "style", lambda: 0)() != Qt.NoBrush:
            p.fillRect(r, QColor(t["run_bg"]))
            if idx.column() == 0:
                p.fillRect(QRectF(r.left(), r.top(), 3, r.height()), QColor(t["accent"]))
        elif sel:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t["sel"]))
            p.drawRoundedRect(r.adjusted(0, 1, 0, -1), t["radius_s"], t["radius_s"])
        text = idx.data(Qt.DisplayRole) or ""
        f = QFont(opt.font)
        f.setPixelSize(t["font_body"] - 1)
        if idx.column() == 0:
            x = r.left() + 6
            num = idx.data(STEP_NUM_ROLE)
            if num is not None:
                fn = QFont(opt.font)
                fn.setPixelSize(t["font_small"])
                p.setFont(fn)
                p.setPen(QColor(t["muted"]))
                nw = max(22, p.fontMetrics().horizontalAdvance(str(num)) + 6)
                p.drawText(QRectF(x, r.top(), nw - 6, r.height()), Qt.AlignVCenter | Qt.AlignRight, str(num))
                x += nw
            ic = idx.data(Qt.DecorationRole)
            if ic is not None and not ic.isNull():
                ic.paint(p, int(x), int(r.center().y() - 8), 16, 16)
                x += 24
            fg = idx.data(Qt.ForegroundRole)
            fgn = fg.color().name().lower() if fg is not None else ""
            name_col = {"#c62828": t["bad"], "#777777": t["muted"]}.get(fgn, t["text"])
            is_branch = ic is None or ic.isNull()
            if ":" in text and not is_branch:
                a, b = text.split(":", 1)
                f.setWeight(QFont.DemiBold)
                p.setFont(f)
                p.setPen(QColor(name_col))
                p.drawText(QRectF(x, r.top(), r.right() - x, r.height()), Qt.AlignVCenter, a)
                x += p.fontMetrics().horizontalAdvance(a) + 8
                f.setWeight(QFont.Normal)
                p.setFont(f)
                p.setPen(QColor(t["muted"]))
                p.drawText(QRectF(x, r.top(), r.right() - x - 4, r.height()), Qt.AlignVCenter,
                           p.fontMetrics().elidedText(b.strip(), Qt.ElideRight, int(r.right() - x - 4)))
            else:
                f.setWeight(QFont.DemiBold if is_branch else QFont.Normal)
                p.setFont(f)
                p.setPen(QColor(t["accent"] if is_branch else name_col))
                p.drawText(QRectF(x, r.top(), r.right() - x - 4, r.height()), Qt.AlignVCenter,
                           p.fontMetrics().elidedText(text, Qt.ElideRight, int(r.right() - x - 4)))
        else:
            f.setPixelSize(t["font_small"])
            p.setFont(f)
            fg = idx.data(Qt.ForegroundRole)
            col = t["muted"]
            if fg is not None:
                c = fg.color().name().lower()
                col = {"#2e7d32": t["ok"], "#8d6e00": t["warn"], "#c62828": t["bad"]}.get(c, t["muted"])
            p.setPen(QColor(col))
            p.drawText(r.adjusted(6, 0, -6, 0), Qt.AlignVCenter, text)
        p.restore()


class ChevronTree(QTreeWidget):
    """줄 그리기(델리게이트)가 고른 줄 표시를 맡는 트리. 접기 화살표만 직접 그려 들여쓰기 칸이 색칠되지 않게."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("QTreeView::item:selected, QTreeView::item:hover, QTreeView::branch:selected"
                           " { background: transparent; }")

    def drawBranches(self, painter, rect, index):
        if not self.model().hasChildren(index):
            return
        name = "chevron-down" if self.isExpanded(index) else "chevron-right"
        x = rect.right() - self.indentation() + (self.indentation() - 14) // 2 + 1
        painter.drawPixmap(int(x), int(rect.center().y() - 7), pixmap(name, T()["muted"], 14))

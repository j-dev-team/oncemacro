"""메모리 매크로: '값 지켜보기' 창 — 저장한 값을 정한 간격으로 읽어 기록·그래프·시간당 변화를 보여 주고,
조건에 닿으면 매크로 실행·알림. 규칙은 memory/watch.json, 실제 지켜보기는 주 창의 타이머가 한다(이 창을 닫아도 계속)."""
from __future__ import annotations

import time

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QDialog, QDoubleSpinBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from gui.v2.i18n import tr

OPS = [("", "조건 없음(기록만)"), ("ge", "이상이 되면"), ("le", "이하가 되면"), ("gt", "보다 커지면"), ("lt", "보다 작아지면"),
       ("eq", "와 같아지면"), ("changed", "바뀌면")]


class Spark(QWidget):
    """최근 기록 선 그래프."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.points = []
        self.setMinimumHeight(120)

    def set_points(self, pts):
        self.points = [(t_, v) for t_, v in pts if isinstance(v, (int, float))]
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(0, 0, 0, 0))
        if len(self.points) < 2:
            p.setPen(QColor("#888"))
            p.drawText(self.rect(), Qt.AlignCenter, tr("기록이 아직 없어요"))
            return
        ts = [t_ for t_, _ in self.points]
        vs = [v for _, v in self.points]
        t0, t1 = min(ts), max(ts)
        v0, v1 = min(vs), max(vs)
        if v1 == v0:
            v1 = v0 + 1
        pad = 8
        pts = [QPointF(pad + (t_ - t0) / max(1e-9, t1 - t0) * (w - 2 * pad),
                       h - pad - (v - v0) / (v1 - v0) * (h - 2 * pad)) for t_, v in self.points]
        p.setPen(QPen(QColor("#4f5bd5"), 2))
        for a, b in zip(pts, pts[1:]):
            p.drawLine(a, b)
        p.setPen(QColor("#666"))
        p.drawText(pad, 14, f"{v1:g}")
        p.drawText(pad, h - 2, f"{v0:g}")


class MemoryWatchDialog(QDialog):
    def __init__(self, parent=None, macro_names=lambda: []):
        super().__init__(parent)
        from engine import memory as mm
        self.setWindowTitle(tr("값 지켜보기 — 메모리 매크로"))
        self.resize(720, 560)
        v = QVBoxLayout(self)
        tip = QLabel(tr("저장한 값을 정한 간격으로 읽어 기록하고, 조건에 닿으면 매크로를 실행하거나 알립니다. 이 창을 닫아도 프로그램이 켜져 있는 동안 계속 지켜봐요."))
        tip.setWordWrap(True)
        tip.setObjectName("Muted")
        v.addWidget(tip)
        row = QHBoxLayout()
        self.name = QComboBox()
        self.name.addItems(sorted(mm.load_values()))
        self.every = QDoubleSpinBox()
        self.every.setRange(1, 3600)
        self.every.setValue(5)
        self.every.setSuffix(tr(" 초마다"))
        self.op = QComboBox()
        for k, lab in OPS:
            self.op.addItem(tr(lab), k)
        self.val = QLineEdit()
        self.val.setPlaceholderText(tr("기준 값"))
        self.macro = QComboBox()
        self.macro.addItem(tr("(알림만)"), "")
        for n in macro_names():
            self.macro.addItem(n, n)
        add = QPushButton(tr("추가"))
        add.clicked.connect(self.add_rule)
        for w in (self.name, self.every, self.op, self.val, self.macro, add):
            row.addWidget(w)
        v.addLayout(row)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([tr("값"), tr("간격"), tr("조건 → 할 일"), tr("지금 값"), tr("시간당 변화")])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.currentCellChanged.connect(lambda *_: self.refresh_graph())
        v.addWidget(self.table, 1)
        row = QHBoxLayout()
        for lab, fn in ((tr("켜기/끄기"), self.toggle_rule), (tr("지우기"), self.delete_rule)):
            b = QPushButton(lab)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(QLabel(tr("최근 1시간 그래프")))
        self.graph = Spark()
        v.addWidget(self.graph)
        self.fill()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_live)
        self.timer.start(2000)

    def _rules(self):
        from engine import memwatch as mw
        return mw.load_rules()

    def fill(self):
        rules = self._rules()
        self.table.setRowCount(len(rules))
        for i, r in enumerate(rules):
            w = r.get("when") or {}
            cond = dict(OPS).get(w.get("op", ""), "")
            txt = (f"{w.get('value', '')} {tr(cond)}" if w.get("op") and w.get("op") != "changed" else tr(cond)) if w.get("op") else tr("기록만")
            do = (r.get("do") or {}).get("macro") or tr("알림")
            cells = (r["name"] + ("" if r.get("on", True) else tr(" (꺼짐)")), f"{r.get('every', 5):g}s",
                     txt + (f" → {do}" if w.get("op") else ""), "", "")
            for c, t_ in enumerate(cells):
                self.table.setItem(i, c, QTableWidgetItem(t_))
        self.refresh_live()

    def refresh_live(self):
        from engine import memwatch as mw
        for i, r in enumerate(self._rules()):
            pts = mw.history(r["name"], since=time.time() - 3600)
            if pts and self.table.item(i, 3) is not None:
                self.table.item(i, 3).setText(str(pts[-1][1]))
                ph = mw.per_hour(pts)
                self.table.item(i, 4).setText("-" if ph is None else f"{ph:+,.0f}/h")
        self.refresh_graph()

    def refresh_graph(self):
        from engine import memwatch as mw
        rules = self._rules()
        i = self.table.currentRow()
        if 0 <= i < len(rules):
            self.graph.set_points(mw.history(rules[i]["name"], since=time.time() - 3600))

    def add_rule(self):
        from engine import memwatch as mw
        name = self.name.currentText().strip()
        if not name:
            QMessageBox.information(self, tr("값 지켜보기"), tr("먼저 '값 찾기'에서 값을 찾아 이름 붙여 저장하세요"))
            return
        rule = {"name": name, "every": self.every.value(), "on": True}
        op = self.op.currentData()
        if op:
            t_ = self.val.text().strip().replace(",", "")
            if op != "changed" and not t_:
                QMessageBox.information(self, tr("값 지켜보기"), tr("기준 값을 넣으세요"))
                return
            rule["when"] = {"op": op, "value": (float(t_) if "." in t_ else int(t_)) if t_ else None}
            rule["do"] = {"macro": self.macro.currentData() or None, "notify": True}
        rules = [r for r in mw.load_rules() if r["name"] != name] + [rule]
        mw.save_rules(rules)
        self.fill()

    def _sel(self):
        i = self.table.currentRow()
        rules = self._rules()
        return (i, rules) if 0 <= i < len(rules) else (None, rules)

    def toggle_rule(self):
        from engine import memwatch as mw
        i, rules = self._sel()
        if i is None:
            return
        rules[i]["on"] = not rules[i].get("on", True)
        mw.save_rules(rules)
        self.fill()

    def delete_rule(self):
        from engine import memwatch as mw
        i, rules = self._sel()
        if i is None:
            return
        rules.pop(i)
        mw.save_rules(rules)
        self.fill()

    def done(self, r):
        self.timer.stop()
        super().done(r)

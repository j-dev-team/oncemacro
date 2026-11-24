"""매크로 실행 중 '사람에게 묻기' 창. 실행 스레드가 기다리는 동안 화면 스레드에서 띄운다.

kind: input(글) · confirm(예/아니) · choose(목록에서) · file(파일 고르기) · folder(폴더 고르기)
timeout(초)이 있으면 남은 시간을 보여 주고, 지나면 'timeout' 으로 닫는다(엔진이 기본값을 씀).
돌려줌: ("ok", 값) / ("cancel", None) / ("timeout", None)
"""
from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout)

from gui.v2.i18n import tr


class AskDialog(QDialog):
    def __init__(self, req: dict, parent=None):
        super().__init__(parent)
        self.req = req
        self.kind = req.get("kind", "input")
        self.status = "cancel"
        self.value = None
        self.setWindowTitle(str(req.get("title") or tr("매크로가 묻습니다")))
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setMinimumWidth(420)
        v = QVBoxLayout(self)
        msg = QLabel(str(req.get("message") or ""))
        msg.setWordWrap(True)
        msg.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(msg)
        d = req.get("default")
        self.edit = None
        self.combo = None
        if self.kind == "input":
            self.edit = QLineEdit("" if d is None else str(d))
            v.addWidget(self.edit)
        elif self.kind == "choose":
            self.combo = QComboBox()
            self.combo.addItems(req.get("options") or [])
            if d is not None and self.combo.findText(str(d)) >= 0:
                self.combo.setCurrentIndex(self.combo.findText(str(d)))
            v.addWidget(self.combo)
        elif self.kind in ("file", "folder"):
            row = QHBoxLayout()
            self.edit = QLineEdit("" if d is None else str(d))
            b = QPushButton(tr("찾아보기"))
            b.setMinimumWidth(0)
            b.clicked.connect(self._browse)
            row.addWidget(self.edit, 1)
            row.addWidget(b)
            v.addLayout(row)
        self.left = QLabel()
        self.left.setObjectName("Muted")
        v.addWidget(self.left)
        if self.kind == "confirm":
            bb = QDialogButtonBox()
            yes = bb.addButton(tr("예"), QDialogButtonBox.AcceptRole)
            no = bb.addButton(tr("아니요"), QDialogButtonBox.RejectRole)
            yes.clicked.connect(lambda: self._done("ok", True))
            no.clicked.connect(lambda: self._done("ok", False))
            stop = bb.addButton(tr("매크로 멈추기"), QDialogButtonBox.DestructiveRole)
            stop.clicked.connect(lambda: self._done("cancel", None))
        else:
            bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            bb.accepted.connect(self._ok)
            bb.rejected.connect(lambda: self._done("cancel", None))
        v.addWidget(bb)
        self._remain = None
        to = req.get("timeout")
        if isinstance(to, (int, float)) and to > 0:
            self._remain = int(to)
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._tick)
            self._timer.start(1000)
            self._show_left()

    def _show_left(self):
        if self._remain is not None:
            self.left.setText(tr("{n}초 안에 답이 없으면 기본값으로 계속합니다.").format(n=self._remain))

    def _tick(self):
        self._remain -= 1
        if self._remain <= 0:
            self._done("timeout", None)
        else:
            self._show_left()

    def _browse(self):
        if self.kind == "folder":
            p = QFileDialog.getExistingDirectory(self, tr("폴더 고르기"), self.edit.text())
        else:
            p, _ = QFileDialog.getOpenFileName(self, tr("파일 고르기"), self.edit.text())
        if p:
            self.edit.setText(p.replace("/", "\\"))

    def _ok(self):
        if self.kind == "choose":
            self._done("ok", self.combo.currentText())
        else:
            self._done("ok", self.edit.text() if self.edit is not None else "")

    def _done(self, status: str, value):
        self.status, self.value = status, value
        self.accept() if status == "ok" else self.reject()

    def closeEvent(self, e):
        if self.status not in ("ok", "timeout"):
            self.status = "cancel"
        super().closeEvent(e)


def ask(parent, req: dict) -> Tuple[str, Optional[object]]:
    d = AskDialog(req, parent)
    d.exec()
    return d.status, d.value

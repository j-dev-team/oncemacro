"""설정 → 메일 계정: 메일 서버 직접 연결(IMAP·SMTP) 계정을 사용자가 직접 넣는 창.

- 서버 주소·아이디는 <자료 폴더>/settings/mail_accounts.json 에, 비밀번호는 윈도우 자격 증명에만 둔다.
- 비밀번호는 사용자가 이 창에서 직접 넣는다(매크로·AI가 넣지 않음). 다시 보여 주지 않는다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QMessageBox, QPushButton, QSpinBox, QVBoxLayout)

from gui.v2.i18n import tr


class MailAccountsDialog(QDialog):
    def __init__(self, root: str, parent=None, cred=None):
        super().__init__(parent)
        from engine import mailserver
        self.ms = mailserver
        self.root = root
        if cred is None:
            from engine import wincred as cred
        self.cred = cred
        self.setWindowTitle(tr("메일 계정"))
        self.resize(640, 420)
        v = QVBoxLayout(self)
        note = QLabel(tr("메일 서버에 직접 연결할 계정입니다. 비밀번호는 이 컴퓨터의 윈도우 자격 증명에만 저장되고, "
                         "매크로·설정 파일·기록에는 남지 않아요. 네이버·다음·구글은 메일 설정에서 IMAP 을 켜고 '앱 비밀번호'를 쓰세요."))
        note.setWordWrap(True)
        note.setObjectName("Muted")
        v.addWidget(note)
        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.setMaximumWidth(180)
        self.list.currentTextChanged.connect(self._load)
        row.addWidget(self.list)
        f = QFormLayout()
        self.name = QLineEdit()
        self.preset = QComboBox()
        self.preset.addItem(tr("직접 넣기"), "")
        for k, lab in (("naver", "네이버"), ("daum", "다음"), ("nate", "네이트"), ("gmail", "구글(지메일)")):
            self.preset.addItem(tr(lab), k)
        self.preset.currentIndexChanged.connect(self._apply_preset)
        self.imap_host, self.smtp_host = QLineEdit(), QLineEdit()
        self.imap_port, self.smtp_port = QSpinBox(), QSpinBox()
        for s in (self.imap_port, self.smtp_port):
            s.setRange(1, 65535)
        self.imap_port.setValue(993)
        self.smtp_port.setValue(465)
        self.user = QLineEdit()
        self.ssl = QCheckBox(tr("암호화 연결(SSL)"))
        self.ssl.setChecked(True)
        self.drafts = QLineEdit()
        self.drafts.setPlaceholderText(tr("임시 보관함 폴더 이름(비우면 Drafts)"))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText(tr("바꿀 때만 넣으세요(저장된 비밀번호는 보여 주지 않음)"))
        f.addRow(tr("계정 이름"), self.name)
        f.addRow(tr("메일 서비스"), self.preset)
        f.addRow(tr("받는 서버(IMAP)"), self._pair(self.imap_host, self.imap_port))
        f.addRow(tr("보내는 서버(SMTP)"), self._pair(self.smtp_host, self.smtp_port))
        f.addRow(tr("아이디(메일 주소)"), self.user)
        f.addRow("", self.ssl)
        f.addRow(tr("임시 보관함"), self.drafts)
        f.addRow(tr("비밀번호"), self.password)
        row.addLayout(f, 1)
        v.addLayout(row)
        btns = QHBoxLayout()
        new = QPushButton(tr("새 계정"))
        save = QPushButton(tr("저장"))
        save.setObjectName("Primary")
        rm = QPushButton(tr("삭제"))
        new.clicked.connect(self._new)
        save.clicked.connect(self.save)
        rm.clicked.connect(self._remove)
        for b in (new, save, rm):
            b.setMinimumWidth(0)
            btns.addWidget(b)
        btns.addStretch(1)
        v.addLayout(btns)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._refresh()

    @staticmethod
    def _pair(a, b):
        h = QHBoxLayout()
        h.addWidget(a, 1)
        h.addWidget(b)
        return h

    def _refresh(self, select: str = ""):
        self.list.clear()
        for n in sorted(self.ms.load_accounts(self.root)):
            self.list.addItem(n)
        items = self.list.findItems(select, Qt.MatchExactly) if select else []
        if items:
            self.list.setCurrentItem(items[0])

    def _apply_preset(self, *_):
        k = self.preset.currentData()
        p = self.ms.PRESETS.get(k)
        if p:
            self.imap_host.setText(p["imap_host"])
            self.imap_port.setValue(p["imap_port"])
            self.smtp_host.setText(p["smtp_host"])
            self.smtp_port.setValue(p["smtp_port"])
            self.ssl.setChecked(p["ssl"])

    def _new(self):
        self.list.clearSelection()
        for e in (self.name, self.imap_host, self.smtp_host, self.user, self.drafts, self.password):
            e.clear()

    def _load(self, name: str):
        c = self.ms.load_accounts(self.root).get(name)
        if not c:
            return
        self.name.setText(name)
        self.imap_host.setText(c.get("imap_host", ""))
        self.imap_port.setValue(int(c.get("imap_port", 993)))
        self.smtp_host.setText(c.get("smtp_host", ""))
        self.smtp_port.setValue(int(c.get("smtp_port", 465)))
        self.user.setText(c.get("user", ""))
        self.ssl.setChecked(bool(c.get("ssl", True)))
        self.drafts.setText(c.get("drafts", ""))
        self.password.clear()

    def save(self) -> bool:
        name = self.name.text().strip()
        if not name or not self.imap_host.text().strip() or not self.user.text().strip():
            QMessageBox.warning(self, tr("메일 계정"), tr("계정 이름·받는 서버·아이디를 넣어 주세요."))
            return False
        cfg = {"imap_host": self.imap_host.text().strip(), "imap_port": self.imap_port.value(),
               "smtp_host": self.smtp_host.text().strip(), "smtp_port": self.smtp_port.value(),
               "user": self.user.text().strip(), "ssl": self.ssl.isChecked()}
        if self.drafts.text().strip():
            cfg["drafts"] = self.drafts.text().strip()
        self.ms.save_account(name, cfg, self.root)
        pw = self.password.text()
        if pw:
            try:
                self.cred.save(name, cfg["user"], pw)
            except OSError as e:
                QMessageBox.warning(self, tr("메일 계정"), tr("비밀번호를 저장하지 못했습니다: {e}").format(e=e))
                return False
            self.password.clear()
        self._refresh(name)
        return True

    def _remove(self):
        it = self.list.currentItem()
        if it is None:
            return
        name = it.text()
        if QMessageBox.question(self, tr("메일 계정"), tr("'{name}' 계정을 지울까요? (저장된 비밀번호도 지웁니다)").format(name=name),
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        acc = self.ms.load_accounts(self.root)
        acc.pop(name, None)
        import json
        import os
        p = self.ms.accounts_path(self.root)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(acc, fh, ensure_ascii=False, indent=1)
        try:
            self.cred.delete(name)
        except OSError:
            pass
        self._new()
        self._refresh()

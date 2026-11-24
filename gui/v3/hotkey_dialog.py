"""새 화면(PySide6) 핫키 정하기 창. 옛 화면 것(gui/dialogs, PyQt5)을 쓰면 실행 묶음에서 죽어서 따로 만든다(11-18).

값 모양은 옛 것과 같다: 'f9', 'ctrl+f1', 'numpad_*' (조합키는 알파벳 순 + 일반키).
정한 핫키는 프로그램이 뒤에 있어도(다른 창이 앞이어도) 먹는다(전역 핫키)."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout)

from gui.v2.i18n import tr

PRESETS = [("F1", "f1"), ("F2", "f2"), ("F3", "f3"), ("F4", "f4"), ("F6", "f6"), ("F7", "f7"), ("F8", "f8"),
           ("F10", "f10"), ("F11", "f11"),
           ("넘버패드 *", "numpad_*"), ("넘버패드 +", "numpad_+"), ("넘버패드 -", "numpad_-"), ("넘버패드 /", "numpad_/"),
           ("넘버패드 0", "numpad_0"), ("넘버패드 1", "numpad_1"), ("넘버패드 2", "numpad_2"), ("넘버패드 3", "numpad_3"),
           ("Ctrl+F1", "ctrl+f1"), ("Ctrl+F2", "ctrl+f2"), ("Alt+F1", "alt+f1"), ("Alt+F2", "alt+f2"),
           ("Ctrl+Shift+F1", "ctrl+shift+f1"), ("Ctrl+Alt+F1", "ctrl+alt+f1")]
# 프로그램이 이미 쓰는 키(겹치면 헷갈림)
RESERVED = {"ctrl+shift+f12": "Ctrl+Shift+F12 = 비상 정지", "f5": "F5 = 고른 매크로 실행(창이 앞에 있을 때)", "f9": "F9 = 녹화 시작(창이 앞에 있을 때)·끝내기"}
_NUMPAD_VK = {96: "numpad_0", 97: "numpad_1", 98: "numpad_2", 99: "numpad_3", 100: "numpad_4", 101: "numpad_5",
              102: "numpad_6", 103: "numpad_7", 104: "numpad_8", 105: "numpad_9", 106: "numpad_*", 107: "numpad_+",
              109: "numpad_-", 110: "numpad_.", 111: "numpad_/"}
_KEYS = {getattr(Qt, f"Key_F{i}"): f"f{i}" for i in range(1, 13)}
_KEYS.update({Qt.Key_Escape: "esc", Qt.Key_Tab: "tab", Qt.Key_Space: "space", Qt.Key_Return: "enter",
              Qt.Key_Enter: "enter", Qt.Key_Backspace: "backspace", Qt.Key_Delete: "delete", Qt.Key_Insert: "insert",
              Qt.Key_Home: "home", Qt.Key_End: "end", Qt.Key_PageUp: "page_up", Qt.Key_PageDown: "page_down",
              Qt.Key_Up: "up", Qt.Key_Down: "down", Qt.Key_Left: "left", Qt.Key_Right: "right"})


def display(hk: str) -> str:
    if not hk:
        return ""
    out = []
    import re
    for p in re.split(r"\+(?=.)", hk):            # 'numpad_+' 의 + 는 나누지 않음
        if p.startswith("numpad_"):
            out.append(tr("넘버패드 ") + p[7:].upper())
        elif p in ("ctrl", "alt", "shift"):
            out.append(p.capitalize())
        elif p == "cmd":
            out.append("Win")
        else:
            out.append(p.upper() if len(p) <= 3 else p.replace("_", " ").title())
    return "+".join(out)


def combo_from_event(key: int, mods, vk: int, text: str) -> Optional[str]:
    """키 누름 → 핫키 글자. 수정키만 누른 것이면 None."""
    if key in (Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta):
        return None
    parts = []
    if mods & Qt.ControlModifier:
        parts.append("ctrl")
    if mods & Qt.AltModifier:
        parts.append("alt")
    if mods & Qt.ShiftModifier:
        parts.append("shift")
    if mods & Qt.MetaModifier:
        parts.append("cmd")
    if vk in _NUMPAD_VK:
        base = _NUMPAD_VK[vk]
    elif key in _KEYS:
        base = _KEYS[key]
    else:
        t = (text or "").lower()
        if not (t and t.isprintable() and t.strip()):
            return None
        base = t
    return "+".join(sorted(parts) + [base])


class HotkeyDialog(QDialog):
    """옛 것과 같은 쓰임: HotkeyDialog(parent, 제목, 지금 핫키) → exec() → get_hotkey()."""

    def __init__(self, parent=None, title: str = "", current_hotkey: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title or tr("핫키 정하기"))
        self.setModal(True)
        self.captured = current_hotkey or ""
        self.capturing = False
        lay = QVBoxLayout(self)
        tip = QLabel(tr("[누르기]를 누른 뒤 쓸 키를 누르세요. 한 키(F6)나 조합(Ctrl+F1)도 됩니다.\n"
                        "정한 핫키는 이 프로그램이 뒤에 있어도(다른 창을 쓰는 중에도) 먹습니다."))
        tip.setWordWrap(True)
        lay.addWidget(tip)
        row = QHBoxLayout()
        self.edit = QLineEdit(display(self.captured))
        self.edit.setReadOnly(True)
        self.edit.setPlaceholderText(tr("없음"))
        row.addWidget(self.edit, 1)
        self.capture_btn = QPushButton(tr("누르기"))
        self.capture_btn.clicked.connect(self.start_capture)
        row.addWidget(self.capture_btn)
        clear = QPushButton(tr("지우기"))
        clear.clicked.connect(lambda: self.set_hotkey(""))
        row.addWidget(clear)
        lay.addLayout(row)
        self.preset = QComboBox()
        self.preset.addItem(tr("자주 쓰는 키에서 고르기"), "")
        for lab, val in PRESETS:
            self.preset.addItem(tr(lab), val)
        self.preset.currentIndexChanged.connect(lambda _=0: self.preset.currentData() and self.set_hotkey(self.preset.currentData()))
        lay.addWidget(self.preset)
        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        self.warn.setObjectName("Muted")
        lay.addWidget(self.warn)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("확인"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("취소"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._update_warn()

    def start_capture(self):
        self.capturing = True
        self.edit.setText(tr("키를 누르세요…"))
        self.capture_btn.setEnabled(False)
        self.setFocus()

    def keyPressEvent(self, ev):
        if not self.capturing:
            return super().keyPressEvent(ev)
        hk = combo_from_event(ev.key(), ev.modifiers(), ev.nativeVirtualKey(), ev.text())
        if hk is None:
            return
        self.capturing = False
        self.capture_btn.setEnabled(True)
        self.set_hotkey(hk)

    def set_hotkey(self, hk: str):
        self.captured = hk or ""
        self.edit.setText(display(self.captured))
        self._update_warn()

    def _update_warn(self):
        w = RESERVED.get(self.captured)
        self.warn.setText(tr("이 키는 프로그램이 이미 씀: ") + tr(w) if w else "")

    def get_hotkey(self) -> str:
        return self.captured


class _KeyRow:
    """한 줄: 라벨 · 지금 키 칸 · [누르기] · 고르기 · [지우기] · 겹침 알림."""

    def __init__(self, dlg, label: str, value: str):
        self.dlg = dlg
        self.value = value or ""
        self.label = QLabel(label)
        self.edit = QLineEdit(display(self.value))
        self.edit.setReadOnly(True)
        self.edit.setPlaceholderText(tr("없음"))
        self.capture = QPushButton(tr("누르기"))
        self.capture.clicked.connect(lambda: dlg._start(self))
        self.preset = QComboBox()
        self.preset.addItem(tr("고르기"), "")
        for lab, val in PRESETS:
            self.preset.addItem(tr(lab), val)
        self.preset.currentIndexChanged.connect(lambda _=0: self.preset.currentData() and self.set(self.preset.currentData()))
        self.clear = QPushButton(tr("지우기"))
        self.clear.clicked.connect(lambda: self.set(""))
        self.warn = QLabel("")
        self.warn.setObjectName("Muted")
        self.warn.setWordWrap(True)

    def widgets(self):
        return [self.label, self.edit, self.capture, self.preset, self.clear]

    def set(self, hk: str):
        self.value = hk or ""
        self.edit.setText(display(self.value))
        self.dlg._changed()

    def set_enabled(self, on: bool):
        for w in (self.edit, self.capture, self.preset, self.clear):
            w.setEnabled(on)


class HotkeyPairDialog(QDialog):
    """한 창에서 실행 키·정지 키를 함께 정함. '같은 키로 켜고 끄기'를 켜면 정지 키가 실행 키를 따라감.
    others: {다른 매크로 이름: (실행, 정지)} — 겹치면 그 줄 옆에 알림."""

    def __init__(self, parent=None, macro: str = "", run: str = "", stop: str = "", others=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QCheckBox, QGridLayout
        self.setWindowTitle(tr("핫키 정하기 — {name}").format(name=macro) if macro else tr("핫키 정하기"))
        self.setModal(True)
        self.others = {k: v for k, v in (others or {}).items() if k != macro}
        self.capturing: Optional[_KeyRow] = None
        lay = QVBoxLayout(self)
        tip = QLabel(tr("이 프로그램이 뒤에 있어도(다른 창을 쓰는 중에도) 먹는 키입니다."))
        tip.setWordWrap(True)
        lay.addWidget(tip)
        self.toggle = QCheckBox(tr("같은 키로 켜고 끄기"))
        self.toggle.setChecked(bool(run) and run == stop)
        lay.addWidget(self.toggle)
        grid = QGridLayout()
        self.run_row = _KeyRow(self, tr("실행 키"), run)
        self.stop_row = _KeyRow(self, tr("정지 키"), stop)
        for r, row in enumerate((self.run_row, self.stop_row)):
            for c, w in enumerate(row.widgets()):
                grid.addWidget(w, r * 2, c)
            grid.addWidget(row.warn, r * 2 + 1, 1, 1, 4)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("확인"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("취소"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.toggle.toggled.connect(lambda _=None: self._changed())
        self._changed()

    def _start(self, row: _KeyRow):
        self.capturing = row
        row.edit.setText(tr("키를 누르세요…"))
        row.capture.setEnabled(False)
        self.setFocus()

    def keyPressEvent(self, ev):
        if self.capturing is None:
            return super().keyPressEvent(ev)
        hk = combo_from_event(ev.key(), ev.modifiers(), ev.nativeVirtualKey(), ev.text())
        if hk is None:
            return
        row, self.capturing = self.capturing, None
        row.capture.setEnabled(True)
        row.set(hk)

    def _clash(self, hk: str) -> str:
        if not hk:
            return ""
        w = RESERVED.get(hk)
        if w:
            return tr("프로그램 단축키와 겹침: ") + tr(w)
        names = [n for n, (r, s) in self.others.items() if hk in (r, s)]
        return tr("다른 매크로와 겹침: {names}").format(names=", ".join(names)) if names else ""

    def _changed(self):
        same = self.toggle.isChecked()
        if same:
            self.stop_row.value = self.run_row.value
            self.stop_row.edit.setText(display(self.stop_row.value))
        self.stop_row.set_enabled(not same)
        for row in (self.run_row, self.stop_row):
            row.warn.setText(self._clash(row.value))
            row.warn.setVisible(bool(row.warn.text()))
        if not same and self.run_row.value and self.run_row.value == self.stop_row.value:
            self.stop_row.warn.setText(tr("실행 키와 같아요 — 같은 키로 켜고 끄려면 위 칸을 켜세요"))
            self.stop_row.warn.setVisible(True)

    def keys(self):
        run = self.run_row.value
        return run, (run if self.toggle.isChecked() else self.stop_row.value)

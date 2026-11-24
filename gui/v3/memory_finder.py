"""메모리 매크로: '값 찾기' 창(부가 기능, 혼자 하는 게임·보호 장치 없는 프로그램용).

① 프로그램 고르기 → ② 지금 값으로 처음 찾기(모르면 '모르는 값으로 시작') → ③ 값이 바뀐 뒤 다시 찾기로 좁히기
→ ④ 결과에서 골라 이름 붙여 저장 / 값 바꾸기 / 고정. 저장한 값 목록에서 실시간 값·고정 켜고 끄기.
찾기는 뒤에서(화면이 멈추지 않게) 돈다. 쓰기는 쓰기 권한으로 따로 붙는다.
"""
from __future__ import annotations

import threading
from typing import Optional

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDoubleSpinBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QMessageBox, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from gui.v2.i18n import tr

KIND_NAMES = [("auto", "자동(정수·실수 함께)"), ("int32", "정수(4바이트)"), ("int16", "정수(2바이트)"),
              ("int64", "정수(8바이트)"), ("float", "실수(float)"), ("double", "실수(double)"), ("uint8", "작은 수(1바이트)")]
NEXT_MODES = [("eq", "이 값과 같음"), ("increased", "커졌음"), ("decreased", "작아졌음"), ("changed", "바뀌었음"),
              ("unchanged", "안 바뀌었음"), ("inc_by", "이만큼 커졌음"), ("dec_by", "이만큼 작아졌음")]


def programs():
    """[(보이는 이름, pid, 실행 파일)] — 제목이 있는 창을 가진 프로그램."""
    import os
    from engine.win_window import list_windows
    me = os.getpid()
    seen, out = {me}, []                      # 이 프로그램 자신은 목록에서 뺌(처음 고른 값이 자기 자신이던 문제)
    for w in list_windows():
        if w.pid in seen or not w.title:
            continue
        seen.add(w.pid)
        out.append((f"{w.title}  ({w.process})", w.pid, w.process))
    try:                                      # 저장한 값이 있는 게임을 맨 위로(다시 켰을 때 바로 고르게)
        from engine import memory as mm
        known = {str(v.get("process")).lower() for v in mm.load_values().values() if v.get("process")}
        out.sort(key=lambda p: 0 if p[2].lower() in known else 1)
    except Exception:
        pass
    return out


def _parse_value(text: str):
    """찾을 값 글 → 숫자, 또는 범위 (최소, 최대). 비면 None. 못 읽으면 ValueError.
    '2.1k' 처럼 줄여 보이는 값은 그 반올림 범위(2050~2150), '2000~2200' 은 그 범위."""
    s = (text or "").replace(",", "").replace(" ", "").strip()
    if not s:
        return None
    if "~" in s:
        a, b = s.split("~", 1)
        lo, hi = float(a), float(b)
        return (min(lo, hi), max(lo, hi))
    mult = {"k": 1000, "m": 1000000, "만": 10000, "억": 100000000}.get(s[-1].lower())
    if mult:
        body = s[:-1]
        dec = len(body.split(".")[1]) if "." in body else 0
        half = 0.5 * (10 ** -dec) * mult
        c = float(body) * mult
        return (c - half, c + half)
    return _num(s)


def _num(text: str):
    t_ = (text or "").replace(",", "").strip()
    if not t_:
        return None
    v = float(t_)
    return int(v) if v == int(v) and "." not in t_ else v


class MemoryFinder(QDialog):
    scan_done = Signal(object, object)          # (개수, 오류)
    progress = Signal(int)
    progress_text = Signal(str)
    task_done = Signal(object, object, object)  # (콜백, 결과, 오류)

    def __init__(self, parent=None, pid: Optional[int] = None, exe: str = ""):
        super().__init__(parent)
        self.setWindowTitle(tr("메모리 에디터 — 혼자 하는 게임용"))
        self.resize(760, 640)
        self.reader = None
        self.writer = None
        self.freezer = None
        self.scan = None
        self.pid, self.exe = pid, exe
        self._busy = False
        v = QVBoxLayout(self)
        note = QLabel(tr("보호 장치가 없는 프로그램·혼자 하는 게임에서 값(체력·돈 등)이 든 곳을 찾아 이름을 붙이거나, 바꾸거나, 고정합니다. "
                         "온라인 게임처럼 남에게 영향을 주는 곳에는 쓰지 마세요."))
        note.setWordWrap(True)
        note.setObjectName("Muted")
        v.addWidget(note)

        row = QHBoxLayout()
        self.prog = QComboBox()
        self.prog.setMinimumWidth(360)
        ref = QPushButton(tr("새로 고침"))
        ref.clicked.connect(self.fill_programs)
        row.addWidget(QLabel(tr("① 프로그램")))
        row.addWidget(self.prog, 1)
        row.addWidget(ref)
        v.addLayout(row)

        row = QHBoxLayout()
        self.value = QLineEdit()
        self.value.setPlaceholderText(tr("지금 값(예: 100, 2.1k, 2000~2200)"))
        self.kind = QComboBox()
        for k, lab in KIND_NAMES:
            self.kind.addItem(tr(lab), k)
        self.first_btn = QPushButton(tr("② 처음 찾기"))
        self.first_btn.clicked.connect(self.first_clicked)
        self.unknown_btn = QPushButton(tr("모르는 값으로 시작"))
        self.unknown_btn.setToolTip(tr("값이 화면에 숫자로 안 보일 때(체력 막대 등): 지금 메모리를 담아 두고, 바뀐 뒤 커졌음·작아졌음으로 좁힙니다"))
        self.unknown_btn.clicked.connect(lambda: self.start_first(None))
        row.addWidget(self.value)
        row.addWidget(self.kind)
        row.addWidget(self.first_btn)
        row.addWidget(self.unknown_btn)
        v.addLayout(row)

        row = QHBoxLayout()
        self.mode = QComboBox()
        for k, lab in NEXT_MODES:
            self.mode.addItem(tr(lab), k)
        self.next_value = QLineEdit()
        self.next_value.setPlaceholderText(tr("새 값(또는 바뀐 양)"))
        self.next_btn = QPushButton(tr("③ 다시 찾기"))
        self.next_btn.clicked.connect(self.start_next)
        self.next_btn.setEnabled(False)
        row.addWidget(QLabel(tr("값이 바뀐 뒤")))
        row.addWidget(self.mode)
        row.addWidget(self.next_value)
        row.addWidget(self.next_btn)
        v.addLayout(row)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setVisible(False)
        v.addWidget(self.bar)
        self.count = QLabel(tr("아직 찾지 않음"))
        v.addWidget(self.count)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([tr("주소"), tr("자료형"), tr("지금 값")])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        # 빈 표 대신 보이는 처음 안내(찾기 → 다시 찾기 → 바꾸기·고정 세 걸음)
        from PySide6.QtWidgets import QStackedWidget
        from PySide6.QtCore import Qt
        self.empty_hint = QLabel(tr("① 게임을 고르고 ② 지금 값을 넣어 '처음 찾기'\n"
                                    "③ 게임에서 그 값을 바꾼 뒤 새 값을 넣고 '다시 찾기' — 후보가 몇 개로 줄 때까지\n"
                                    "④ 남은 줄을 골라 이름 붙여 저장, 그다음 값 바꾸기·고정"))
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setObjectName("Muted")
        self.table_stack = QStackedWidget()
        self.table_stack.addWidget(self.empty_hint)
        self.table_stack.addWidget(self.table)
        v.addWidget(self.table_stack, 1)

        row = QHBoxLayout()
        self.replace_btn = QPushButton(tr("고른 줄로 바꿔 저장"))
        self.replace_btn.setToolTip(tr("'다시 찾기' 중일 때: 결과에서 고른 줄을 그 저장 값의 새 자리로"))
        self.replace_btn.clicked.connect(lambda: self.saved_replace_with_selected())
        self.save_btn = QPushButton(tr("④ 이름 붙여 저장"))
        self.save_btn.clicked.connect(self.save_selected)
        self.set_btn = QPushButton(tr("값 바꾸기…"))
        self.set_btn.clicked.connect(self.write_selected)
        self.freeze_btn = QPushButton(tr("고정 켜기/끄기"))
        self.freeze_btn.clicked.connect(self.freeze_selected)
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.01, 5)
        self.interval.setValue(0.1)
        self.interval.setSuffix(tr(" 초마다"))
        for b in (self.save_btn, self.replace_btn, self.set_btn, self.freeze_btn):
            row.addWidget(b)
        row.addWidget(self.interval)
        row.addStretch(1)
        v.addLayout(row)
        # 화면 숫자 도우미: 화면에 보이는 숫자를 읽어 저절로 다시 찾기
        row = QHBoxLayout()
        self.ocr_btn = QPushButton(tr("화면의 숫자 칸 고르기"))
        self.ocr_btn.setToolTip(tr("게임 화면에서 그 값이 보이는 곳을 끌어서 고르면, 숫자를 읽어 찾기에 넣어 줍니다"))
        self.ocr_btn.clicked.connect(self.pick_ocr_region)
        self.ocr_read_btn = QPushButton(tr("화면 숫자로 찾기"))
        self.ocr_read_btn.clicked.connect(self.ocr_step)
        self.ocr_read_btn.setEnabled(False)
        from PySide6.QtWidgets import QCheckBox
        self.ocr_auto = QCheckBox(tr("숫자가 바뀔 때마다 저절로 다시 찾기"))
        self.ocr_auto.setEnabled(False)
        self.ocr_auto.toggled.connect(lambda on: self.ocr_timer.start(1000) if on else self.ocr_timer.stop())
        self.auto_btn = QPushButton(tr("자동으로 좁히기(써 보고 확인)…"))
        self.auto_btn.setToolTip(tr("값이 안 바뀌어도 찾기: 후보에 몇 개씩 새 값을 써 보고 화면 숫자가 바뀌는지로 진짜 자리를 고릅니다"))
        self.auto_btn.clicked.connect(self.start_auto_narrow)
        self.auto_btn.setEnabled(False)
        self.savefile_btn = QPushButton(tr("저장 파일에서 찾기…"))
        self.savefile_btn.setToolTip(tr("게임 저장 파일의 숫자 칸(돈·날짜 등)을 이름으로 찾아 바꿉니다. 화면이 잘 안 바뀌는 게임에 좋아요"))
        self.savefile_btn.clicked.connect(self.open_savefile)
        self.renpy_btn = QPushButton(tr("렌파이 게임 콘솔…"))
        self.renpy_btn.setToolTip(tr("렌파이 게임은 메모리 찾기가 잘 안 돼요. 게임이 가진 개발자 콘솔을 켜서 변수를 바꾸는 길입니다"))
        self.renpy_btn.clicked.connect(self.renpy_console)
        # 처음 보는 사람용: 저장 파일 찾기만 밖에, 나머지 도우미는 '더 보기'로 접음
        from PySide6.QtWidgets import QWidget
        self.more_btn = QPushButton(tr("더 보기…"))
        self.more_btn.setCheckable(True)
        self.more_btn.setToolTip(tr("화면 숫자 읽기·자동으로 좁히기·렌파이 콘솔 같은 도우미"))
        row.addWidget(self.savefile_btn)
        row.addWidget(self.more_btn)
        row.addStretch(1)
        v.addLayout(row)
        self.more_box = QWidget()
        mrow = QHBoxLayout(self.more_box)
        mrow.setContentsMargins(0, 0, 0, 0)
        for w in (self.ocr_btn, self.ocr_read_btn, self.ocr_auto, self.auto_btn, self.renpy_btn):
            mrow.addWidget(w)
        mrow.addStretch(1)
        self.more_box.setVisible(False)
        v.addWidget(self.more_box)
        self.more_btn.toggled.connect(lambda on: (self.more_box.setVisible(on),
                                                  self.more_btn.setText(tr("접기") if on else tr("더 보기…"))))
        # 화면 숫자 칸을 고르기 전엔 못 쓰는 것들은 숨김(흐린 단추로 두지 않음)
        for w in (self.ocr_read_btn, self.ocr_auto, self.auto_btn):
            w.setVisible(False)
        self.ocr_region = None
        self._ocr_last = None
        self.ocr_timer = QTimer(self)
        self.ocr_timer.timeout.connect(self._ocr_tick)

        # 저장한 값(이 프로그램)
        v.addWidget(QLabel("<b>" + tr("저장한 값(이 프로그램)") + "</b>"))
        self.saved = QTableWidget(0, 4)
        self.saved.setHorizontalHeaderLabels([tr("이름"), tr("지금 값"), tr("핫키(고정 켜기/끄기)"), tr("고정")])
        self.saved.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.saved.setSelectionBehavior(QTableWidget.SelectRows)
        self.saved.setEditTriggers(QTableWidget.NoEditTriggers)
        self.saved.setMaximumHeight(170)
        v.addWidget(self.saved)
        row = QHBoxLayout()
        # 11-19: '다시 켜도 찾기'(포인터 경로)·'목표 맞추기'는 실험으로 접어 둠(코드는 남김)
        for lab, fn in ((tr("다시 찾기…"), self.saved_refind), (tr("핫키 정하기"), self.saved_hotkey),
                        (tr("고정 켜기/끄기"), self.saved_freeze),
                        (tr("값 바꾸기…"), self.saved_write), (tr("지우기"), self.saved_delete),
                        (tr("파일로 내보내기"), self.saved_export), (tr("파일에서 가져오기"), self.saved_import)):
            b = QPushButton(lab)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        self.prog.currentIndexChanged.connect(lambda _=None: self.fill_saved())

        self.scan_done.connect(self._on_scan_done)
        self.progress.connect(self.bar.setValue)
        self.progress_text.connect(lambda s: self.count.setText(s))
        self.task_done.connect(lambda cb, res, err: (self._task_end(), cb(res, err)))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_values)
        self.timer.start(500)
        self.fill_programs()
        self.fill_saved()

    # -------------------------------------------------- 프로그램
    def fill_programs(self):
        self.prog.clear()
        try:
            items = programs()
        except Exception:
            items = []
        for label, pid, exe in items:
            self.prog.addItem(label, (pid, exe))
            if self.pid == pid:
                self.prog.setCurrentIndex(self.prog.count() - 1)

    def _target(self):
        d = self.prog.currentData()
        return d if d else (self.pid, self.exe)

    def _ensure_reader(self):
        from engine import memory as mm
        pid, exe = self._target()
        if not pid:
            raise mm.MemoryError_(tr("프로그램을 고르세요"))
        if self.reader is None or self.reader.pid != pid:
            self._close()
            self.reader = mm.ProcessReader(pid)
            self.pid, self.exe = pid, exe
        return self.reader

    def _ensure_writer(self):
        from engine.memwrite import Freezer, ProcessWriter
        r = self._ensure_reader()
        if self.writer is None or self.writer.pid != r.pid:
            self.writer = ProcessWriter(r.pid)
            self.freezer = Freezer(self.writer, self.interval.value())
        return self.writer

    # -------------------------------------------------- 찾기(뒤에서)
    def _run_bg(self, fn):
        if self._busy:
            return
        self._busy = True
        self.bar.setVisible(True)
        self.bar.setValue(0)
        for b in (self.first_btn, self.unknown_btn, self.next_btn):
            b.setEnabled(False)

        def work():
            try:
                n = fn()
                self.scan_done.emit(n, None)
            except Exception as e:                        # 붙지 못함·후보 너무 많음 등은 쉬운 말로
                self.scan_done.emit(None, str(e))
        threading.Thread(target=work, daemon=True).start()

    def _run_task(self, fn, cb):
        if self._busy:
            return
        self._busy = True
        for b in (self.first_btn, self.unknown_btn, self.next_btn, self.auto_btn):
            b.setEnabled(False)

        def work():
            try:
                self.task_done.emit(cb, fn(), None)
            except Exception as e:
                self.task_done.emit(cb, None, str(e))
        threading.Thread(target=work, daemon=True).start()

    def _task_end(self):
        self._busy = False
        self.first_btn.setEnabled(True)
        self.unknown_btn.setEnabled(True)
        self.next_btn.setEnabled(self.scan is not None)
        self.auto_btn.setEnabled(bool(self.ocr_region))

    def first_clicked(self):
        """② 처음 찾기: 빈칸이면 알려 주고(예전엔 몰래 '모르는 값'으로 시작), 글자면 다시 넣게."""
        try:
            v = _parse_value(self.value.text())
        except ValueError:
            QMessageBox.information(self, tr("값 찾기"), tr("숫자로 넣어 주세요(예: 100, 2.1k, 2000~2200)"))
            return
        if v is None:
            QMessageBox.information(self, tr("값 찾기"), tr("지금 값을 넣으세요. 화면에 숫자로 안 보이면 '모르는 값으로 시작'을 누르세요."))
            return
        self.start_first(v)

    def start_first(self, value):
        from engine import memory as mm
        from engine.memscan import Scan
        try:
            r = self._ensure_reader()
        except mm.MemoryError_ as e:
            QMessageBox.warning(self, tr("값 찾기"), str(e))
            return
        self.scan = None                          # 새로 찾는 동안 지난 결과(다른 값)가 남아 보이지 않게
        self._rows = []
        self.table.setRowCount(0)
        self.count.setText(tr("찾는 중… (게임이 크면 몇 분 걸려요)"))
        self.scan = Scan(r, self.kind.currentData(),
                         progress=lambda d, t_: self.progress.emit(int(d * 100 / max(1, t_))))
        self._run_bg(lambda: self.scan.first(value))

    def start_next(self):
        if self.scan is None:
            return
        mode = self.mode.currentData()
        try:
            val = _parse_value(self.next_value.text())
        except ValueError:
            QMessageBox.information(self, tr("값 찾기"), tr("숫자로 넣어 주세요(예: 100, 2.1k, 2000~2200)"))
            return
        if mode in ("eq", "inc_by", "dec_by") and val is None:
            QMessageBox.information(self, tr("값 찾기"), tr("새 값(또는 바뀐 양)을 넣으세요"))
            return
        if isinstance(val, tuple):
            if mode != "eq":
                QMessageBox.information(self, tr("값 찾기"), tr("범위는 '이 값과 같음'에서만 쓸 수 있어요"))
                return
            lo, hi = val
            self._run_bg(lambda: self.scan.next("between", lo, hi))
            return
        self._run_bg(lambda: self.scan.next(mode, val))

    def _on_scan_done(self, n, err):
        if not err and n == 1 and getattr(self, "_refind_name", None) and self.scan is not None:
            rows = self.scan.results(1)            # 다시 찾기: 하나로 좁혀지면 바로 그 자리로 저장
            if rows:
                from engine import memory as mm
                old = self._saved_spec(self._refind_name) or {}
                new = self._spec(rows[0])
                for k in ("hotkey", "freeze_to", "note"):
                    if k in old:
                        new[k] = old[k]
                mm.save_value(self._refind_name, new)
                self.status.setText(tr("'{n}' 을(를) 다시 찾아 저장했어요.").format(n=self._refind_name))
                self._refind_name = None
        self._busy = False
        self.bar.setVisible(False)
        self.first_btn.setEnabled(True)
        self.unknown_btn.setEnabled(True)
        self.next_btn.setEnabled(self.scan is not None)
        if err:
            self.count.setText(err)
            return
        if n == -1:
            self.count.setText(tr("지금 메모리를 담아 두었어요. 값이 바뀐 뒤 '커졌음/작아졌음/바뀌었음'으로 다시 찾으세요."))
        else:
            g = self.scan.guess_kind() if self.scan else None
            places = len({r["address"] for r in self.scan.results(50)}) if self.scan and 1 < n <= 50 else n
            same = (tr(" — 같은 자리 {p}곳을 자료형만 달리 본 것(바꿔서 안 먹히면 다른 줄)").format(p=places)
                    if places < n else "")
            self.count.setText(tr("후보 {n}개").format(n=f"{n:,}") + same + (tr(" · 자료형: {k}").format(k=g) if g else "")
                               + (tr(" — 게임에서 값을 바꾼 뒤 다시 찾아 더 좁히세요") if n > 20 else "")
                               + (tr(" (표에는 앞 200개만)") if n > 200 else ""))
        self.fill_table()

    # -------------------------------------------------- 결과
    def fill_table(self):
        rows = self.scan.results(200) if self.scan and self.scan.count() > 0 else []
        self.table.setRowCount(len(rows))
        self.table_stack.setCurrentWidget(self.table if (rows or (self.scan and self.scan.count() != 0)) else self.empty_hint)
        for i, r in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(hex(r["address"])))
            self.table.setItem(i, 1, QTableWidgetItem(r["kind"]))
            self.table.setItem(i, 2, QTableWidgetItem(str(r["value"])))
        self._rows = rows

    def refresh_values(self):
        """보이는 결과·저장한 값의 지금 값(0.5초마다)."""
        if self._busy:
            return
        if getattr(self, "_saved", None):
            try:
                rd = self._ensure_reader()
            except Exception:
                rd = None
            for i, n in enumerate(self._saved):
                sp = self._saved_spec(n)
                try:
                    val = rd.value(sp) if rd is not None and sp else "?"
                except Exception:
                    val = "?"
                it = self.saved.item(i, 1)
                if it is not None and it.text() != str(val):
                    it.setText(str(val))
        if self.reader is None or not getattr(self, "_rows", None):
            return
        for i, r in enumerate(self._rows[:200]):
            try:
                val = self.reader.value({"offset": r["address"], "kind": r["kind"]})
            except Exception:
                val = "?"
            it = self.table.item(i, 2)
            if it is not None and it.text() != str(val):
                it.setText(str(val))

    def _selected(self):
        i = self.table.currentRow()
        rows = getattr(self, "_rows", [])
        return rows[i] if 0 <= i < len(rows) else None

    def _spec(self, row):
        from engine.memscan import spec_for
        sp = spec_for(self._ensure_reader(), row["address"], row["kind"])
        if self.exe:
            sp["process"] = self.exe
        return sp

    def save_selected(self):
        from engine import memory as mm
        row = self._selected()
        if row is None:
            return
        name, ok = QInputDialog.getText(self, tr("이름 붙여 저장"), tr("이 값의 이름(예: 체력, 돈):"))
        if not ok or not name.strip():
            return
        mm.save_value(name.strip(), self._spec(row))
        self.fill_saved()
        self.status.setText(tr("'{n}' 으로 저장했어요. 아래 '저장한 값'에서 바꾸기·고정·핫키를 쓸 수 있어요.").format(n=name.strip()))

    def write_selected(self):
        from engine import memory as mm
        row = self._selected()
        if row is None:
            return
        text, ok = QInputDialog.getText(self, tr("값 바꾸기"), tr("넣을 값:"), text=str(row["value"]))
        if not ok or _num(text) is None:
            return
        try:
            spec = {"offset": row["address"], "kind": row["kind"]}
            self._ensure_writer().write(spec, _num(text))
            if self._reverted(spec, _num(text)):
                return
            self.status.setText(tr("{a} 에 {v} 을(를) 넣었어요(기록: logs\\memory\\writes.jsonl)").format(a=hex(row["address"]), v=text)
                                + "  " + tr("화면이 바로 안 바뀌는 게임도 있어요 — 게임에서 값이 한 번 바뀌거나 저장을 다시 불러오면 보여요."))
        except mm.MemoryError_ as e:
            QMessageBox.warning(self, tr("값 바꾸기"), str(e))

    def _reverted(self, spec, want) -> bool:
        """써 넣은 뒤 잠깐 있다 다시 읽어, 게임이 곧바로 되돌렸으면(화면 표시용 복사본) 알려 준다."""
        import time as _t
        try:
            for _ in range(3):
                _t.sleep(0.1)
                now = self.reader.value(spec)
                if now is None or abs(float(now) - float(want)) > 0.5:
                    QMessageBox.information(self, tr("값 바꾸기"), tr(
                        "써 넣었지만 게임이 곧바로 {now}(으)로 되돌렸어요.\n"
                        "이 자리는 화면 표시용 복사본일 가능성이 커요. 결과의 다른 줄(특히 다른 자료형)을 골라 바꿔 보거나, "
                        "자료형을 '자동'으로 두고 처음부터 다시 찾아 보세요.").format(now=now))
                    self.status.setText(tr("게임이 값을 되돌렸어요 — 다른 줄을 골라 보세요"))
                    return True
        except Exception:
            return False
        return False

    def freeze_selected(self):
        from engine import memory as mm
        row = self._selected()
        if row is None:
            return
        try:
            self._ensure_writer()
            self.freezer.interval = self.interval.value()
            key = hex(row["address"])
            cur = self.reader.value({"offset": row["address"], "kind": row["kind"]})
            on = self.freezer.toggle(key, {"offset": row["address"], "kind": row["kind"]}, cur)
            self.status.setText((tr("{a} 를 {v} 으로 고정했어요(이 창을 닫으면 풀림)") if on else tr("{a} 고정을 풀었어요"))
                                .format(a=key, v=cur))
        except mm.MemoryError_ as e:
            QMessageBox.warning(self, tr("고정"), str(e))

    # -------------------------------------------------- 저장한 값
    def _saved_names(self):
        from engine import memory as mm
        return sorted(mm.values_for(self._target()[1] or ""))

    def fill_saved(self):
        from engine import memory as mm
        vals = mm.values_for(self._target()[1] or "")
        names = sorted(vals)
        self.saved.setRowCount(len(names))
        frozen = set(self.freezer.active()) if self.freezer else set()
        for i, n in enumerate(names):
            sp = vals[n]
            from gui.v3.hotkey_dialog import display
            for c, txt in enumerate((n, "", display(sp.get("hotkey", "")) or "-",
                                     tr("켜짐") if ("name:" + n) in frozen else "-")):
                self.saved.setItem(i, c, QTableWidgetItem(txt))
        self._saved = names

    def _saved_sel(self):
        i = self.saved.currentRow()
        names = getattr(self, "_saved", [])
        return names[i] if 0 <= i < len(names) else None

    def _saved_spec(self, name):
        from engine import memory as mm
        return mm.load_values().get(name)

    def saved_refind(self):
        """게임을 다시 켰을 때: 고른 저장 값의 자료형으로 지금 값을 찾는다. 후보가 하나면 바로 그 자리로 바꿔 저장,
        여럿이면 값이 바뀐 뒤 '③ 다시 찾기' → 줄을 고르고 '고른 줄로 바꿔 저장'."""
        from engine import memory as mm
        n = self._saved_sel()
        if not n:
            return
        sp = self._saved_spec(n)
        text, ok = QInputDialog.getText(self, tr("다시 찾기"), tr("게임 화면의 '{n}' 지금 값:").format(n=n))
        try:
            val = _parse_value(text) if ok else None
        except ValueError:
            val = None
        if val is None:
            return
        self._refind_name = n
        kind = sp.get("kind", "int32")
        i = self.kind.findData(kind)
        if i >= 0:
            self.kind.setCurrentIndex(i)
        self.value.setText(text)
        self.status.setText(tr("'{n}' 을(를) 다시 찾는 중… 후보가 여럿이면 값이 바뀐 뒤 '③ 다시 찾기'를 누르고, 남은 줄을 골라 '고른 줄로 바꿔 저장'.").format(n=n))
        self.start_first(val)

    def saved_replace_with_selected(self):
        """결과 표에서 고른 줄로 저장 값의 자리를 바꿈(이름·핫키·자료형은 그대로)."""
        from engine import memory as mm
        n = getattr(self, "_refind_name", None) or self._saved_sel()
        row = self._selected()
        if not n or row is None:
            QMessageBox.information(self, tr("다시 찾기"), tr("저장 값 하나와 결과 줄 하나를 고르세요"))
            return
        old = self._saved_spec(n) or {}
        new = self._spec(row)
        for k in ("hotkey", "freeze_to", "note"):
            if k in old:
                new[k] = old[k]
        mm.save_value(n, new)
        self._refind_name = None
        self.fill_saved()
        self.status.setText(tr("'{n}' 을(를) 새 자리로 바꿔 저장했어요.").format(n=n))

    def saved_relocate(self):
        """다시 켜도 찾기: ① 지금 경로 후보를 모아 두고 → (프로그램을 껐다 켠 뒤) ② 같은 값에 닿는 경로만 남겨 저장."""
        import os
        from engine import memory as mm
        from engine import memptr as mp
        n = self._saved_sel()
        if not n:
            return
        sp = self._saved_spec(n)
        f = os.path.join(os.path.dirname(mm.values_path()), "paths", "".join(c if c not in '\\/:*?"<>|' else "_" for c in n) + ".json")
        try:
            r = self._ensure_reader()
        except Exception as e:
            QMessageBox.warning(self, tr("다시 켜도 찾기"), str(e))
            return
        try:
            cur = r.value(sp)
        except Exception:
            cur = ""                                  # 다시 켠 뒤엔 예전 주소가 안 읽힐 수 있음
        if os.path.exists(f) and not sp.get("pointers"):
            text, ok = QInputDialog.getText(self, tr("다시 켜도 찾기"),
                                            tr("모아 둔 후보가 있어요. 프로그램을 껐다 켰다면 지금 화면의 '{n}' 값을 넣으세요:").format(n=n),
                                            text=str(cur))
            if not ok or _num(text) is None:
                return
            cands = mp.load_candidates(f)

            def work():
                return mp.stable_paths(cands["paths"], r, cands["kind"], _num(text))

            def done(keep, err):
                if err or not keep:
                    if sp.get("pattern"):                  # 경로가 끊겼으면 무늬로
                        try:
                            if r.value(sp) == _num(text):
                                self.status.setText(tr("경로는 끊겼지만 무늬로 '{n}' 을(를) 다시 찾았어요. 다시 켜도 무늬로 찾아요.").format(n=n))
                                return
                        except Exception:
                            pass
                    self.status.setText(err or tr("다시 켠 뒤 맞는 경로가 없어요 — 지금 값으로 다시 찾아 저장한 뒤 후보를 새로 모으세요"))
                    return
                new = mp.to_spec(keep[0], cands["kind"])
                if sp.get("process"):
                    new["process"] = sp["process"]
                for k in ("hotkey", "freeze_to"):
                    if k in sp:
                        new[k] = sp[k]
                mm.save_value(n, new)
                mp.save_candidates(keep, cands["kind"], f, note="겹친 뒤")
                self.status.setText(tr("다시 켜도 찾는 경로를 정했어요(맞는 경로 {k}개 중 하나). 이제 '{n}' 은 다시 켜도 찾아요.").format(k=len(keep), n=n))
                self.fill_saved()
            self._run_task(work, done)
            return
        if QMessageBox.question(self, tr("다시 켜도 찾기"), tr(
                "지금 '{n}' 에 닿는 경로 후보를 모읍니다(1~5분). 다 모으면 프로그램을 껐다 켜고 같은 값을 다시 찾지 말고 "
                "이 단추를 한 번 더 누르세요 — 양쪽에 다 맞는 경로만 남겨 저장합니다. 계속할까요?").format(n=n)) != QMessageBox.Yes:
            return
        addr = r.resolve(sp)
        try:                                           # 무늬도 같이 떠 둠(경로가 안 되는 게임의 다른 길)
            from engine import mempattern as mpat
            sp["pattern"] = mpat.capture(r, addr, sp.get("kind", "int32"))
            mm.save_value(n, sp)
        except Exception:
            pass

        def work():
            return mp.find_paths(r, addr, depth=4, max_off=0x1000, max_paths=3000, level_cap=6000, keep_going=True)

        def done(paths, err):
            if err or not paths:
                self.status.setText(err or tr("경로 후보를 못 찾았어요(값이 자주 옮겨 다니는 프로그램일 수 있음)"))
                return
            os.makedirs(os.path.dirname(f), exist_ok=True)
            mp.save_candidates(paths, sp.get("kind", "int32"), f, note="첫 실행")
            self.status.setText(tr("경로 후보 {k}개를 모았어요. 프로그램을 껐다 켠 뒤 '다시 켜도 찾기…'를 한 번 더 누르세요.").format(k=len(paths)))
        self._run_task(work, done)

    def saved_goal(self):
        """계산되는 값 맞추기: 고른 값(입력, 예: 점수)을 바꿔 가며 결과(예: 레벨)를 읽어 목표에 닿을 때까지 스스로 맞춘다.
        결과는 저장한 다른 값(메모리)이나 화면 숫자 칸으로 읽는다. 사람에게 숫자를 묻지 않는다."""
        from engine import memory as mm
        from engine import mempattern as mpat
        n = self._saved_sel()
        if not n:
            return
        names = [x for x in self._saved_names() if x != n]
        opts = names + ([tr("(화면 숫자 칸)")] if self.ocr_region else [])
        if not opts:
            QMessageBox.information(self, tr("목표 맞추기"), tr("결과를 읽을 값이 필요해요 — 결과 값을 찾아 저장하거나 화면의 숫자 칸을 고르세요"))
            return
        out, ok = QInputDialog.getItem(self, tr("목표 맞추기"), tr("'{n}' 을(를) 바꾸면 달라지는 결과는?").format(n=n), opts, 0, False)
        if not ok:
            return
        text, ok = QInputDialog.getText(self, tr("목표 맞추기"), tr("결과의 목표(예: 레벨 10이면 10):"))
        if not ok or _num(text) is None:
            return
        hi_t, ok = QInputDialog.getText(self, tr("목표 맞추기"), tr("'{n}' 의 최대값(넉넉하게):").format(n=n), text="100000")
        if not ok or _num(hi_t) is None:
            return
        sp_in = self._saved_spec(n)
        try:
            w = self._ensure_writer()
        except mm.MemoryError_ as e:
            QMessageBox.warning(self, tr("목표 맞추기"), str(e))
            return
        if out in names:
            sp_out = self._saved_spec(out)
            read = lambda: w.value(sp_out)          # noqa: E731
        else:
            read = self.read_screen_number

        def work():
            return mpat.goal_seek(lambda x: w.write(sp_in, x), read, _num(text), 0, _num(hi_t), settle=0.6,
                                  progress=self.progress_text.emit)

        def done(got, err):
            if err or got is None:
                self.status.setText(err or tr("목표에 닿는 값을 못 찾았어요(최대값이 모자라거나 결과가 바로 안 바뀌는 게임)"))
                return
            self.status.setText(tr("'{n}' = {v} 로 맞췄어요(결과가 목표에 닿는 가장 작은 값).").format(n=n, v=got))
        self._run_task(work, done)

    def saved_hotkey(self):
        from engine import memory as mm
        from gui.v3.hotkey_dialog import HotkeyDialog
        n = self._saved_sel()
        if not n:
            return
        sp = self._saved_spec(n)
        d = HotkeyDialog(self, tr("'{n}' 고정 켜기/끄기 키").format(n=n), sp.get("hotkey", ""))
        if d.exec():
            sp["hotkey"] = d.get_hotkey()
            if not sp["hotkey"]:
                sp.pop("hotkey")
            mm.save_value(n, sp)
            self.fill_saved()
            p = self.parent()
            if p is not None and hasattr(p, "register_hotkeys"):
                p.register_hotkeys()                 # 프로그램 전체에서(창을 닫아도) 먹게
            self.status.setText(tr("'{n}' 핫키를 정했어요. 이 창을 닫아도, 프로그램이 뒤에 있어도 그 키로 고정을 켜고 끕니다.").format(n=n))

    def saved_freeze(self):
        from engine import memory as mm
        n = self._saved_sel()
        if not n:
            return
        try:
            self._ensure_writer()
            sp = self._saved_spec(n)
            cur = self.writer.value(sp)
            on = self.freezer.toggle("name:" + n, sp, sp.get("freeze_to", cur))
            self.status.setText((tr("'{n}' 고정 켜짐({v})") if on else tr("'{n}' 고정 꺼짐")).format(n=n, v=sp.get("freeze_to", cur)))
        except mm.MemoryError_ as e:
            QMessageBox.warning(self, tr("고정"), str(e))
        self.fill_saved()

    def saved_write(self):
        from engine import memory as mm
        n = self._saved_sel()
        if not n:
            return
        text, ok = QInputDialog.getText(self, tr("값 바꾸기"), tr("넣을 값:"))
        if not ok or _num(text) is None:
            return
        try:
            sp = self._saved_spec(n)
            self._ensure_writer().write(sp, _num(text))
            if self._reverted(sp, _num(text)):
                return
            self.status.setText(tr("'{n}' 에 {v} 을(를) 넣었어요").format(n=n, v=text))
        except mm.MemoryError_ as e:
            QMessageBox.warning(self, tr("값 바꾸기"), str(e))

    def saved_delete(self):
        from engine import memory as mm
        n = self._saved_sel()
        if n and QMessageBox.question(self, tr("지우기"), tr("'{n}' 을(를) 지울까요?").format(n=n)) == QMessageBox.Yes:
            mm.delete_value(n)
            self.fill_saved()

    def saved_export(self):
        from PySide6.QtWidgets import QFileDialog
        from engine import memory as mm
        exe = self._target()[1] or "program"
        path, _ = QFileDialog.getSaveFileName(self, tr("파일로 내보내기"), f"{exe}_값.json", "JSON (*.json)")
        if path:
            n = mm.export_values(exe, path)
            self.status.setText(tr("{n}개를 내보냈어요: {p}").format(n=n, p=path))

    def saved_import(self):
        from PySide6.QtWidgets import QFileDialog
        from engine import memory as mm
        path, _ = QFileDialog.getOpenFileName(self, tr("파일에서 가져오기"), "", "JSON (*.json)")
        if path:
            try:
                n = mm.import_values(path)
            except (OSError, ValueError, mm.MemoryError_) as e:
                QMessageBox.warning(self, tr("파일에서 가져오기"), str(e))
                return
            self.fill_saved()
            self.status.setText(tr("{n}개를 가져왔어요").format(n=n))

    # -------------------------------------------------- 화면 숫자 도우미
    def pick_ocr_region(self):
        from gui.v3.editor.screen_picker import ScreenTools
        tools = ScreenTools(self, lambda: None, lambda: "", lambda: [self])
        r = tools.pick_region()
        if r:
            self.ocr_region = r
            for w in (self.ocr_read_btn, self.ocr_auto, self.auto_btn):
                w.setEnabled(True)
                w.setVisible(True)
            self.status.setText(tr("숫자 칸을 정했어요. [화면 숫자로 찾기]를 누르거나 '저절로 다시 찾기'를 켜세요."))

    def read_screen_number(self):
        """정한 화면 칸의 숫자(그림 인식). 못 읽으면 None."""
        if not self.ocr_region:
            return None
        from engine import new_macro
        from engine.real import RealEnv
        ev = []
        m = new_macro("화면숫자", [{"type": "read_number", "region": list(self.ocr_region), "var": "n"}])
        res = RealEnv().runner(m, on_event=ev.append).run()
        got = [e.get("value") for e in ev if e.get("event") == "set" and e.get("var") == "n"]
        return got[-1] if res.status == "ok" and got else None

    def ocr_step(self):
        n = self.read_screen_number()
        if n is None:
            self.status.setText(tr("화면 숫자를 못 읽었어요 — 칸을 숫자에 꼭 맞게 다시 골라 보세요"))
            return
        self._ocr_last = n
        self.value.setText(str(n))
        self.next_value.setText(str(n))
        if self.scan is None:
            self.start_first(n)
        else:
            self.mode.setCurrentIndex(self.mode.findData("eq"))
            self.start_next()

    def renpy_console(self):
        """렌파이 콘솔 켜기/끄기: game 폴더에 작은 파일 하나만 넣고 뺀다(원본 그대로)."""
        from PySide6.QtWidgets import QFileDialog
        from engine import memsafe as ms
        from engine import renpy_tools as rt
        path = ""
        try:
            pid = self._target()[0]
            path = ms.exe_path(pid) if pid else ""
        except Exception:
            pass
        if not path or not rt.game_dir(path):
            path = QFileDialog.getExistingDirectory(self, tr("렌파이 게임 폴더 고르기"))
            if not path:
                return
        if not rt.game_dir(path):
            QMessageBox.information(self, tr("렌파이 게임 콘솔"), tr("렌파이 게임 폴더가 아니에요(game 폴더를 찾지 못함)"))
            return
        on = rt.console_on(path)
        q = (tr("콘솔이 켜져 있어요. 끌까요?(넣었던 파일을 지워 원래대로)") if on else
             tr("게임이 가진 개발자 콘솔을 켭니다. game 폴더에 파일 하나만 넣고, 끄면 지워져요.\n"
                "켠 뒤 게임을 다시 시작하고 Shift+O → 예: money = 100000 처럼 바꾸세요. 켤까요?"))
        if QMessageBox.question(self, tr("렌파이 게임 콘솔"), q) != QMessageBox.Yes:
            return
        g = rt.set_console(path, not on)
        self.status.setText((tr("콘솔을 껐어요: {g}") if on else tr("콘솔을 켰어요: {g} — 게임을 다시 시작하고 Shift+O")).format(g=g))

    def open_savefile(self):
        from engine import memsafe as ms
        start = ""
        try:
            pid = self._target()[0]
            folders = ms.save_folders(ms.exe_path(pid)) if pid else []
            start = folders[0] if folders else ""
        except Exception:
            pass
        d = SaveFileDialog(self, start)
        self._savefile_dialog = d
        d.exec()

    def _region_crop(self):
        from PIL import ImageGrab
        import numpy as np
        x, y, w, h = self.ocr_region
        return np.asarray(ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)).astype(int)

    def start_auto_narrow(self):
        """값이 안 바뀌어도 찾기: 안전하게 줄이고(바뀌는 자리·포인터 빼기) → 저장 폴더 백업 → 몇 개씩 써 보며 반씩 좁히기."""
        from engine import memsafe as ms
        if self.scan is None or self.scan.count() <= 0 or not self.ocr_region:
            QMessageBox.information(self, tr("자동으로 좁히기"), tr("먼저 처음 찾기를 하고 화면의 숫자 칸을 고르세요"))
            return
        text, ok = QInputDialog.getText(self, tr("자동으로 좁히기"), tr("새로 넣을 값(예: 100000):"))
        if not ok or _num(text) is None:
            return
        if QMessageBox.question(self, tr("자동으로 좁히기"), tr(
                "후보에 몇 개씩 새 값을 써 보며 화면 숫자가 바뀌는지 봅니다.\n"
                "돈이 아닌 자리에 쓰면 프로그램이 꺼질 수 있어요 — 먼저 게임에서 저장하세요.\n"
                "찾을 수 있는 저장 폴더는 자동으로 백업합니다. 혼자 하는 게임에서만 쓰세요.\n\n계속할까요?")) != QMessageBox.Yes:
            return
        new = _num(text)
        kind = self.scan.guess_kind() or "int32"
        addrs = [r["address"] for r in self.scan.results(100000) if r["kind"] == kind]
        expect = _num(self.value.text()) if self.value.text().strip() else None
        try:
            w = self._ensure_writer()
            backups = ms.backup_saves(ms.exe_path(w.pid))
        except Exception as e:
            QMessageBox.warning(self, tr("자동으로 좁히기"), str(e))
            return
        state = {"base": self._region_crop()}

        def screen_changed():
            import numpy as np
            cur = self._region_crop()
            ch = cur.shape == state["base"].shape and float(np.abs(cur - state["base"]).mean()) > 6
            state["base"] = cur
            return ch

        def work():
            kept = ms.narrow_safe(w, addrs, kind, expect)
            self.progress_text.emit(tr("안전하게 줄임: {a} → {b}곳(바뀌는 자리 {c}·포인터 {d} 뺌)").format(
                a=len(addrs), b=len(kept["keep"]), c=len(kept["changing"]), d=len(kept["pointer"]) + len(kept["mapped"])))
            real = ms.auto_narrow(w, kept["keep"], kind, new, screen_changed, progress=self.progress_text.emit)
            if real is None:
                raise RuntimeError(tr("써 봐도 화면 숫자가 안 바뀌었어요. 이 게임은 돈이 바뀌는 순간에만 화면을 다시 그릴 수 있어요 — "
                                      "'저장 파일에서 찾기'를 쓰거나, 게임에서 값이 한 번 바뀐 뒤 다시 찾으세요."))
            return real

        def done(real, err):
            if err:
                self.count.setText(err)
                return
            self.status.setText(tr("찾았어요: {a} 에 {v} 을(를) 넣었어요. 이름 붙여 저장하세요.").format(a=hex(real), v=new)
                                + ("  " + tr("저장 백업: {p}").format(p=backups[0]) if backups else ""))
            self.scan.cands = {kind: (__import__("numpy").array([real], dtype="int64"),
                                      __import__("numpy").array([new]))}
            self.fill_table()
        self._run_task(work, done)

    def _ocr_tick(self):
        if self._busy:
            return
        n = self.read_screen_number()
        if n is None or n == self._ocr_last:
            return
        self.ocr_step()
        if self.scan is not None and 0 <= self.scan.count() <= 3:
            self.ocr_auto.setChecked(False)
            self.status.setText(tr("후보가 {n}개로 줄었어요. 골라서 이름 붙여 저장하세요.").format(n=self.scan.count()))

    # -------------------------------------------------- 닫기
    def _close(self):
        if self.freezer is not None:
            self.freezer.stop()
            self.freezer = None
        for x in (self.writer, self.reader):
            try:
                if x is not None:
                    x.close()
            except Exception:
                pass
        self.writer = self.reader = None

    def done(self, r):
        self.timer.stop()
        self.ocr_timer.stop()
        self._close()
        super().done(r)


class SaveFileDialog(QDialog):
    """저장 파일의 숫자 칸을 이름으로 찾아 바꾸기(원본 폴더 자동 백업·기록). 게임을 다시 불러와야 반영."""

    def __init__(self, parent=None, folder: str = "", path: str = ""):
        super().__init__(parent)
        self.setWindowTitle(tr("저장 파일에서 찾기 — 혼자 하는 게임용"))
        self.resize(640, 520)
        self.path = path
        v = QVBoxLayout(self)
        tip = QLabel(tr("게임을 끄거나 타이틀 화면에서 바꾸고, 바꾼 뒤 그 저장을 다시 불러오세요. 게임 안에서 저장하면 바꾼 값이 덮일 수 있어요."))
        tip.setWordWrap(True)
        tip.setObjectName("Muted")
        v.addWidget(tip)
        row = QHBoxLayout()
        self.file_label = QLabel(path or tr("파일을 고르세요"))
        pick = QPushButton(tr("파일 고르기…"))
        pick.clicked.connect(lambda: self.choose(folder))
        row.addWidget(self.file_label, 1)
        row.addWidget(pick)
        v.addLayout(row)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("칸 이름 찾기(예: money, gold, hp)"))
        self.search.textChanged.connect(lambda _=None: self.fill())
        v.addWidget(self.search)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([tr("칸 이름"), tr("지금 값")])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        v.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.set_btn = QPushButton(tr("값 바꾸기…"))
        self.set_btn.clicked.connect(self.change)
        row.addWidget(self.set_btn)
        row.addStretch(1)
        v.addLayout(row)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setObjectName("Muted")
        v.addWidget(self.status)
        if path:
            self.fill()

    def choose(self, folder=""):
        from PySide6.QtWidgets import QFileDialog
        p, _ = QFileDialog.getOpenFileName(self, tr("저장 파일 고르기"), folder, tr("저장 파일 (*.sav *.save *.json *.dat *.ini *.cfg *.txt);;모든 파일 (*)"))
        if p:
            self.path = p
            self.file_label.setText(p)
            self.fill()

    def fill(self):
        from engine import memory as mm
        from engine import savefile as sf
        if not self.path:
            return
        try:
            rows = sf.find(self.path, self.search.text())
        except (mm.MemoryError_, OSError, ValueError) as e:
            self.status.setText(str(e))
            rows = []
        self.table.setRowCount(len(rows))
        for i, f in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(f["name"]))
            self.table.setItem(i, 1, QTableWidgetItem(str(f["value"])))
        self._rows = rows

    def change(self):
        from engine import memory as mm
        from engine import savefile as sf
        i = self.table.currentRow()
        rows = getattr(self, "_rows", [])
        if not (0 <= i < len(rows)):
            return
        f = rows[i]
        text, ok = QInputDialog.getText(self, tr("값 바꾸기"), tr("'{n}' 에 넣을 값:").format(n=f["name"]), text=str(f["value"]))
        if not ok or _num(text) is None:
            return
        try:
            r = sf.set_value(self.path, f["name"], _num(text))
        except (mm.MemoryError_, OSError) as e:
            QMessageBox.warning(self, tr("값 바꾸기"), str(e))
            return
        self.status.setText(tr("'{n}': {a} → {b}. 원본은 {p} 에 있어요. 게임에서 이 저장을 다시 불러오세요.").format(
            n=f["name"], a=r["old"], b=r["new"], p=r["backup"]))
        self.fill()

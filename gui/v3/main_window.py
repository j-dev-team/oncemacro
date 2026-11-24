"""
매크로 프로그램 v2 메인 창: macros_v2/ 매크로 목록·실행·정지·핫키·편집.

왼쪽: 그룹 트리(검색, 끌어서 그룹 이동), 버튼(새 매크로·편집·삭제·실행·중지)
오른쪽: 매크로 정보, 스텝 트리(실행 중인 스텝 강조), 실행 기록
"""
from __future__ import annotations

import os
from typing import Callable, Dict, Optional

from PySide6.QtCore import QEvent, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QShortcut, QBrush, QColor, QKeySequence
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QStatusBar, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from engine.model import MacroError
from gui.v2.describe import BRANCH_NAMES, step_text
from gui.v2.i18n import tr
from .icons import CATEGORY_COLORS, step_icon, tool_icon
from .design import theme as _theme
from .widgets import STEP_NUM_ROLE
from gui.v2.model import CHILD_KEYS
from .run_thread import RunThread
from gui.v2.store import MacroStore, StoreError

WELCOME_LAYOUT = "B"      # 매크로가 없을 때 첫 화면: "A" 오른쪽 칸만 / "B" 목록까지 통째로

ROLE_KIND = Qt.UserRole
ROLE_NAME = Qt.UserRole + 1
ROLE_PATH = Qt.UserRole + 2
ROLE_META = Qt.UserRole + 3

from PySide6.QtGui import QTextBlockUserData as _QTBUD  # noqa: E402


class _LogLink(_QTBUD):
    """실행 기록 줄에 붙이는 '이 줄 = 이 매크로의 이 스텝'."""

    def __init__(self, macro: str, path: str):
        super().__init__()
        self.macro, self.path = macro, path     # 새 화면 목록 줄: {hot, last, status, status_text, running}

RUN_BG = QColor("#fff3b0")
OK_FG = QColor("#2e7d32")
SKIP_FG = QColor("#8d6e00")
FAIL_FG = QColor("#c62828")


class _StoreLib:
    """승인 반영용: 화면의 매크로 저장소를 엔진 저장소처럼(load·save·path_for)."""

    def __init__(self, store):
        self.store = store

    def load(self, name):
        return self.store.load(name)

    def save(self, macro):
        return self.store.save(macro) if hasattr(self.store, "save") else None

    def path_for(self, name):
        return self.store.path(name)


class MacroTree(QTreeWidget):
    """매크로 목록. 매크로를 그룹 위로 끌어 놓으면 그 그룹으로 옮긴다."""
    moved = Signal(str, object)       # 매크로 이름, 그룹 이름(None = 그룹 없음)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabel(tr("매크로 (v2)"))
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QTreeWidget.InternalMove)
        self.setExpandsOnDoubleClick(False)

    def group_band_rect(self, row_rect, index):
        """묶음 제목 띠가 차지하는 칸(줄 높이에서 위 틈을 뺀 곳)."""
        from PySide6.QtCore import QRectF
        top_gap = row_rect.height() - (32 if row_rect.height() <= 40 else 36)
        return QRectF(row_rect).adjusted(0, top_gap + 2, 0, -2)

    def drawRow(self, painter, option, index):
        """묶음 제목 줄은 화살표 칸까지 줄 전체에 옅은 띠를 깐다(일반 매크로 줄과 한눈에 구분)."""
        kind = index.data(ROLE_KIND)
        if kind in ("group", "recent"):
            from PySide6.QtGui import QPainterPath
            t = _theme.current()
            band = self.group_band_rect(option.rect, index).adjusted(4, 0, -6, 0)
            band.setLeft(4)
            painter.save()
            painter.setRenderHint(painter.RenderHint.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(band, t["radius_s"], t["radius_s"])
            painter.fillPath(path, QColor(t["surface2"] if t["theme"] == "light" else t["line"]))   # 어두운 테마는 한 단계 진하게
            painter.restore()
        super().drawRow(painter, option, index)

    def drawBranches(self, painter, rect, index):
        """접기 화살표 + 하위 매크로 안내선(부모 매크로 칸에 세로줄)을 직접 그림."""
        from .design.assets import pixmap
        t = _theme.current()
        ind = self.indentation()
        depth, p = 0, index.parent()
        kinds = []
        while p.isValid():
            kinds.append(p.data(ROLE_KIND))
            depth += 1
            p = p.parent()
        kinds.reverse()                                 # kinds[i] = i 단계 조상의 종류
        if index.data(ROLE_KIND) in ("group", "recent"):
            band = self.group_band_rect(rect, index)
            cy = band.center().y()
        else:
            cy = rect.center().y()
        for i, k in enumerate(kinds):
            if k == "macro":                            # 매크로가 부르는 하위 매크로 → 부모 칸에 세로 안내선
                cx = rect.left() + i * ind + ind // 2
                painter.fillRect(int(cx), rect.top(), 1, rect.height(), QColor(t["guide"]))
        if not self.model().hasChildren(index):
            return
        name = "chevron-down" if self.isExpanded(index) else "chevron-right"
        x = rect.left() + depth * ind + (ind - 16) // 2
        painter.drawPixmap(int(x), int(cy - 8), pixmap(name, t["text"] if index.data(ROLE_KIND) in ("group", "recent")
                                                       else t["muted"], 16))

    def dropEvent(self, e):
        src = self.currentItem()
        if src is None or src.data(0, ROLE_KIND) != "macro":
            e.ignore()
            return
        target = self.itemAt(e.pos())
        group = None
        while target is not None and target.data(0, ROLE_KIND) in ("macro", "parts"):
            if target.data(0, ROLE_KIND) == "macro" and target.parent() is None:
                target = None
                break
            target = target.parent()
        if target is not None:
            if target.data(0, ROLE_KIND) == "recent":
                e.ignore()
                return
            if target.data(0, ROLE_KIND) == "group":
                group = target.data(0, ROLE_NAME)
        e.ignore()      # 트리는 저장소 기준으로 다시 그린다
        self.moved.emit(src.data(0, ROLE_NAME), group)


class MainWindowV2(QMainWindow):
    hotkey_run = Signal(str)
    hotkey_stop = Signal(str)
    record_done = Signal(list)

    def __init__(self, store: Optional[MacroStore] = None, env_factory: Optional[Callable] = None,
                 hotkeys: bool = True, emergency_hotkey: Optional[str] = "ctrl+shift+f12",
                 write_trace: bool = True):
        super().__init__()
        self.setWindowTitle(tr("원스매크로"))
        self.setGeometry(100, 100, 1200, 800)
        self.store = store or MacroStore()
        self.env_factory = env_factory
        self.emergency_hotkey = emergency_hotkey
        self.write_trace = write_trace
        self.run_thread: Optional[RunThread] = None
        self.running_name: Optional[str] = None
        self.copied: Optional[dict] = None
        self.path_items: Dict[str, QTreeWidgetItem] = {}
        self._highlighted: Optional[QTreeWidgetItem] = None
        self._run_pos: dict = {}          # 매크로 이름 → 지금 진행 중인 스텝 경로(실행 중)
        self._run_marks: dict = {}        # 매크로 이름 → {스텝 경로: (상태, ms)}
        self._shown_name: Optional[str] = None
        from PySide6 import QtCore as _qc
        from gui.v2.settings_path import open_settings
        self.settings = open_settings(_qc, "v2")
        self._minimized_for_run = False

        self._build_ui()
        self._build_menus()
        self._build_shortcuts()
        self.hotkey_run.connect(self.run_macro)
        self.hotkey_stop.connect(lambda key: self.stop_macro(tr("정지 단축키 {key}").format(key=key)))
        self.record_done.connect(self._on_record_done)
        self._recorder = None
        self.sched_timer = QTimer(self)          # 예약 실행 확인(20초마다, 프로그램이 켜져 있을 때만)
        self.sched_timer.timeout.connect(self._check_schedules)
        self.sched_timer.start(20000)

        self.hotkey_manager = None
        if hotkeys:
            try:
                from utils.hotkey_manager import HotkeyManager
                self.hotkey_manager = HotkeyManager()
            except Exception as e:      # 핫키가 없어도 프로그램은 동작
                print(tr("[핫키] 사용할 수 없음: {e}").format(e=e))
        self.reload_list()
        self.register_hotkeys()
        self.refresh_approval_badge()

    # ================================================================ UI
    def _build_ui(self):
        """새 화면(시안 A): 왼쪽 레일 | 명령 막대 + [매크로 목록 카드 | 정보·스텝·실행 기록 카드] + 아래 상태 줄."""
        from .design import theme as _theme
        from .widgets import MacroRowDelegate, NavRail, StepRowDelegate, card, label
        t = _theme.current()
        try:
            from PySide6.QtGui import QIcon
            from .design.assets import pixmap
            self.setWindowIcon(QIcon(pixmap("mouse-pointer-click", t["accent"], 32)))
        except Exception:
            pass
        central = QWidget()
        central.setObjectName("Root")
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.nav = NavRail(
            [("macros", "list-tree", tr("매크로")), ("history", "rotate-ccw-clock", tr("실행 기록")),
             ("schedule", "calendar-clock", tr("예약")), ("repairs", "wrench", tr("고침 기록")),
             ("approvals", "shield-check", tr("승인 대기")), ("ai", "bot", tr("AI 도우미"))],
            [("settings", "settings", tr("설정")), ("help", "circle-question-mark", tr("도움말"))])
        self.nav.set_current("macros")
        self.nav.triggered.connect(self._on_nav)
        outer.addWidget(self.nav)
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)
        self._body_layout = body

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(tr("매크로 검색 (Ctrl+F)"))
        self.search_edit.textChanged.connect(self._filter)
        self.search_edit.setClearButtonEnabled(True)
        try:
            from .design.assets import icon as _icon
            self.search_edit.addAction(_icon("search", t["muted"], 16), QLineEdit.LeadingPosition)
        except Exception:
            pass

        pad, gap = t["pad"], t["gap"]
        content = QWidget()
        ch = QHBoxLayout(content)
        ch.setContentsMargins(pad, 2, pad, 8)
        ch.setSpacing(gap)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(gap)
        # 매크로가 하나도 없을 때의 첫 화면(세 갈래 안내). 안 A: 오른쪽 칸 자리 / 안 B: 목록까지 통째로
        from PySide6.QtWidgets import QStackedWidget
        from .welcome import WelcomePanel
        self.welcome_layout = (os.environ.get("MACRO_WELCOME_LAYOUT") or WELCOME_LAYOUT).upper()
        self.welcome = WelcomePanel(wide=self.welcome_layout == "B")
        self.welcome.record.connect(self.start_recording)
        self.welcome.ai.connect(self._ai_help)
        self.welcome.examples.connect(self.install_examples)
        self.welcome.new.connect(lambda: self.new_macro())
        self._welcome_stack = QStackedWidget()
        if self.welcome_layout == "B":
            self._welcome_stack.addWidget(splitter)
            self._welcome_stack.addWidget(self.welcome)
            ch.addWidget(self._welcome_stack)
        else:
            ch.addWidget(splitter)
        self._content = content

        # 왼쪽: 매크로 목록
        left = card()
        left.setMinimumWidth(280)
        left.setMaximumWidth(600)          # 큰 화면에서 목록이 끝없이 넓어져 이름과 상태가 멀어지지 않게
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 12, 8, 8)
        lv.setSpacing(4)
        head = QHBoxLayout()
        head.setContentsMargins(10, 0, 4, 2)
        self.list_title = label(tr("매크로"), "Section")
        head.addWidget(self.list_title)
        head.addStretch(1)
        lv.addLayout(head)
        self.macro_list = MacroTree()
        self.macro_list.setHeaderHidden(True)
        self.macro_list.setIndentation(20)            # 하위 매크로가 한 단계 안으로 들어간 게 보이게
        self.macro_list.setMouseTracking(True)
        self.macro_list.setStyleSheet("QTreeView::item:selected, QTreeView::item:hover, QTreeView::branch:selected"
                                      " { background: transparent; }")   # 고른 줄 표시는 줄 그리기에서
        self.macro_list.setItemDelegate(MacroRowDelegate(ROLE_KIND, ROLE_NAME, ROLE_META, self.macro_list))
        self.macro_list.itemSelectionChanged.connect(self._on_selected)
        self.macro_list.itemDoubleClicked.connect(self._on_double_clicked)
        self.macro_list.customContextMenuRequested.connect(self._context_menu)
        self.macro_list.moved.connect(self._on_moved)
        lv.addWidget(self.macro_list)
        bl = QHBoxLayout()
        bl.setSpacing(2)
        self.new_btn = QPushButton(tr("새 매크로"))
        self.edit_btn = QPushButton(tr("편집"))
        self.delete_btn = QPushButton(tr("삭제"))
        self.run_btn = QPushButton(tr("실행"))
        self.stop_btn = QPushButton(tr("중지"))
        self.stop_btn.setEnabled(False)
        for b, fn in ((self.new_btn, self.new_macro), (self.edit_btn, self.edit_macro),
                      (self.delete_btn, self.delete_macro), (self.run_btn, self._guarded(self.run_macro)),
                      (self.stop_btn, self._guarded(self.stop_macro))):
            b.clicked.connect(lambda _=False, f=fn: f())
            bl.addWidget(b)
        lv.addLayout(bl)
        splitter.addWidget(left)

        # 오른쪽: 정보 / 스텝 / 실행 기록
        right = QSplitter(Qt.Vertical)
        right.setHandleWidth(gap)
        info_box = card()
        iv = QVBoxLayout(info_box)
        iv.setContentsMargins(pad, pad - 4, pad, pad - 4)
        iv.setSpacing(8)
        top = QHBoxLayout()
        self.info_title = label(tr("매크로를 선택하세요"), "Title")
        top.addWidget(self.info_title, 1)
        self.info_run_btn = QPushButton(" " + tr("실행"))
        self.info_run_btn.setObjectName("Primary")
        self.info_run_btn.clicked.connect(lambda: self._info_run_clicked())
        self.info_run_note = label("", "Muted")     # '다른 매크로 실행 중' 안내
        self.info_run_note.hide()
        self.info_edit_btn = QPushButton(" " + tr("편집"))
        self.info_edit_btn.clicked.connect(lambda: self.edit_macro())
        self.info_hotkey_btn = QPushButton(" " + tr("핫키"))
        self.info_hotkey_btn.setToolTip(tr("이 매크로를 실행·정지할 키 정하기 (이 프로그램이 뒤에 있어도 먹음)"))
        self.info_hotkey_btn.clicked.connect(lambda: self.set_hotkeys())
        try:
            from .design.assets import icon as _icon
            self.info_run_btn.setIcon(_icon("play", t["on_accent"], 16))
            self.info_edit_btn.setIcon(_icon("pencil", t["text"], 16))
            self.info_hotkey_btn.setIcon(_icon("keyboard", t["text"], 16))
        except Exception:
            pass
        top.addWidget(self.info_run_note)
        top.addWidget(self.info_run_btn)
        top.addWidget(self.info_edit_btn)
        top.addWidget(self.info_hotkey_btn)
        iv.addLayout(top)
        self.info_label = QLabel(tr("왼쪽 목록에서 매크로를 고르면 할 일 목록이 여기 보여요."))
        self.info_label.setWordWrap(True)
        self.info_label.setTextFormat(Qt.RichText)
        self.info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        iv.addWidget(self.info_label)
        right.addWidget(info_box)

        steps_box = card()
        sv = QVBoxLayout(steps_box)
        sv.setContentsMargins(8, 12, 8, 8)
        sv.setSpacing(4)
        sh = QHBoxLayout()
        sh.setContentsMargins(10, 0, 10, 0)
        self.steps_title = label(tr("스텝"), "Section")
        sh.addWidget(self.steps_title)
        sh.addStretch(1)
        sh.addWidget(label(tr("실행 중인 스텝을 따라 강조"), "Muted"))
        sv.addLayout(sh)
        from .widgets import ChevronTree
        self.steps_view = ChevronTree()
        self.steps_view.setColumnCount(2)
        self.steps_view.setHeaderLabels([tr("스텝"), tr("결과")])
        self.steps_view.setHeaderHidden(True)
        self.steps_view.setIndentation(18)
        self.steps_view.setUniformRowHeights(True)
        self.steps_view.setItemDelegate(StepRowDelegate(parent=self.steps_view))
        self.steps_view.setColumnWidth(0, 560)
        sv.addWidget(self.steps_view)
        right.addWidget(steps_box)

        log_box = card()
        lgv = QVBoxLayout(log_box)
        lgv.setContentsMargins(pad - 4, 12, pad - 4, 8)
        lgv.setSpacing(4)
        lgv.addWidget(label(tr("실행 기록"), "Section"))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(3000)
        self.log_view.viewport().installEventFilter(self)
        self.log_view.viewport().setMouseTracking(True)
        self.log_view.setToolTip(tr("스텝 위치가 적힌 줄을 누르면 그 스텝으로 가요"))
        self.log_view.setStyleSheet(f"font-family: Consolas, '{t.get('family', '')}'; font-size: {t['font_small']}px;")
        lgv.addWidget(self.log_view)
        right.addWidget(log_box)
        right.setStretchFactor(0, 0)
        right.setStretchFactor(1, 3)
        right.setStretchFactor(2, 1)
        if self.welcome_layout == "B":
            splitter.addWidget(right)
        else:
            self._welcome_stack.addWidget(right)
            self._welcome_stack.addWidget(self.welcome)
            splitter.addWidget(self._welcome_stack)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([420, 700])

        self.statusBar = QStatusBar()
        self.statusBar.setSizeGripEnabled(False)
        self.setStatusBar(self.statusBar)
        try:                                     # 어느 판인지 늘 보이게(옛 판·새 판 구분)
            from .build_info import short as _ver
            self.version_label = QLabel(tr("판: ") + _ver())
            self.version_label.setObjectName("Muted")
            self.statusBar.addPermanentWidget(self.version_label)
        except Exception:
            pass
        self.emergency_label = QLabel()
        self.emergency_label.setObjectName("Muted")
        self.statusBar.addPermanentWidget(self.emergency_label)
        if self.emergency_hotkey:
            self.emergency_label.setText(tr("비상 정지 {key}").format(key=self.emergency_hotkey.title()) + "   ")
        self._build_toolbar()
        body.addWidget(content, 1)
        for b in (self.new_btn, self.edit_btn, self.delete_btn, self.run_btn, self.stop_btn):
            b.setVisible(False)          # 같은 기능이 위 명령 막대에 있음(시험·단축키용으로 객체는 남김)

    def _build_toolbar(self):
        """명령 막대: 제목 · [새 매크로] 녹화 | 실행 정지 | 편집 핫키 예약 복사본 삭제 | 검색 · AI 연결하기."""
        from PySide6.QtGui import QAction
        from .design import theme as _theme
        from .widgets import command_button, label, separator
        t = _theme.current()
        bar = QWidget()
        bar.setObjectName("Bar")
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(t["pad"], 14, t["pad"], 10)
        bh.setSpacing(6)
        bh.addWidget(label(tr("매크로"), "Title"))
        bh.addSpacing(12)
        items = [("새 매크로", "+", "#185FA5", self.new_macro, "새 매크로 만들기 (Ctrl+N)"),
                 ("편집", "✎", "#444441", self.edit_macro, "고른 매크로 편집 (Ctrl+E, 더블클릭)"),
                 ("녹화", "●", "#A32D2D", self.start_recording, "마우스·키보드를 녹화해 새 매크로로 (시작: 이 단추 또는 창이 앞에 있을 때 F9 / 끝내기: 어디서나 F9)"),
                 ("실행", "▶", "#3B6D11", self._guarded(self.run_macro), "고른 매크로 실행 (F5 — 이 창이 앞에 있을 때만. 다른 창을 쓰는 중에도 실행하려면 [핫키]로 매크로에 키를 정하세요)"),
                 ("정지", "■", "#A32D2D", self._guarded(self.stop_macro), "실행 정지 (Shift+F5, 어디서나 Ctrl+Shift+F12)"),
                 ("핫키", "⌨", "#444441", self.set_hotkeys, "이 매크로를 실행·정지할 키 정하기 (이 프로그램이 뒤에 있어도 먹음)"),
                 ("예약", "◷", "#444441", self.open_schedules, "정해진 시각·간격으로 자동 실행(이 프로그램이 켜져 있을 때)"),
                 ("복사본", "⧉", "#444441", self.duplicate_macro, "복사본 만들기 (Ctrl+D)"),
                 ("삭제", "✕", "#444441", self.delete_macro, "고른 매크로 삭제"),
                 ("실행 기록", "☰", "#444441", self._open_trace_folder, "실행 기록(JSONL) 폴더 열기"),
                 ("AI 연결하기", "✦", "#534AB7", self._ai_help, "Claude·Codex·제미나이·Cursor 등 AI에 MCP 로 연결해 매크로를 만들게 하는 방법"),
                 ("도움말", "?", "#444441", self._show_help, "사용법")]
        self.tool_actions = {}
        for label_, glyph, color, fn, tip in items:
            ic = tool_icon(glyph, color)
            if label_ == "새 매크로":                  # 강조 단추 위 아이콘은 강조색 위 글자색
                from .design.assets import icon as _icon
                ic = _icon("plus", t["on_accent"], 18)
            a = QAction(ic, tr(label_), self)
            a.setToolTip(tr(tip))
            a.triggered.connect(lambda _=False, f=fn: f())
            self.tool_actions[label_] = a
        A = self.tool_actions
        bh.addWidget(command_button(A["새 매크로"], primary=True))
        bh.addWidget(command_button(A["녹화"]))
        bh.addWidget(separator())
        bh.addWidget(command_button(A["실행"]))
        bh.addWidget(command_button(A["정지"]))
        bh.addWidget(separator())
        bh.addWidget(command_button(A["편집"]))
        bh.addWidget(command_button(A["핫키"], text_beside=False))
        bh.addWidget(command_button(A["예약"], text_beside=False))
        bh.addWidget(command_button(A["복사본"], text_beside=False))
        bh.addWidget(command_button(A["삭제"], text_beside=False))
        bh.addStretch(1)
        self.search_edit.setMinimumWidth(110)
        self.search_edit.setMaximumWidth(260)
        bh.addWidget(self.search_edit, 1)
        bh.addWidget(command_button(A["AI 연결하기"]))
        self.toolbar = bar
        self._body_layout.addWidget(bar)
        A["정지"].setEnabled(False)

    def _on_nav(self, key: str):
        """왼쪽 레일 항목."""
        if key == "macros":
            self.search_edit.setFocus()
        elif key == "history":
            self._open_trace_folder()
        elif key == "schedule":
            self.open_schedules()
        elif key == "repairs":
            self.show_repairs()
        elif key == "approvals":
            self.show_approvals()
        elif key == "ai":
            self.show_ai_settings()
        elif key == "help":
            self._show_help()
        elif key == "settings":
            self._settings_menu().exec(self.nav.buttons["settings"].mapToGlobal(self.nav.buttons["settings"].rect().topRight()))

    def _settings_menu(self):
        """설정: 화면(테마·촘촘함·글자 크기·움직임) + 기존 설정 메뉴와 같은 항목."""
        from .design import theme as _theme
        m = QMenu(self)
        cur = {"theme": _theme.pref("theme", "system"), "density": _theme.pref("density", "comfortable"),
               "scale": _theme.pref("scale", 1.0), "motion": _theme.pref("motion", "auto")}
        sub = m.addMenu(tr("테마"))
        for code, lab in (("system", tr("윈도우 설정 따라")), ("light", tr("밝게")), ("dark", tr("어둡게"))):
            a = sub.addAction(lab, lambda c=code: self._set_view_pref("theme", c))
            a.setCheckable(True)
            a.setChecked(cur["theme"] == code)
        sub = m.addMenu(tr("촘촘함"))
        for code, lab in (("comfortable", tr("편안하게")), ("compact", tr("촘촘하게"))):
            a = sub.addAction(lab, lambda c=code: self._set_view_pref("density", c))
            a.setCheckable(True)
            a.setChecked(cur["density"] == code)
        sub = m.addMenu(tr("글자 크기"))
        for sc in (0.9, 1.0, 1.15, 1.3):
            a = sub.addAction(f"{int(sc * 100)}%", lambda s=sc: self._set_view_pref("scale", s))
            a.setCheckable(True)
            a.setChecked(abs(float(cur["scale"]) - sc) < 0.01)
        sub = m.addMenu(tr("움직임"))
        for code, lab in (("auto", tr("윈도우 설정 따라")), ("on", tr("켜기")), ("off", tr("줄이기(끄기)"))):
            a = sub.addAction(lab, lambda c=code: self._set_view_pref("motion", c))
            a.setCheckable(True)
            a.setChecked(cur["motion"] == code)
        m.addSeparator()
        for a in self.settings_menu.actions():
            m.addAction(a)
        return m

    def _set_view_pref(self, key: str, value):
        from .design import theme as _theme
        _theme.set_pref(key, value)
        if key == "motion":
            return
        if QMessageBox.question(self, tr("설정"), tr("바뀐 화면 설정은 프로그램을 다시 켜야 전체에 적용됩니다.\n지금 다시 켤까요?")) == QMessageBox.Yes:
            self._restart_app()

    # ================================================================ 녹화
    def _f9_in_window(self):
        """창이 앞에 있을 때 F9 = 녹화 시작(끝내기 F9 는 녹화 중 어디서나). 매크로 핫키가 F9 면 그쪽이 우선."""
        if self._recorder is not None:
            return
        owner = next((n for n, (r, s_) in self.store.hotkeys().items() if "f9" in (r, s_)), None)
        if owner:
            self.statusBar.showMessage(tr("F9 는 '{name}' 의 핫키라서 녹화는 위쪽 [녹화] 단추로 시작하세요").format(name=owner), 8000)
            return
        self.start_recording()

    def start_recording(self):
        if self._recorder is not None:
            return
        if QMessageBox.question(self, tr("녹화"),
                                tr("지금부터 마우스 클릭·끌기와 키 입력을 녹화합니다.\n"
                                   "이 창은 작게 줄어듭니다. 끝내려면 F9 를 누르세요.\n\n"
                                   "좌표는 화면 기준으로 저장됩니다(창이 움직이면 맞지 않을 수 있음).\n"
                                   "녹화를 시작할까요?")) != QMessageBox.Yes:
            return
        from gui.v2.recorder import Recorder
        self._recorder = Recorder(on_stop=lambda steps: self.record_done.emit(steps))
        self.showMinimized()
        QTimer.singleShot(600, self._recorder.start)    # 줄어드는 동안의 클릭은 안 받음
        self.statusBar.showMessage(tr("녹화 중… 끝내려면 F9"))

    def _on_record_done(self, steps: list):
        self._recorder = None
        self.showNormal()
        self.raise_()
        self.activateWindow()
        if not steps:
            QMessageBox.information(self, tr("녹화"), tr("받아 적은 동작이 없습니다."))
            return
        import time as _t
        from engine.model import new_macro
        name = self.store.unique_name(tr("녹화_") + _t.strftime("%m%d_%H%M"))
        m = new_macro(name, [{"type": "comment", "text": tr("녹화로 만든 매크로(화면 좌표). 필요하면 클릭을 그림 대상으로 바꾸세요")},
                             *steps], description=tr("녹화로 만든 매크로"))
        try:
            name = self.store.add(m)            # 11-19: 그때 골라 둔 묶음(예시 등)이 아니라 맨 위에(묶음 밖) 저장
        except Exception as e:
            QMessageBox.warning(self, tr("녹화"), tr("저장 실패: {e}").format(e=e))
            return
        self.log(tr("녹화 끝: '{name}' 스텝 {n}개 — 목록 맨 위(묶음 밖)에 저장했어요. 묶음에 넣으려면 끌어다 놓으세요.").format(name=name, n=len(steps)))
        self.reload_list(select=name)
        self.edit_macro(name)

    # ================================================================ 예약
    def open_schedules(self):
        from gui.v2 import schedule as sch
        d = QDialog(self)
        d.setWindowTitle(tr("예약 실행"))
        d.resize(760, 380)
        v = QVBoxLayout(d)
        note = QLabel(tr("이 프로그램이 켜져 있는 동안 정해진 시각(매일)이나 간격으로 매크로를 실행합니다. "
                         "다른 매크로가 실행 중이면 그 차례는 건너뜁니다."))
        note.setWordWrap(True)
        v.addWidget(note)
        from PySide6.QtWidgets import QComboBox, QListWidget, QSpinBox, QTimeEdit
        from PySide6.QtCore import QTime
        lst = QListWidget()
        v.addWidget(lst, 1)
        items = sch.load(self.store.root)

        def refresh():
            lst.clear()
            for it in items:
                lst.addItem(sch.describe(it))

        row = QHBoxLayout()
        from .macro_picker import MacroPicker, PickerSource
        mc = MacroPicker(lambda: PickerSource.from_store(self.store, recent=self._recent_names(10)),
                         current=self.current_name() or "", title=tr("예약할 매크로 고르기"))
        mc.setMinimumWidth(280)
        self._schedule_picker = mc               # 시험용
        mode = QComboBox()
        mode.addItem(tr("매일 이 시각"), "daily")
        mode.addItem(tr("몇 분마다"), "every")
        te = QTimeEdit(QTime(9, 0))
        te.setDisplayFormat("HH:mm")
        sp = QSpinBox()
        sp.setRange(1, 1440)
        sp.setValue(60)
        sp.setSuffix(tr(" 분"))
        sp.setVisible(False)
        mode.currentIndexChanged.connect(lambda _=None: (te.setVisible(mode.currentData() == "daily"),
                                                         sp.setVisible(mode.currentData() == "every")))
        add_b = QPushButton(tr("추가"))
        for wdg in (mc, mode, te, sp, add_b):
            row.addWidget(wdg)
        v.addLayout(row)
        row2 = QHBoxLayout()
        tog_b = QPushButton(tr("켜기/끄기"))
        del_b = QPushButton(tr("삭제"))
        close_b = QPushButton(tr("닫기"))
        row2.addWidget(tog_b)
        row2.addWidget(del_b)
        row2.addStretch(1)
        row2.addWidget(close_b)
        v.addLayout(row2)

        def add():
            if not mc.name():
                if not mc.pick():
                    return
            it = {"macro": mc.name(), "mode": mode.currentData(), "on": True, "last": 0}
            if it["mode"] == "daily":
                it["time"] = te.time().toString("HH:mm")
            else:
                it["minutes"] = sp.value()
                import time as _t
                it["last"] = _t.time()            # 지금부터 N분 뒤 첫 실행
            items.append(it)
            sch.save(self.store.root, items)
            refresh()

        def toggle():
            i = lst.currentRow()
            if 0 <= i < len(items):
                items[i]["on"] = not items[i].get("on", True)
                sch.save(self.store.root, items)
                refresh()

        def delete():
            i = lst.currentRow()
            if 0 <= i < len(items):
                items.pop(i)
                sch.save(self.store.root, items)
                refresh()
        add_b.clicked.connect(add)
        tog_b.clicked.connect(toggle)
        del_b.clicked.connect(delete)
        close_b.clicked.connect(d.accept)
        refresh()
        d.exec()

    def _check_schedules(self):
        from gui.v2 import schedule as sch
        import time as _t
        try:
            items = sch.load(self.store.root)
        except Exception:
            return
        if not items or self.is_running():
            return
        for it in items:
            if sch.due(it) and it.get("macro") in self.store.names():
                it["last"] = _t.time()
                sch.save(self.store.root, items)
                self.log(tr("예약 실행: {name}").format(name=it['macro']))
                self.run_macro(it["macro"])
                return

    def _ai_help(self):
        """여러 AI 프로그램에 MCP 서버를 붙이는 설정 글 + 공통 요청 글."""
        from .ai_connect import show_dialog
        show_dialog(self)

    def _build_menus(self):
        """메뉴: 처음 보는 사람이 '여기 있겠지' 하는 자리에(2026-11-17 개편).
        파일(만들기·폴더) / 매크로(고른 매크로 다루기) / 실행 / 보기(목록·기록) / 설정(언어·AI·점검) / 도움말(안내만)."""
        mb = self.menuBar()
        m = mb.addMenu(tr("파일"))
        m.addAction(tr("새 매크로"), self.new_macro, QKeySequence("Ctrl+N"))
        m.addAction(tr("녹화해서 새 매크로"), self.start_recording)
        m.addAction(tr("새 그룹"), self.new_group)
        m.addSeparator()
        m.addAction(tr("매크로 폴더 열기"), lambda: self._open_folder(self.store.root))
        m.addSeparator()
        m.addAction(tr("매크로 내보내기(파일 하나로)…"), self.export_pack)
        m.addAction(tr("매크로 가져오기…"), self.import_pack)
        m.addSeparator()
        m.addAction(tr("종료"), self.close)

        m = mb.addMenu(tr("매크로"))
        m.addAction(tr("편집"), self.edit_macro, QKeySequence("Ctrl+E"))
        m.addAction(tr("이름 바꾸기"), self.rename_macro, QKeySequence("F2"))
        m.addAction(tr("복사본 만들기"), self.duplicate_macro, QKeySequence("Ctrl+D"))
        m.addAction(tr("삭제"), self.delete_macro)
        m.addSeparator()
        m.addAction(tr("핫키 설정"), self.set_hotkeys)
        m.addAction(tr("예약 실행"), self.open_schedules)

        m = mb.addMenu(tr("실행"))
        self.menu_run_action = m.addAction(tr("실행"), self.run_macro, QKeySequence("F5"))
        self.menu_stop_action = m.addAction(tr("정지"), self.stop_macro, QKeySequence("Shift+F5"))
        self.menu_stop_action.setEnabled(False)
        m.addAction(tr("멈춤 지킴이…"), self.show_guard)
        m.addSeparator()
        self.minimize_action = m.addAction(tr("실행할 때 이 창 최소화"))
        self.minimize_action.setCheckable(True)
        self.minimize_action.setChecked(self.settings.value("minimize_on_run", True, type=bool))
        self.minimize_action.toggled.connect(lambda v: self.settings.setValue("minimize_on_run", v))

        m = mb.addMenu(tr("보기"))
        m.addAction(tr("목록 새로 고침"), self.reload_list, QKeySequence("Ctrl+R"))
        self.parts_action = m.addAction(tr("불러 쓰는 매크로를 아래 트리로 묶어 보기"))
        self.parts_action.setCheckable(True)
        self.parts_action.setChecked(self.settings.value("call_tree", True, type=bool))
        self.parts_action.toggled.connect(lambda v: (self.settings.setValue("call_tree", v), self.reload_list()))
        m.addSeparator()
        m.addAction(tr("실행 기록 폴더 열기"), self._open_trace_folder)
        m.addAction(tr("AI 도우미 기록"), self.show_ai_log)
        m.addAction(tr("고침 기록"), self.show_repairs)
        self.approval_action = m.addAction(tr("승인 대기함"), self.show_approvals)

        m = mb.addMenu(tr("설정"))
        self.settings_menu = m
        lang_label = tr("언어")
        lm = m.addMenu(lang_label if lang_label == "Language" else lang_label + " (Language)")   # 못 읽는 언어여도 찾게
        note = lm.addAction(tr("바꾸면 프로그램을 다시 켜야 적용됩니다"))
        note.setEnabled(False)
        lm.addSeparator()
        from gui.v2 import i18n
        for code, label in i18n.LANGS.items():
            act = lm.addAction(label, lambda c=code: self._set_language(c))
            act.setCheckable(True)
            act.setChecked(i18n.current() == code)
        m.addSeparator()
        m.addAction(tr("AI 연결하기"), self._ai_help)
        m.addAction(tr("AI 도우미 설정"), self.show_ai_settings)
        m.addAction(tr("메일 계정"), self.show_mail_accounts)
        m.addAction(tr("부가 기능"), self.show_addons)
        self.finder_action = m.addAction(tr("메모리 에디터(혼자 하는 게임용)…"), self.show_memory_finder)
        from .icons import memory_on as _mon
        self.finder_action.setVisible(_mon())       # 부가 기능을 켠 사람에게만
        # 11-19: 값 지켜보기·조건 실행은 숨김(코드는 남김). 메모리는 '메모리 에디터' 창만
        self._mem_watcher = None
        m.addSeparator()
        m.addAction(tr("환경 점검"), self.show_env_check)

        m = mb.addMenu(tr("도움말"))
        m.addAction(tr("사용법"), self._show_help)
        m.addAction(tr("예시 매크로 넣기"), self.install_examples)
        m.addAction(tr("뒤에서 실행이란"), self._show_background_help)
        from . import hwp_setup as _hs
        m.addAction(tr("한글 자동화 설정"), lambda: _hs.show_guide(self))
        m.addSeparator()
        m.addAction(tr("문제·의견 보내기"), self._send_feedback)
        m.addAction(tr("이 프로그램 정보"), self.show_about)

    def _send_feedback(self):
        from .feedback import show_dialog
        show_dialog(self)

    def show_addons(self):
        """부가 기능 켜고 끄기(기본 꺼짐). 지금은 메모리 매크로 하나."""
        from PySide6.QtWidgets import QCheckBox, QDialogButtonBox
        from engine import memory as mm
        d = QDialog(self)
        d.setWindowTitle(tr("부가 기능"))
        v = QVBoxLayout(d)
        cb = QCheckBox(tr("메모리 에디터(혼자 하는 게임용)"))
        cb.setChecked(mm.enabled())
        v.addWidget(cb)
        h = QLabel(tr("보호 장치가 없는 혼자 하는 게임에서, 게임이 켜져 있는 동안 돈·체력 같은 값을 찾아 바꾸거나 고정합니다.\n"
                      "게임을 다시 켜면 값을 다시 찾아야 해요(지난번 찾은 값 이름은 기억해 두고 다시 찾기를 도와요).\n"
                      "켜면 설정 메뉴에 '메모리 에디터'가 생깁니다. 온라인 게임에는 쓰지 마세요."))
        h.setWordWrap(True)
        h.setObjectName("Muted")
        v.addWidget(h)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        v.addWidget(bb)
        self._addons_dialog = d                  # 시험용
        if d.exec():
            mm.set_enabled(cb.isChecked())
            if hasattr(self, "finder_action"):
                self.finder_action.setVisible(cb.isChecked())
            self.statusBar.showMessage(tr("부가 기능 설정을 저장했습니다(열려 있는 편집기는 다시 열면 반영)"), 6000)

    def _guard_start(self, name: str):
        """실행 시작을 지킴이 상태에 적고, 이 매크로에 지킴이를 켰으면 지킴이를 띄운다."""
        try:
            from engine import guard
            cfg = guard.load_settings().get(name) or {}
            guard.mark_started(name, os.getpid(), bool(cfg.get("on")), float(cfg.get("stall_min", 10)),
                               bool(cfg.get("restart_on_stall")))
            if cfg.get("on") and not getattr(self, "_no_guard_spawn", False):
                guard.spawn_guard()
        except Exception:
            pass

    def show_guard(self):
        """멈춤 지킴이 설정(고른 매크로) + 오늘 실적."""
        from PySide6.QtWidgets import QCheckBox, QDialogButtonBox, QDoubleSpinBox, QFormLayout
        from engine import guard
        name = self.current_name()
        if not name:
            QMessageBox.information(self, tr("멈춤 지킴이"), tr("지킬 매크로를 고르세요."))
            return
        cfg = guard.load_settings().get(name) or {}
        d = QDialog(self)
        d.setWindowTitle(tr("멈춤 지킴이 — {name}").format(name=name))
        v = QVBoxLayout(d)
        tip = QLabel(tr("오래 도는 매크로가 멈추거나 프로그램이 꺼지면 알아채서 알리고 다시 켭니다. "
                        "사람이 정지 단추·키로 멈추거나 프로그램을 닫으면 다시 켜지 않아요."))
        tip.setWordWrap(True)
        v.addWidget(tip)
        f = QFormLayout()
        on = QCheckBox(tr("이 매크로를 지키기"))
        on.setChecked(bool(cfg.get("on")))
        stall = QDoubleSpinBox()
        stall.setRange(1, 240)
        stall.setValue(float(cfg.get("stall_min", 10)))
        stall.setSuffix(tr(" 분"))
        rs = QCheckBox(tr("멈춤 때도 다시 켜기(아니면 알림만)"))
        rs.setChecked(bool(cfg.get("restart_on_stall")))
        f.addRow(on)
        f.addRow(tr("실행 기록이 이만큼 안 늘면 멈춤으로 봄"), stall)
        f.addRow(rs)
        v.addLayout(f)
        s = guard.summary()
        v.addWidget(QLabel(tr("오늘: 실행 {runs}번 · 완료 {ok} · 실패 {failed} · 사람이 멈춤 {stopped} · 다시 켬 {restarts} · 멈춤 의심 {stalls}").format(**s)))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        v.addWidget(bb)
        self._guard_dialog = d                   # 시험용
        if d.exec():
            guard.save_setting(name, {"on": True, "stall_min": stall.value(), "restart_on_stall": rs.isChecked()}
                               if on.isChecked() else None)
            self.statusBar.showMessage(tr("'{name}' 멈춤 지킴이 {s}").format(name=name, s=tr("켬") if on.isChecked() else tr("끔")), 6000)

    def _image_root(self):
        return os.path.join(os.path.dirname(os.path.abspath(self.store.root)), "image")

    def export_pack(self):
        """고른 매크로 + 부르는 매크로 + 쓰는 그림을 파일 하나(.macropack)로."""
        from PySide6.QtWidgets import QFileDialog
        from engine import pack
        name = self.current_name()
        if not name:
            QMessageBox.information(self, tr("매크로 내보내기"), tr("내보낼 매크로를 고르세요."))
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("매크로 내보내기"), name + pack.EXT, tr("매크로 묶음 (*.macropack)"))
        if not path:
            return
        r = pack.export(self.store, name, path, self._image_root())
        msg = tr("내보냈어요: 매크로 {n}개({names}), 그림 {i}개\n{p}").format(
            n=len(r["macros"]), names=", ".join(r["macros"]), i=r["images"], p=r["path"])
        if r["missing"]:
            msg += "\n" + tr("찾지 못한 그림: {m}").format(m=", ".join(r["missing"][:5]))
        QMessageBox.information(self, tr("매크로 내보내기"), msg)

    def import_pack(self):
        from PySide6.QtWidgets import QFileDialog
        from engine import pack
        path, _ = QFileDialog.getOpenFileName(self, tr("매크로 가져오기"), "", tr("매크로 묶음 (*.macropack)"))
        if not path:
            return
        try:
            r = pack.import_pack(self.store, path, self._image_root(), group=self.current_group())
        except Exception as e:
            QMessageBox.warning(self, tr("매크로 가져오기"), tr("가져오지 못했어요: {e}").format(e=e))
            return
        msg = tr("가져왔어요: {names}").format(names=", ".join(r["added"]))
        if r["renamed"]:
            msg += "\n" + tr("이름이 겹쳐 바꿔 넣음: {r}").format(r=", ".join(f"{a} → {b}" for a, b in r["renamed"].items()))
        for w_ in r["warnings"]:
            msg += "\n⚠ " + w_
        self.reload_list(select=r.get("main"))
        QMessageBox.information(self, tr("매크로 가져오기"), msg)

    def show_memory_watch(self):
        from .memory_watch import MemoryWatchDialog
        d = MemoryWatchDialog(self, lambda: [n for n in self.store.names() if not n.startswith("_")])
        self._memory_watch_dialog = d            # 시험용
        d.exec()

    def _memory_watch_tick(self):
        """값 지켜보기 규칙대로 읽기·기록·조건 실행(부가 기능을 켰고 규칙이 있을 때만, 읽기만)."""
        from .icons import memory_on
        if not memory_on():
            return
        try:
            from engine import memwatch as mw
            if not mw.load_rules():
                return
            if self._mem_watcher is None:
                def run(name):
                    if not self.is_running() and name in self.store.names():
                        self.run_macro(name)

                def notify(title, msg):
                    self.statusBar.showMessage(tr("값 지켜보기: {m}").format(m=msg), 8000)
                    try:
                        from engine import notify as nt
                        nt.send(tr("값 지켜보기"), msg, channels=("toast",), source=tr("메모리 매크로"))
                    except Exception:
                        pass
                self._mem_watcher = mw.Watcher(run_macro=run, notify=notify)
            self._mem_watcher.tick()
        except Exception:
            pass

    def show_memory_finder(self):
        from .memory_finder import MemoryFinder
        d = MemoryFinder(self)
        self._memory_finder = d                  # 시험용
        d.exec()

    def show_about(self):
        from .build_info import text
        QMessageBox.information(self, tr("이 프로그램 정보"), text())

    def show_env_check(self, modal: bool = True):
        from . import env_check
        return env_check.show_dialog(self, self.store.root, modal=modal)

    def show_mail_accounts(self):
        """설정 → 메일 계정(메일 서버 직접 연결). 비밀번호는 윈도우 자격 증명에만."""
        from .mail_accounts import MailAccountsDialog
        MailAccountsDialog(os.path.dirname(self.store.root), self).exec()

    def show_ai_settings(self):
        """막힘 해결용 명령줄 AI 고르기(이 컴퓨터마다 저장)."""
        from engine.rescue import CliAI, load_ai_config, save_ai_config
        from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout)
        cfg = load_ai_config(self.store.root)
        d = QDialog(self)
        d.setWindowTitle(tr("AI 도우미 설정"))
        d.resize(560, 380)
        v = QVBoxLayout(d)
        intro = QLabel(tr("매크로가 막혔을 때 한 번 부를 이 컴퓨터의 AI 프로그램을 고릅니다. 로그인은 그 프로그램이 이미 해 둔 것을 씁니다."))
        intro.setWordWrap(True)
        v.addWidget(intro)
        f = QFormLayout()
        combo = QComboBox()
        # codex·gemini 는 아직 실제로 돌려 확인하지 않음(도구 잠금도 덜 됨) → '시험 중' 표시, 자동 선택에서 뺌
        for label, val in ((tr("자동 (claude)"), "auto"), ("claude", "claude"), (tr("codex (시험 중)"), "codex"),
                           (tr("gemini (시험 중)"), "gemini"), (tr("직접 입력"), "custom")):
            combo.addItem(label, val)
        cur = str(cfg.get("command") or "auto")
        idx = combo.findData(cur)
        custom = QLineEdit()
        custom.setPlaceholderText(tr("예: 프로그램 {prompt_file} {image}"))
        if idx < 0:
            idx = combo.findData("custom")
            custom.setText(cur)
        combo.setCurrentIndex(idx)
        custom.setEnabled(combo.currentData() == "custom")
        combo.currentIndexChanged.connect(lambda _=0: custom.setEnabled(combo.currentData() == "custom"))
        timeout = QLineEdit(str(int(cfg.get("timeout", 90) or 90)))
        timeout.setFixedWidth(80)
        model = QLineEdit(str(cfg.get("model") or "sonnet"))
        model.setFixedWidth(160)
        consent = QCheckBox(tr("막혔을 때 화면 사진과 실행 기록을 AI로 보내는 것에 동의"))
        consent.setChecked(cfg.get("consent") is True)
        found = QLabel()

        def refresh(_=0):
            c = dict(cfg)
            c["command"] = custom.text().strip() if combo.currentData() == "custom" else combo.currentData()
            name = CliAI(c).describe()
            found.setText(tr("찾은 명령줄 AI: {name}").format(name=name or tr("없음")))
        combo.currentIndexChanged.connect(refresh)
        custom.textChanged.connect(refresh)
        refresh()
        f.addRow(tr("사용할 AI"), combo)
        f.addRow(tr("직접 입력"), custom)
        f.addRow(tr("AI 모델"), model)
        f.addRow(tr("기다리는 시간(초)"), timeout)
        v.addLayout(f)
        v.addWidget(consent)
        heal = QCheckBox(tr("스스로 고치기 허용(값 조정·제안) — 매크로마다 켠 것만 고칩니다"))
        heal.setToolTip(tr("꺼 두면 매크로를 '값 조정까지'로 켜도 알림만 합니다. 바뀐 것은 보기 → 고침 기록에서 보고 되돌릴 수 있습니다."))
        heal.setChecked(cfg.get("self_heal_allowed") is True)
        v.addWidget(heal)
        usage = QLabel(tr("AI 프로그램의 구독 사용량을 씁니다."))
        usage.setStyleSheet("color:#666")
        v.addWidget(usage)
        v.addWidget(found)
        note = QLabel(tr("막혔을 때 그 순간의 화면 사진이 이 컴퓨터의 AI 프로그램으로 보내집니다. 화면에 개인정보가 보이면 함께 보내질 수 있습니다."))
        note.setWordWrap(True)
        note.setStyleSheet("color:#a05000")
        v.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        v.addWidget(bb)
        self._ai_dialog = d
        if d.exec() != QDialog.Accepted:
            return None
        new = dict(cfg)
        new["model"] = model.text().strip() or "sonnet"
        new["consent"] = consent.isChecked()
        new["self_heal_allowed"] = heal.isChecked()
        new["command"] = (custom.text().strip() or "auto") if combo.currentData() == "custom" else combo.currentData()
        try:
            new["timeout"] = max(10, int(timeout.text()))
        except ValueError:
            new["timeout"] = 90
        save_ai_config(self.store.root, new)
        return new

    # ---------------------------------------------------------------- 승인 대기함(스스로 고치기 4단계)
    def proposal_sentence(self, p: dict) -> str:
        """제안을 쉬운 문장으로: "'클릭: 이미지 확인버튼' 앞에 동작 2개를 추가: ① … ② …"."""
        from gui.v2.describe import step_text
        target = p.get("path", "")
        try:
            from engine.proposals import _locate
            lst, idx = _locate(self.store.load(p["macro"]), target)
            if lst is not None:
                target = step_text(lst[idx])
        except Exception:
            pass
        marks = "①②③④⑤⑥⑦⑧⑨"
        steps = p.get("steps") or []
        cond = ""
        if len(steps) == 1 and steps[0].get("type") == "if" and isinstance(steps[0].get("then"), list):
            from gui.v2.describe import cond_text
            c = steps[0].get("cond") or {}
            parts = c.get("all") if isinstance(c.get("all"), list) else [c]
            nots = [x for x in parts if isinstance(x.get("not"), dict) and (x["not"].get("exists") or {}).get("image")]
            sizes = [x["window_size"] for x in parts if "window_size" in x]
            if nots and len(nots) + len(sizes) == len(parts):
                from engine.runner import _pic
                img = nots[0]["not"]["exists"]["image"]
                if sizes:
                    cond = tr(" ('{p}' 그림이 안 보이고 창 크기가 {w}x{h} 일 때만)").format(p=_pic(img), w=sizes[0][0], h=sizes[0][1])
                else:
                    cond = tr(" ('{p}' 그림이 안 보일 때만)").format(p=_pic(img))
            else:
                cond = tr(" (조건: {c} 일 때만)").format(c=cond_text(c))
            steps = steps[0]["then"]
        acts = " ".join(f"{marks[i] if i < len(marks) else '-'} {step_text(s)}" for i, s in enumerate(steps)) + cond
        where = tr("앞에") if p.get("kind") == "insert_before" else tr("뒤에")
        detail = tr("이 스텝 {where} 동작 {n}개를 추가: '{target}' — {acts}").format(
            where=where, n=len(steps), target=target, acts=acts)
        if p.get("summary"):                             # 사람이 먼저 읽을 '하는 일'을 맨 위에, 자세한 동작은 아래
            return tr("하는 일: {s}").format(s=p["summary"]) + "\n" + tr("자세히: ") + detail
        return detail

    def proposal_diff(self, p: dict) -> str:
        """바뀐 내용 보기: 그 자리 앞뒤 스텝을 바꾸기 전/후로 나란히(쉬운 말)."""
        from gui.v2.describe import step_text
        from engine.proposals import _locate, apply
        cur = self.store.load(p["macro"])
        lst, idx = _locate(cur, p["path"])
        new = apply(cur, p)
        nlst, nidx = _locate(new, p["path"])
        if lst is None:
            return tr("이 매크로에서 그 자리를 찾지 못했습니다(매크로가 바뀌었을 수 있음).")
        lo = max(0, idx - 2)
        before = [("   " + step_text(s)) for s in lst[lo:idx + 3]]
        n = len(p.get("steps") or [])
        after = []
        for i, s in enumerate(nlst[lo:idx + 3 + n]):
            added = lo + i >= idx and lo + i < idx + n if p.get("kind") == "insert_before" else (idx < lo + i <= idx + n)
            after.append(("+  " if added else "   ") + step_text(s))
            if added and s.get("type") == "if":
                for c in s.get("then") or []:            # 만약 안의 동작도 펼쳐 보여 줌
                    after.append("+      " + step_text(c))
        return (tr("바꾸기 전") + "\n" + "\n".join(before) + "\n\n" + tr("바꾼 뒤 (+ 가 새로 들어가는 동작)") + "\n" + "\n".join(after))

    def refresh_approval_badge(self):
        try:
            from engine.proposals import pending_count
            n = pending_count(self.store.root)
        except Exception:
            n = 0
        self.approval_action.setText(tr("승인 대기함") + (f" ({n})" if n else ""))
        if getattr(self, "nav", None) is not None:
            self.nav.buttons["approvals"].set_badge(n)
        if n:
            self.statusBar.showMessage(tr("승인 대기 {n}건 — 보기 → 승인 대기함").format(n=n))

    def show_approvals(self):
        """승인 대기함: 매크로 구조를 바꾸는 제안. 승인해야만 반영(승인 전에는 원본이 그대로 돎)."""
        from engine.proposals import decide, load_all
        from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)
        rows = [p for p in load_all(self.store.root) if p.get("status") == "pending"]
        d = QDialog(self)
        d.setWindowTitle(tr("승인 대기함"))
        d.resize(940, 420)
        v = QVBoxLayout(d)
        v.addWidget(QLabel(tr("매크로 구조를 바꾸자는 제안입니다. 승인해야만 반영되고, 승인 전에는 원래 매크로가 그대로 돕니다.")))
        tbl = QTableWidget(len(rows), 4)
        tbl.setHorizontalHeaderLabels([tr("시각"), tr("매크로"), tr("바뀔 내용"), tr("이유")])
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        tbl.setWordWrap(True)
        for r, p in enumerate(rows):
            for c, val in enumerate((p.get("created"), p.get("macro"), self.proposal_sentence(p), p.get("why"))):
                tbl.setItem(r, c, QTableWidgetItem(str(val or "")))
        h = tbl.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        tbl.resizeRowsToContents()
        if rows:
            tbl.selectRow(0)
        v.addWidget(tbl, 1)
        if not rows:
            v.addWidget(QLabel(tr("승인을 기다리는 제안이 없습니다.")))
        row = QHBoxLayout()
        b_diff, b_ok, b_no = QPushButton(tr("바뀐 내용 보기")), QPushButton(tr("승인")), QPushButton(tr("거절"))
        for b in (b_diff, b_ok, b_no):
            b.setEnabled(bool(rows))
            row.addWidget(b)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(d.reject)
        row.addWidget(bb)
        v.addLayout(row)

        def cur():
            i = tbl.currentRow()
            return rows[i] if 0 <= i < len(rows) else None

        def show_diff():
            p = cur()
            if p:
                QMessageBox.information(d, tr("바뀐 내용 보기"), self.proposal_diff(p))

        def act(approve: bool):
            p = cur()
            if not p:
                return
            if approve and QMessageBox.question(d, tr("승인"), tr("이 제안을 '{name}' 에 반영할까요?\n(지금 매크로는 백업 폴더에 남깁니다)\n\n{s}").format(
                    name=p["macro"], s=self.proposal_sentence(p))) != QMessageBox.Yes:
                return
            try:
                out = decide(self.store.root, self.store.library if hasattr(self.store, "library") else _StoreLib(self.store),
                             p["id"], approve)
            except Exception as e:
                QMessageBox.warning(d, tr("승인 대기함"), str(e))
                return
            import os as _os
            from engine.real import PROJECT_ROOT
            from engine.repairs import append
            append(_os.path.join(PROJECT_ROOT, "logs", "repairs"), p["macro"], "proposal", out["status"],
                   {"id": p["id"], "path": p["path"], "steps": p["steps"], "backup": out.get("backup")},
                   message=(tr("승인: ") if approve else tr("거절: ")) + self.proposal_sentence(p))
            d.accept()
            self.reload_list(select=p["macro"])
            self.refresh_approval_badge()
        b_diff.clicked.connect(show_diff)
        b_ok.clicked.connect(lambda: act(True))
        b_no.clicked.connect(lambda: act(False))
        self._approval_dialog = d
        d.exec()

    def show_repairs(self):
        """고침 기록(스스로 고치기): 알아챈 신호·고친 것·결과. 최신이 위."""
        import os as _os
        from engine.real import PROJECT_ROOT
        from engine.repairs import load_all
        from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout)
        kinds = {"proposal": tr("구조 수정 제안"), "stall": tr("진전 없음"), "score_low": tr("인식 점수 하락"), "new_window": tr("처음 보는 창"),
                 "slow": tr("느려짐"), "recapture": tr("그림 다시 따기"), "confidence": tr("인식 기준 낮추기"),
                 "timeout": tr("기다리는 시간 늘리기")}
        states = {"notified": tr("알림"), "trial": tr("시험 반영 중"), "applied": tr("확정"), "reverted": tr("되돌림"),
                  "pending": tr("승인 대기"), "approved": tr("승인됨"), "rejected": tr("거절함"), "blocked": tr("안 함(안전 검사)")}
        rows = load_all(_os.path.join(PROJECT_ROOT, "logs", "repairs"))
        d = QDialog(self)
        d.setWindowTitle(tr("고침 기록"))
        d.resize(900, 460)
        v = QVBoxLayout(d)
        v.addWidget(QLabel(tr("매크로가 오래 돌며 알아챈 것과 고친 것입니다. 매크로 편집 창의 '스스로 고치기'에서 켭니다.")))
        tbl = QTableWidget(len(rows), 5)
        tbl.setHorizontalHeaderLabels([tr("시각"), tr("매크로"), tr("종류"), tr("내용"), tr("상태")])
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        tbl.setWordWrap(True)
        from engine.runner import repair_sentence

        def sentence(e):                                 # 값 조정 기록은 쉬운 문장으로 다시 만들어 보여 줌(예전 기록 포함)
            dt = e.get("detail") or {}
            if e.get("kind") in ("recapture", "confidence", "timeout") and e.get("status") in ("trial", "applied", "reverted"):
                tg = dt.get("target") or dt.get("image") or dt.get("step")
                if tg:
                    return repair_sentence(e["kind"], e["status"], tg, dt.get("old"), dt.get("new"), dt.get("why"))
            if e.get("kind") == "score_low" and dt.get("image"):
                from engine.runner import _pic
                from engine.i18n import t as _t
                return _t("'{p}' 그림이 아슬아슬하게 인식됨(평균 점수 {avg}, 기준 {conf})", p=_pic(dt["image"]),
                          avg=dt.get("avg"), conf=dt.get("confidence"))
            return e.get("message") or ""
        for r, e in enumerate(rows):
            vals = (e.get("at"), e.get("macro"), kinds.get(e.get("kind"), e.get("kind")),
                    sentence(e), states.get(e.get("status"), e.get("status")))
            for c, val in enumerate(vals):
                tbl.setItem(r, c, QTableWidgetItem("" if val is None else str(val)))
        h = tbl.horizontalHeader()
        for c in (0, 1, 2, 4):
            h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        tbl.resizeRowsToContents()
        v.addWidget(tbl, 1)
        if not rows:
            v.addWidget(QLabel(tr("아직 기록이 없습니다.")))
        from PySide6.QtWidgets import QHBoxLayout, QPushButton
        row = QHBoxLayout()
        undo = QPushButton(tr("고른 고침 되돌리기"))
        undo.setToolTip(tr("시험 반영 중이면 바로 원래대로, 확정된 것이면 바꾸기 전 매크로로 되돌립니다."))
        undo.clicked.connect(lambda: self._undo_repair(rows, tbl.currentRow(), d))
        row.addWidget(undo)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(d.reject)
        row.addWidget(bb)
        v.addLayout(row)
        self._repairs_dialog = d
        d.exec()

    def _undo_repair(self, rows, idx: int, dlg=None):
        """고침 기록에서 고른 줄 되돌리기: 시험 반영 중 → 원래대로 / 확정 → 백업 매크로로."""
        import os as _os
        import shutil as _sh
        from engine.real import PROJECT_ROOT
        from engine.repairs import append
        if idx < 0 or idx >= len(rows):
            QMessageBox.information(self, tr("고침 기록"), tr("되돌릴 줄을 고르세요."))
            return
        e = rows[idx]
        name, status, det = e.get("macro", ""), e.get("status"), e.get("detail") or {}
        root = _os.path.join(PROJECT_ROOT, "logs", "repairs")
        if status == "trial":
            from engine.tuning import Tuner
            tu = Tuner(self.store.root, name)
            if tu.revert(tr("사람이 되돌림")):
                append(root, name, e.get("kind", ""), "reverted", det, message=tr("사람이 시험 반영을 되돌림"))
                QMessageBox.information(self, tr("고침 기록"), tr("시험 반영을 되돌렸습니다."))
            else:
                QMessageBox.information(self, tr("고침 기록"), tr("이미 끝난 시험입니다."))
        elif status == "applied" and det.get("backup") and _os.path.exists(det["backup"]):
            if QMessageBox.question(self, tr("고침 기록"), tr("'{name}' 을 이 고침 전으로 되돌릴까요?\n(지금 매크로 파일은 백업 폴더에 따로 남깁니다)").format(name=name)) != QMessageBox.Yes:
                return
            cur = self.store.path(name) if hasattr(self.store, "path") else None
            if cur and _os.path.exists(cur):
                import time as _t
                bdir = _os.path.join(_os.path.dirname(cur), "_backup")
                _os.makedirs(bdir, exist_ok=True)
                _sh.copy2(cur, _os.path.join(bdir, f"{_os.path.splitext(_os.path.basename(cur))[0]}_{_t.strftime('%Y%m%d_%H%M%S')}_before_revert.json"))
                _sh.copy2(det["backup"], cur)
            append(root, name, e.get("kind", ""), "reverted", det, message=tr("사람이 확정한 고침을 되돌림"))
            QMessageBox.information(self, tr("고침 기록"), tr("되돌렸습니다."))
            self.reload_list(select=name)
        else:
            QMessageBox.information(self, tr("고침 기록"), tr("이 줄은 되돌릴 것이 없습니다(알림이거나 이미 되돌림)."))
            return
        if dlg is not None:
            dlg.accept()

    def show_ai_log(self):
        """AI 도우미 기록(읽기 전용, 최신이 위)."""
        import json as _json
        import os as _os
        from engine.real import PROJECT_ROOT
        from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout)
        names = {"ai_saved": tr("AI가 고쳐 저장함"), "ai_rejected": tr("AI 답을 거절함"),
                 "ai_failed": tr("AI 답으로도 안 풀림"), "ai_error": tr("AI 호출 오류"),
                 "blocked": tr("횟수 한도·반복 방지로 부르지 않음"), "rule": tr("저장된 해결 규칙으로 해결"),
                 "rule_off": tr("해결 규칙 꺼져 있어 건너뜀"), "no_consent": tr("동의가 없어 부르지 않음")}
        rows = []
        try:
            with open(_os.path.join(PROJECT_ROOT, "logs", "ai_rescue", "log.jsonl"), encoding="utf-8") as fh:
                for line in fh:
                    try:
                        rows.append(_json.loads(line))
                    except Exception:
                        pass
        except Exception:
            pass
        rows.reverse()

        def flat(x):
            if isinstance(x, (list, tuple)):
                return "; ".join(flat(i) for i in x)
            if isinstance(x, dict):
                return _json.dumps(x, ensure_ascii=False)
            return "" if x is None else str(x)
        d = QDialog(self)
        d.setWindowTitle(tr("AI 도우미 기록"))
        d.resize(960, 480)
        v = QVBoxLayout(d)
        tbl = QTableWidget(len(rows), 6)
        tbl.setHorizontalHeaderLabels([tr("시각"), tr("매크로"), tr("스텝"), tr("결과"), tr("이유"), tr("스텝 요약·문제점")])
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        tbl.setWordWrap(True)
        for r, e in enumerate(rows):
            how = str(e.get("how", ""))
            detail = flat(e.get("steps"))
            if e.get("problems"):
                detail = (detail + " / " if detail else "") + flat(e.get("problems"))
            for c, val in enumerate((e.get("at"), e.get("macro"), e.get("step"), names.get(how, how),
                                     e.get("why") or e.get("reason"), detail)):
                tbl.setItem(r, c, QTableWidgetItem(flat(val)))
        h = tbl.horizontalHeader()
        for c in range(5):
            h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(5, QHeaderView.Stretch)
        tbl.resizeRowsToContents()
        v.addWidget(tbl, 1)
        if not rows:
            from PySide6.QtWidgets import QLabel
            v.addWidget(QLabel(tr("아직 기록이 없습니다.")))
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(d.reject)
        v.addWidget(bb)
        self._ai_log_dialog = d
        d.exec()

    def maybe_first_run_check(self):
        """처음 켤 때 한 번만 환경 점검 창(app.py 에서 부름)."""
        if self.settings.value("env_checked", False, type=bool):
            return
        self.settings.setValue("env_checked", True)
        self.show_env_check(modal=False)

    def _build_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: self.search_edit.setFocus())
        QShortcut(QKeySequence("F9"), self, activated=self._f9_in_window)
        for key, fn in (("Ctrl+C", self.copy_macro), ("Ctrl+V", self.paste_macro),
                        ("Delete", self.delete_macro)):
            sc = QShortcut(QKeySequence(key), self.macro_list)
            sc.setContext(Qt.WidgetShortcut)
            sc.activated.connect(fn)

    # ================================================================ 목록
    def reload_list(self, select: Optional[str] = None):
        if select is None:
            select = self.current_name()
        expanded = set()
        collapsed = set()
        for it in self._all_items():
            key = it.data(0, ROLE_PATH) or (it.data(0, ROLE_NAME) if it.data(0, ROLE_KIND) != "macro" else None)
            if key and it.childCount():
                (expanded if it.isExpanded() else collapsed).add(key)
        hot = self.store.hotkeys()
        self.macro_list.clear()
        groups, loose = self.store.tree()
        sel_item = None

        def make(name: str) -> QTreeWidgetItem:
            nonlocal sel_item
            it = QTreeWidgetItem([self._macro_label(name, hot.get(name))])
            it.setData(0, ROLE_KIND, "macro")
            it.setData(0, ROLE_NAME, name)
            it.setData(0, ROLE_META, self._macro_meta(name, hot.get(name)))
            it.setToolTip(0, name)
            if name == self.running_name:
                f = it.font(0)
                f.setBold(True)
                it.setFont(0, f)
                it.setBackground(0, QBrush(RUN_BG))
            if name == select:
                sel_item = it
            return it

        tree_mode = self.parts_action.isChecked()
        graph = self._call_graph() if tree_mode else {}
        called = {c for cs in graph.values() for c in cs}
        recent = self._recent_names(5)
        if recent:
            ri = QTreeWidgetItem(["🕘 " + tr("최근 실행")])
            ri.setData(0, ROLE_KIND, "recent")
            ri.setData(0, ROLE_NAME, "__recent__")
            ri.setForeground(0, QBrush(QColor("#5F5E5A")))
            self.macro_list.addTopLevelItem(ri)
            for n in recent:
                it = QTreeWidgetItem([n])
                it.setData(0, ROLE_KIND, "macro")
                it.setData(0, ROLE_NAME, n)
                it.setData(0, ROLE_META, self._macro_meta(n, hot.get(n)))
                it.setToolTip(0, n)
                ri.addChild(it)
            ri.setExpanded("__recent__" not in collapsed)
        def add_tree(parent: QTreeWidgetItem, name: str, key: str, chain: tuple, shown: set):
            """name 과 그것이 불러 쓰는 매크로들을 아래 트리로(같은 줄기에서 다시 나오면 멈춤)."""
            it = make(name)
            it.setData(0, ROLE_PATH, key)
            parent.addChild(it)
            shown.add(name)
            if len(chain) >= 6:
                return
            for c in graph.get(name, []):
                if c in chain or c == name:
                    continue
                add_tree(it, c, f"{key}/{c}", chain + (name,), shown)
            if it.childCount():
                it.setToolTip(0, tr("{name}\n아래는 이 매크로가 불러 쓰는 매크로({n}개)").format(name=name, n=it.childCount()))
                it.setExpanded(key in expanded or (len(chain) == 0 and key not in collapsed))

        for g, items in groups:
            roots = [n for n in items if n not in called]
            gi = QTreeWidgetItem(["📁 {}  ({})".format(g, len(items))])
            gi.setData(0, ROLE_KIND, "group")
            gi.setData(0, ROLE_NAME, g)
            gi.setData(0, ROLE_META, {"count": len(items)})
            f = gi.font(0)
            f.setBold(True)
            gi.setFont(0, f)
            self.macro_list.addTopLevelItem(gi)
            shown: set = set()
            for n in roots:
                add_tree(gi, n, f"{g}/{n}", (), shown)
            for n in items:                    # 순환 등으로 어디에도 안 나온 매크로는 그룹 바로 아래에
                if n not in shown and n not in called:
                    gi.addChild(make(n))
            gi.setExpanded(g not in collapsed)
        for n in loose:
            self.macro_list.addTopLevelItem(make(n))
        if sel_item is not None:
            self.macro_list.setCurrentItem(sel_item)
        self._filter()
        self.statusBar.showMessage(tr("매크로 {n}개").format(n=len(self.store.names())))
        self._update_welcome()

    def _update_welcome(self):
        """매크로가 하나도 없으면 첫 화면 안내를, 있으면 보통 화면을."""
        empty = not self.store.names()
        self._welcome_stack.setCurrentWidget(self.welcome if empty else self._welcome_stack.widget(0))

    def _on_ask(self, thread, req: dict):
        """실행 중인 매크로의 '사람에게 묻기': 맨 위에 창을 띄우고 답을 실행 스레드로 돌려준다."""
        from .ask_dialog import ask
        status, value = ask(None, req)
        thread.answer(status, value)

    def install_examples(self):
        """예시 매크로 3개를 '예시' 묶음에 넣는다(같은 이름이 있으면 건너뜀, 지우거나 덮어쓰지 않음)."""
        from . import examples as ex
        try:
            res = ex.install(self.store, os.path.dirname(self.store.root), ex.program_installed)
        except Exception as e:
            QMessageBox.warning(self, tr("예시 넣기"), tr("예시를 넣지 못했습니다: {e}").format(e=e))
            return
        first = res["made"][0] if res["made"] else (res["skipped"][0] if res["skipped"] else None)
        self.reload_list(select=first)
        if first:
            self.show_macro(first)
        lines = []
        if res["made"]:
            lines.append(tr("예시 {n}개를 '{group}' 묶음에 넣었어요.").format(n=len(res["made"]), group=ex.group_name()))
            lines.append(tr("먼저 '{name}'을 골라 '실행'을 눌러 보세요. 마우스·키보드를 쓰지 않아 가장 안전해요.")
                         .format(name=res["made"][0]))
        if res["skipped"]:
            lines.append(tr("이미 있는 예시는 그대로 뒀어요: {names}").format(names=", ".join(res["skipped"])))
        for name, lack in res["missing"]:
            lines.append(tr("이 컴퓨터에 {what}이(가) 없어 '{name}'은 돌아가지 않아요.")
                         .format(what=", ".join(ex.program_label(k) for k in lack), name=name))
        lines.append(tr("예시가 쓰는 파일과 결과는 이 폴더에 있어요: {folder}").format(folder=res["folder"]))
        QMessageBox.information(self, tr("예시 넣기"), "\n\n".join(lines))

    def _part_names(self) -> set:
        """다른 매크로가 call 로 부르는 매크로(부품)."""
        return {c for cs in self._call_graph().values() for c in cs}

    def _call_graph(self) -> dict:
        """매크로 → 그 매크로가 call 로 부르는 매크로 목록(스텝 순서). 파일이 바뀐 것만 다시 읽음."""
        cache = getattr(self, "_calls_cache", None)
        if cache is None:
            cache = self._calls_cache = {}
        from gui.v2.model import walk_dict
        graph = {}
        names = self.store.names()
        for n in names:
            try:
                fp = self.store.path(n)
                mt = os.path.getmtime(fp)
            except Exception:
                fp, mt = None, None
            hit = cache.get(n)
            if hit is None or hit[0] != mt:
                try:
                    m = self.store.load(n)
                    calls = list(dict.fromkeys(s.get("macro") for _, s in walk_dict(m.get("steps", []))
                                               if isinstance(s, dict) and s.get("type") == "call"))
                except Exception:
                    calls = []
                hit = cache[n] = (mt, calls)
            graph[n] = hit[1]
        valid = set(names)
        return {n: [c for c in cs if c in valid] for n, cs in graph.items()}

    def _recent_names(self, k: int) -> list:
        """최근 실행 기록(logs/runs)의 매크로 이름(있는 것만, 시험용 '_' 매크로 제외)."""
        try:
            from engine.real import TRACE_ROOT
            files = sorted(os.listdir(TRACE_ROOT), reverse=True)
        except Exception:
            return []
        names = set(self.store.names())
        out = []
        for f in files:
            if not f.endswith(".jsonl") or len(f) < 17:
                continue
            n = f[16:-6]
            if n in names and not n.startswith("_") and n not in out:
                out.append(n)
            if len(out) >= k:
                break
        return out

    def _macro_meta(self, name: str, hot) -> dict:
        """새 화면 목록 줄에 그릴 것: 핫키 칩, 마지막 실행, 상태(정상·실행 중·알림·실패·기록 없음)."""
        hk = ""
        if hot:
            run, stop = hot
            hk = run if (run and run == stop) else " / ".join(x for x in (run, stop) if x)
        meta = {"hot": hk, "last": "", "status": "off", "status_text": "", "running": name == self.running_name}
        if meta["running"]:
            meta.update(status="running", status_text=tr("실행 중"), last=tr("지금 실행 중"))
            return meta
        cache = getattr(self, "_meta_cache", None)
        if cache is None:
            cache = self._meta_cache = {}
        try:
            from engine.real import PROJECT_ROOT
            hp = os.path.join(PROJECT_ROOT, "logs", "health", name + ".json")
            mt = os.path.getmtime(hp) if os.path.exists(hp) else None
        except Exception:
            hp, mt = None, None
        hit = cache.get(name)
        if hit is not None and hit[0] == mt:
            meta.update(hit[1])
            return meta
        extra = {"last": "", "status": "off", "status_text": ""}   # 기록 없으면 둘째 줄을 비워 줄마다 같은 글이 반복되지 않게
        if mt is not None:
            try:
                from engine.health import load_summary
                sm = load_summary(os.path.dirname(hp), name)
            except Exception:
                sm = None
            if sm and sm.get("iterations"):
                import time as _t
                when = _t.strftime("%m-%d %H:%M", _t.localtime(mt))
                med = sm.get("median_seconds")
                extra["last"] = when + (" · " + tr("한 바퀴 {sec}초").format(sec=med) if med is not None else "") +                     " · " + tr("성공 {ok}/{n}").format(ok=sm["ok"], n=sm["iterations"])
                weak = [x for x in sm.get("low_images", []) if x.get("margin", 1) < 0.05]
                if sm["ok"] < sm["iterations"]:
                    extra.update(status="bad", status_text=tr("실패 있음"))
                elif weak:
                    extra.update(status="warn", status_text=tr("알림"))
                else:
                    extra.update(status="ok", status_text=tr("정상"))
        try:                                    # 한글 단계가 있는데 보안 승인 모듈이 없으면 '설정 필요'(처음 예시에서 막히지 않게)
            from . import hwp_setup
            if not hwp_setup.ready():
                with open(self.store.path(name), encoding="utf-8") as fh:
                    if '"hwp"' in fh.read():
                        extra = dict(extra, status="warn", status_text=tr("설정 필요"))
        except Exception:
            pass
        cache[name] = (mt, extra)
        meta.update(extra)
        return meta

    def _macro_label(self, name: str, hot) -> str:
        s = ("▶ " if name == self.running_name else "") + name
        if hot:
            run, stop = hot
            if run and run == stop:
                s += "   [" + tr("{key} 실행/정지").format(key=run) + "]"
            else:
                parts = ([tr("실행 {key}").format(key=run)] if run else []) + ([tr("정지 {key}").format(key=stop)] if stop else [])
                s += f"   [{', '.join(parts)}]"
        return s

    def current_name(self) -> Optional[str]:
        it = self.macro_list.currentItem() if hasattr(self, "macro_list") else None
        if it is not None and it.data(0, ROLE_KIND) == "macro":
            return it.data(0, ROLE_NAME)
        return None

    def current_group(self) -> Optional[str]:
        it = self.macro_list.currentItem()
        while it is not None and it.data(0, ROLE_KIND) != "group":
            it = it.parent()
        return it.data(0, ROLE_NAME) if it is not None else None

    def _all_items(self):
        stack = [self.macro_list.topLevelItem(i) for i in range(self.macro_list.topLevelItemCount())]
        while stack:
            it = stack.pop(0)
            yield it
            stack[0:0] = [it.child(j) for j in range(it.childCount())]

    def select_macro(self, name: str) -> bool:
        for it in self._all_items():
            if it.data(0, ROLE_KIND) == "macro" and it.data(0, ROLE_NAME) == name \
                    and (it.parent() is None or it.parent().data(0, ROLE_KIND) != "recent"):
                p = it.parent()
                while p is not None:
                    p.setExpanded(True)
                    p = p.parent()
                self.macro_list.setCurrentItem(it)
                return True
        return False

    def _filter(self):
        text = self.search_edit.text().strip().lower()

        def apply(it, inherited: bool) -> bool:
            kind = it.data(0, ROLE_KIND)
            if kind == "macro":
                me = not text or inherited or text in it.data(0, ROLE_NAME).lower()
                kids = sum(apply(it.child(j), False) for j in range(it.childCount()))
                show = me or kids > 0
                if text and kids:
                    it.setExpanded(True)
                it.setHidden(not show)
                return show
            gmatch = kind == "group" and bool(text) and text in (it.data(0, ROLE_NAME) or "").lower()
            visible = sum(apply(it.child(j), inherited or gmatch) for j in range(it.childCount()))
            if text and visible and kind == "parts":
                it.setExpanded(True)
            hide = bool(text) and not gmatch and visible == 0
            it.setHidden(hide)
            return not hide

        for i in range(self.macro_list.topLevelItemCount()):
            apply(self.macro_list.topLevelItem(i), False)

    # ================================================================ 선택·정보
    def _on_selected(self):
        name = self.current_name()
        if name is None or name == self._shown_name:
            return
        self.show_macro(name)

    def show_macro(self, name: str):
        try:
            m = self.store.load(name)
        except Exception as e:
            self.info_label.setText("<b>{}</b><br>".format(name) + tr("읽기 실패: {e}").format(e=e))
            self.steps_view.clear()
            self.path_items = {}
            self._shown_name = name
            return
        errors = self.store.check(m)
        self._shown_name = name
        self.info_title.setText(name)
        self.info_label.setText(self._info_html(name, m, errors))
        self._fill_steps(m)
        self._sync_run_ui()
        try:
            from gui.v2.model import walk_dict
            n = sum(1 for _ in walk_dict(m.get("steps", [])))
        except Exception:
            n = len(m.get("steps") or [])
        self.steps_title.setText(tr("스텝 {n}개").format(n=n))

    def _info_html(self, name: str, m: dict, errors) -> str:
        win = (m.get("window") or {}).get("title")
        rep = m.get("repeat") or {"times": 1}
        rep_s = tr("계속 반복") if rep.get("forever") else tr("{n}번").format(n=rep.get('times', 1))
        fail = (m.get("on_iteration_fail") or {}).get("action")
        from .design import theme as _theme
        _t = _theme.current()
        rows = []
        if m.get("description"):
            rows.append(m["description"])
        rows.append(tr("창: {win} &nbsp;|&nbsp; 반복: {rep}").format(win=win or tr("화면 전체"), rep=rep_s)
                    + (tr(" &nbsp;|&nbsp; 회차 실패 시: {what}").format(what=tr("다시") if fail == 'retry' else tr("정지")) if fail else ""))
        run, stop = m.get("run_hotkey"), m.get("stop_hotkey")
        if run or stop:
            from gui.v3.hotkey_dialog import display as _hd
            rows.append((tr("핫키: 실행·정지 {key} (같은 키로 켜고 끄기)").format(key=_hd(run)) if run and run == stop else
                         tr("핫키: 실행 {run} · 정지 {stop}").format(run=_hd(run) or tr("없음"), stop=_hd(stop) or tr("없음")))
                        + tr(" (이 프로그램이 뒤에 있어도 먹음)"))
        else:
            rows.append(tr("핫키 없음 — [핫키]로 키를 정하면 다른 창을 쓰는 중에도 이 매크로를 켜고 끌 수 있어요"))
        callers = []
        try:
            callers = self.store.callers_of(name)
        except Exception:
            pass
        if callers:
            rows.append(tr("이 매크로를 부르는 매크로: ") + ", ".join(callers))
        hs = self._health_line(name)
        if hs:
            rows.append(hs)
        if errors:
            rows.append("<span style='color:" + _theme.current()['bad'] + "'><b>" + tr("형식 오류") + "</b><br>" + "<br>".join(errors[:6]) + "</span>")
        return "<br>".join(rows)

    def _health_line(self, name: str) -> str:
        """건강 요약 한 줄(최근 회차 성공 수·한 바퀴 시간·점수 여유가 적은 그림). 기록이 없으면 빈 글."""
        try:
            import os
            from engine.health import load_summary
            from engine.real import PROJECT_ROOT
            s = load_summary(os.path.join(PROJECT_ROOT, "logs", "health"), name)
        except Exception:
            return ""
        if not s or not s["iterations"]:
            return ""
        parts = [tr("최근 {n}회 중 성공 {ok}회").format(n=s["iterations"], ok=s["ok"])]
        if s["median_seconds"] is not None:
            parts.append(tr("한 바퀴 보통 {sec}초").format(sec=s["median_seconds"]))
        weak = [x for x in s["low_images"] if x["margin"] < 0.05]
        if weak:
            parts.append("<span style='color:" + _theme.current()['bad'] + "'>" + tr("인식이 아슬아슬한 그림 {n}개: {names}").format(
                n=len(weak), names=", ".join(x["image"].replace("\\", "/").split("/")[-1] for x in weak)) + "</span>")
        return tr("건강: ") + " · ".join(parts)

    def _fill_steps(self, m: dict):
        self.steps_view.clear()
        self.path_items = {}
        self._highlighted = None

        def add(parent, steps, prefix):
            for i, s in enumerate(steps or []):
                path = f"{prefix}[{i}]"
                it = QTreeWidgetItem([step_text(s) if isinstance(s, dict) else str(s), ""])
                if isinstance(s, dict):
                    it.setIcon(0, step_icon(s.get("type", "")))
                it.setData(0, ROLE_PATH, path)
                it.setData(0, STEP_NUM_ROLE, i + 1)
                it.setToolTip(0, path)
                if isinstance(s, dict) and s.get("type") == "comment":
                    it.setForeground(0, QBrush(QColor("#777777")))
                (parent.addChild(it) if parent is not None else self.steps_view.addTopLevelItem(it))
                self.path_items[path] = it
                if not isinstance(s, dict):
                    continue
                keys = CHILD_KEYS.get(s.get("type"), ())
                if s.get("type") == "if":
                    for k in keys:
                        if k in s:
                            hdr = QTreeWidgetItem([tr(BRANCH_NAMES[k]), ""])
                            hdr.setForeground(0, QBrush(QColor("#1565c0")))
                            it.addChild(hdr)
                            add(hdr, s[k], f"{path}.{k}")
                            hdr.setExpanded(True)
                elif keys:
                    add(it, s.get("steps"), f"{path}.steps")
                it.setExpanded(True)

        add(None, m.get("steps"), "steps")
        self._restore_run_marks()

    def _restore_run_marks(self):
        """다른 매크로를 보다 돌아오면 스텝 표를 새로 그리므로, 실행 중인 위치 강조와 완료/실패 표시를 다시 칠한다.
        실행 중인 매크로뿐 아니라 지금 불려서 도는 하위 매크로를 볼 때도 같다."""
        name = self._shown_name
        if not name or not self.is_running():
            return
        for path, (st, ms) in (self._run_marks.get(name) or {}).items():
            if path in self.path_items:
                self._mark_status(self.path_items[path], st, ms)
        pos = self._run_pos.get(name)
        if pos in self.path_items:
            self._highlight(self.path_items[pos])

    def _mark_status(self, it: QTreeWidgetItem, st, ms):
        it.setText(1, tr({'ok': '완료', 'skipped': '건너뜀', 'failed': '실패'}.get(st, st))
                      + (f" {ms}ms" if ms is not None else ""))
        it.setForeground(1, QBrush({"ok": OK_FG, "skipped": SKIP_FG}.get(st, FAIL_FG)))

    def _on_double_clicked(self, item, _col=0):
        if item.data(0, ROLE_KIND) in ("group", "parts", "recent"):
            item.setExpanded(not item.isExpanded())
        else:
            self.edit_macro()

    # ================================================================ 실행
    def is_running(self) -> bool:
        t = self.run_thread
        return bool(t is not None and t.isRunning())

    def run_macro(self, name: Optional[str] = None):
        name = name or self.current_name()
        if not name:
            QMessageBox.information(self, tr("실행"), tr("실행할 매크로를 고르세요."))
            return
        if self.is_running():
            self.statusBar.showMessage(tr("이미 '{name}' 실행 중").format(name=self.running_name))
            return
        try:
            m = self.store.load(name)
        except Exception as e:
            QMessageBox.warning(self, tr("실행"), tr("'{name}' 을(를) 읽을 수 없음: {e}").format(name=name, e=e))
            return
        errors = self.store.check(m)
        if errors:
            from .editor.friendly import friendly_list
            QMessageBox.warning(self, tr("실행"), tr("아직 정하지 않은 곳이 있어 실행할 수 없습니다. '편집'에서 고쳐 주세요:\n\n")
                                + "\n".join(friendly_list(errors, m, 10)))
            return
        from . import hwp_setup
        if hwp_setup.uses_hwp(m) and not hwp_setup.ask_before_run(self):
            return                                  # 한글 보안 승인 모듈 없음 → 설정 안내 또는 취소(숨은 창에 2분 막히지 않게)
        self.select_macro(name)
        self.show_macro(name)
        self.running_name = name
        self._run_pos = {}
        self._run_marks = {}
        self.log(tr("=== 실행: {name} (비상 정지 Ctrl+Shift+F12) ===").format(name=name))
        t = RunThread(m, env_factory=self.env_factory, emergency_hotkey=self.emergency_hotkey,
                      write_trace=self.write_trace)
        t.event.connect(self._on_run_event)
        t.run_finished.connect(self._on_run_finished)
        t.ask_requested.connect(lambda req, th=t: self._on_ask(th, req))
        self.run_thread = t
        self._run_macros = {name: m}            # 실행 기록에 스텝 이름을 쓰려고(하위 매크로는 필요할 때 읽음)
        self._user_stop = False
        self._guard_start(name)
        self._sync_run_ui()
        self.statusBar.showMessage(tr("'{name}' 실행 중…").format(name=name))
        self.reload_list(select=name)
        # 이 창이 대상 창을 가리면 화면 인식·클릭이 이 창에 걸리므로 실행 중에는 최소화
        # ('뒤에서 실행' 매크로는 가려져도 되므로 그대로 둠)
        self._minimized_for_run = False
        background = bool((m.get("window") or {}).get("background"))
        if self.minimize_action.isChecked() and not self.isMinimized() and not background:
            self.showMinimized()
            self._minimized_for_run = True
        t.start()

    def stop_macro(self, source=None):
        """source: 누가 멈췄는지(기록에 남김). 버튼·메뉴는 Qt 가 bool 을 넘기므로 글이 아니면 '프로그램 정지'로 봄."""
        if not isinstance(source, str):
            source = tr("프로그램 정지(버튼·메뉴·Shift+F5)")
        self._user_stop = True                   # 사람이 멈춤 → 지킴이는 다시 켜지 않음
        if self.is_running():
            self.run_thread.stop(source)
            self.statusBar.showMessage(tr("'{name}' 정지 요청…").format(name=self.running_name))
            self.log(tr("정지 요청") + f" — {source}")

    def _on_run_event(self, ev: dict):
        kind = ev.get("event")
        macro = ev.get("macro")
        top = macro == self.running_name and ev.get("depth", 0) == 0
        path = ev.get("path")
        shown = self._shown_name == macro
        # 매크로별 지금 위치·완료 표시를 기억해 둠(다른 매크로를 보다 돌아와도 다시 칠하려고)
        if kind == "run_start" and not top:
            self._run_pos.pop(macro, None)
            self._run_marks[macro] = {}
            if shown:
                self._clear_run_view()
        elif kind == "run_end" and not top:
            self._run_pos.pop(macro, None)
            if shown:
                self._unhighlight()
        elif kind == "step_start" and path:
            self._run_pos[macro] = path
            if shown and path in self.path_items:
                self._highlight(self.path_items[path])
        elif kind == "step_end" and path:
            self._run_marks.setdefault(macro, {})[path] = (ev.get("status"), ev.get("ms"))
            if shown and path in self.path_items:
                self._mark_status(self.path_items[path], ev.get("status"), ev.get("ms"))
        if not top:
            if kind == "step_start":
                self.statusBar.showMessage(tr("'{name}' → 하위 매크로 '{sub}' 실행 중").format(name=self.running_name, sub=ev.get('macro')))
            if kind == "step_end" and ev.get("status") == "failed":
                sub = ev.get("macro")
                self.log(tr("  [하위 {sub}] {path} 실패: {reason}").format(sub=sub, path=self._where(sub, path),
                                                                        reason=ev.get('reason', '')), link=(sub, path))
            return
        if kind == "step_end" and path in self.path_items and shown:
            st = ev.get("status")
            if st in ("skipped", "failed") and ev.get("type") not in ("if", "repeat", "group"):
                self.log("  {} {}: {}".format(self._where(self.running_name, path), tr('건너뜀') if st == 'skipped' else tr('실패'),
                                              ev.get('reason', '')), link=(self.running_name, path))
        elif kind == "warning":
            self.log(tr("  경고: {msg}").format(msg=ev.get('message') or ev.get('detail') or ev))
        elif kind == "iteration_start" and ev.get("iteration", 1) > 1:
            self.log(tr("  회차 {n}").format(n=ev.get('iteration')))

    def _unhighlight(self):
        if self._highlighted is not None:
            try:
                self._highlighted.setBackground(0, QBrush())
            except RuntimeError:
                pass
            self._highlighted = None

    def _clear_run_view(self):
        """하위 매크로가 새로 불릴 때 지난번 완료/실패 표시를 지움."""
        self._unhighlight()
        for it in self.path_items.values():
            try:
                it.setText(1, "")
            except RuntimeError:
                pass

    def _highlight(self, it: QTreeWidgetItem):
        self._unhighlight()
        it.setBackground(0, QBrush(RUN_BG))
        self.steps_view.scrollToItem(it)
        self._highlighted = it

    def _on_run_finished(self, res: dict):
        try:
            self.refresh_approval_badge()           # 실행 중 새 제안이 생겼을 수 있음
        except Exception:
            pass
        name = self.running_name
        st = res.get("status")
        word = {"ok": tr("완료"), "failed": tr("실패"), "stopped": tr("정지됨")}.get(st, st)
        msg = tr("=== {name} {word} ({sec}초)").format(name=name, word=word, sec="%.1f" % res.get('duration', 0))
        if res.get("value") not in (None, "ok"):
            msg += tr(" 결과: {v}").format(v=res.get('value'))
        msg += " ==="
        self.log(msg)
        if st == "stopped":
            src = getattr(self.run_thread, "stop_source", None) or tr("알 수 없음")
            self.log(tr("  정지 출처: {src}").format(src=src))
            try:
                if not self.write_trace:            # 시험(가짜 화면)에서는 진짜 기록 폴더에 안 남김
                    raise RuntimeError
                import json as _json
                import time as _time
                from engine.real import PROJECT_ROOT
                d = os.path.join(PROJECT_ROOT, "logs", "guard")
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, "stop_sources.jsonl"), "a", encoding="utf-8") as f:
                    f.write(_json.dumps({"시각": _time.strftime("%Y-%m-%d %H:%M:%S"), "매크로": name, "출처": src,
                                         "초": round(res.get("duration", 0), 1)}, ensure_ascii=False) + "\n")
            except Exception:
                pass
        err = res.get("error")
        if err:
            ep = err.get('path')
            self.log(tr("  실패 위치 {path}: {reason}").format(path=self._where(name, ep) if ep else "-", reason=err.get('reason')),
                     link=(name, ep) if ep else None)
        if res.get("trace"):
            self.log(tr("  기록: {path}").format(path=res['trace']))
        self._unhighlight()
        self._run_pos = {}
        self._run_marks = {}
        self.running_name = None
        self.run_thread = None
        try:
            from engine import guard
            guard.mark_ended(st, user_stopped=st == "stopped" or getattr(self, "_user_stop", False))
        except Exception:
            pass
        self._sync_run_ui()
        self.statusBar.showMessage(f"'{name}' {word}")
        self.reload_list()
        if self._minimized_for_run:
            self._minimized_for_run = False
            from gui.v2.quiet_restore import restore_without_focus      # 되살리되 키 입력은 안 뺏음
            restore_without_focus(self, QApplication.platformName() == "windows")

    def log(self, text: str, link=None):
        """실행 기록 한 줄. link=(매크로 이름, 스텝 위치)를 주면 그 줄을 누를 때 그 스텝으로 간다."""
        self.log_view.appendPlainText(text)
        if link and link[0] and link[1]:
            self.log_view.document().lastBlock().setUserData(_LogLink(link[0], link[1]))

    def _where(self, macro_name, path) -> str:
        """'steps[11].steps[8].then[2]' → "12번 › 9번 › 그러면 3번 '이름'" (매크로를 못 읽으면 번호만)."""
        from .editor.friendly import where
        cache = getattr(self, "_run_macros", None)
        if cache is None:
            cache = self._run_macros = {}
        m = cache.get(macro_name)
        if m is None and macro_name:
            try:
                m = cache[macro_name] = self.store.load(macro_name)
            except Exception:
                m = cache[macro_name] = {}
        return where(m or {}, path or "")

    def _log_link_at(self, pos):
        data = self.log_view.cursorForPosition(pos).block().userData()
        return data if isinstance(data, _LogLink) else None

    def go_to_step(self, name: str, path: str):
        """매크로를 고르고 스텝 목록에서 그 스텝을 보여 줌."""
        if name != self._shown_name:
            self.select_macro(name)
            self.show_macro(name)
        it = self.path_items.get(path)
        if it is not None:
            p = it.parent()
            while p is not None:
                p.setExpanded(True)
                p = p.parent()
            self.steps_view.setCurrentItem(it)
            self.steps_view.scrollToItem(it)

    def eventFilter(self, obj, ev):
        lv = getattr(self, "log_view", None)
        if lv is not None and obj is lv.viewport():
            et = ev.type()
            if et == QEvent.MouseButtonRelease and ev.button() == Qt.LeftButton:
                link = self._log_link_at(ev.position().toPoint())
                if link is not None and not lv.textCursor().hasSelection():
                    self.go_to_step(link.macro, link.path)
            elif et == QEvent.MouseMove:
                on = self._log_link_at(ev.position().toPoint()) is not None
                obj.setCursor(Qt.PointingHandCursor if on else Qt.IBeamCursor)
        return super().eventFilter(obj, ev)

    # ------------------------------------------------------------ 실행 상태 → 버튼·메뉴(한 곳에서)
    # 11-23: 다른 창(예: 채팅 창)을 쓰다가 이 창을 누르면, 창을 앞으로 가져오는 그 첫 클릭이 '실행/정지' 단추에
    # 그대로 먹어 자동운영이 켜자마자·몇 시간 뒤 꺼졌음(정지 출처 기록: '정보 칸 정지 버튼'). 앞으로 온 직후 클릭은 무시.
    ACTIVATION_GUARD_SEC = 0.6

    def changeEvent(self, e):
        try:
            if e.type() == QEvent.ActivationChange and self.isActiveWindow():
                import time as _time
                self._activated_at = _time.monotonic()
        except Exception:
            pass
        super().changeEvent(e)

    def _click_just_activated(self) -> bool:
        """방금(0.6초 안) 이 창이 앞으로 온 클릭이면 True — 실행·정지 단추는 이 클릭을 무시한다."""
        import time as _time
        if _time.monotonic() - getattr(self, "_activated_at", -99.0) < self.ACTIVATION_GUARD_SEC:
            self.statusBar.showMessage(tr("창을 앞으로 가져온 클릭이라 실행·정지는 하지 않았어요. 한 번 더 누르세요."), 6000)
            return True
        return False

    def _guarded(self, fn):
        return lambda *_: None if self._click_just_activated() else fn()

    def _info_run_clicked(self):
        if self._click_just_activated():
            return
        if self.running_name and self.running_name == self._shown_name:
            self.stop_macro(tr("정보 칸 정지 버튼"))
        else:
            self.run_macro()

    def _sync_run_ui(self):
        """실행 중인지에 따라 도구 줄·정보 칸·아래 버튼·메뉴 줄을 같은 상태로 맞춘다."""
        running = self.running_name
        shown = self._shown_name
        idle = running is None
        mine = not idle and shown == running
        self.run_btn.setEnabled(idle)
        self.stop_btn.setEnabled(not idle)
        for key, on in (("실행", idle), ("정지", not idle)):
            a = getattr(self, "tool_actions", {}).get(key)
            if a is not None:
                a.setEnabled(on)
        if hasattr(self, "menu_run_action"):
            self.menu_run_action.setEnabled(idle)
            self.menu_stop_action.setEnabled(not idle)
        b = self.info_run_btn
        if mine:
            b.setText(" " + tr("정지"))
            b.setObjectName("StopPrimary")
            b.setEnabled(True)
            b.setToolTip(tr("실행 중 — 누르면 정지 (Shift+F5, 어디서나 Ctrl+Shift+F12)"))
            icon_name = "square"
        else:
            b.setText(" " + tr("실행"))
            b.setObjectName("Primary")
            b.setEnabled(idle and shown is not None)
            b.setToolTip(tr("다른 매크로 '{name}' 실행 중 — 멈춘 뒤 실행할 수 있어요").format(name=running) if not idle
                         else tr("고른 매크로 실행 (F5 — 이 창이 앞에 있을 때)"))
            icon_name = "play"
        try:
            from .design import theme as _theme
            from .design.assets import icon as _icon
            b.setIcon(_icon(icon_name, _theme.current()["on_accent"], 16))
        except Exception:
            pass
        b.style().unpolish(b)
        b.style().polish(b)
        other = not idle and not mine
        self.info_run_note.setText(tr("다른 매크로 실행 중: {name}").format(name=running) if other else "")
        self.info_run_note.setVisible(other)
        self.info_edit_btn.setEnabled(not mine)
        self.edit_btn.setEnabled(not mine)
        self.delete_btn.setEnabled(not mine)

    # ================================================================ 편집·관리
    def new_macro(self, group: Optional[str] = None):
        group = group if isinstance(group, str) else self.current_group()
        name, ok = QInputDialog.getText(self, tr("새 매크로"), tr("매크로 이름:"))
        name = (name or "").strip()
        if not ok or not name:
            return
        try:
            self.store.create(name, group=group)
        except (StoreError, ValueError, MacroError) as e:
            QMessageBox.warning(self, tr("새 매크로"), str(e))
            return
        self.reload_list(select=name)
        self.edit_macro(name)

    def edit_macro(self, name: Optional[str] = None):
        name = name if isinstance(name, str) else self.current_name()
        if not name:
            QMessageBox.information(self, tr("편집"), tr("편집할 매크로를 고르세요."))
            return
        if self.running_name == name:
            QMessageBox.information(self, tr("편집"), tr("실행 중인 매크로는 멈춘 뒤 편집하세요."))
            return
        from .editor.macro_editor import MacroEditorDialog
        dlg = MacroEditorDialog(self.store, name, parent=self, env_factory=self.env_factory)
        if dlg.exec():
            new_name = dlg.saved_name or name
            if dlg.updated_callers:
                self.log(tr("이름 변경으로 함께 고친 매크로: {names}").format(names=', '.join(dlg.updated_callers)))
            self._shown_name = None
            self.reload_list(select=new_name)
            self.show_macro(new_name)
            self.register_hotkeys()

    def rename_macro(self):
        name = self.current_name()
        if not name:
            return
        new, ok = QInputDialog.getText(self, tr("이름 바꾸기"), tr("새 이름:"), text=name)
        new = (new or "").strip()
        if not ok or not new or new == name:
            return
        try:
            updated = self.store.rename(name, new)
        except (StoreError, ValueError, MacroError) as e:
            QMessageBox.warning(self, tr("이름 바꾸기"), str(e))
            return
        if updated:
            self.log(tr("'{old}' → '{new}': 이 매크로를 부르던 {names} 도 고침").format(old=name, new=new, names=', '.join(updated)))
        self._shown_name = None
        self.reload_list(select=new)
        self.register_hotkeys()

    def duplicate_macro(self):
        name = self.current_name()
        if not name:
            return
        new = self.store.copy(name)
        self.reload_list(select=new)

    def copy_macro(self):
        name = self.current_name()
        if name:
            self.copied = self.store.load(name)
            self.statusBar.showMessage(tr("'{name}' 복사됨 (Ctrl+V 로 붙여넣기)").format(name=name))

    def paste_macro(self):
        if not self.copied:
            return
        try:
            new = self.store.add(self.copied, group=self.current_group())
        except (StoreError, ValueError, MacroError) as e:
            QMessageBox.warning(self, tr("붙여넣기"), str(e))
            return
        self.reload_list(select=new)

    def delete_macro(self):
        name = self.current_name()
        if not name:
            g = self.current_group()
            if g:
                self.delete_group(g)
            return
        if self.running_name == name:
            QMessageBox.information(self, tr("삭제"), tr("실행 중인 매크로는 지울 수 없습니다."))
            return
        callers = self.store.callers_of(name)
        msg = tr("'{name}' 매크로를 지울까요?").format(name=name)
        if callers:
            msg += tr("\n\n주의: 이 매크로를 부르는 매크로가 있습니다:\n  ") + "\n  ".join(callers) \
                   + tr("\n지우면 그 매크로들의 호출 스텝이 실패합니다.")
        if QMessageBox.question(self, tr("삭제"), msg, QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        self.store.delete(name)
        self._shown_name = None
        self.steps_view.clear()
        self.info_label.setText(tr("왼쪽 목록에서 매크로를 고르면 할 일 목록이 여기 보여요."))
        self.reload_list()
        self.register_hotkeys()

    def set_hotkeys(self):
        name = self.current_name()
        if not name:
            QMessageBox.information(self, tr("핫키"), tr("핫키를 정할 매크로를 고르세요."))
            return
        from gui.v3.hotkey_dialog import HotkeyPairDialog
        m = self.store.load(name)
        run_old, stop_old = m.get("run_hotkey", ""), m.get("stop_hotkey", "")
        d = HotkeyPairDialog(self, name, run_old, stop_old, self.store.hotkeys())
        self._hotkey_dialog = d                  # 시험용
        if not d.exec():
            return
        run_new, stop_new = d.keys()
        try:
            self.store.set_hotkeys(name, run_new, stop_new)
        except MacroError as e:
            QMessageBox.warning(self, tr("핫키"), str(e))
            return
        self.reload_list(select=name)
        self.show_macro(name)                    # 정보 칸 핫키 줄 새로
        self.register_hotkeys()
        from gui.v3.hotkey_dialog import display as _hd
        self.statusBar.showMessage(tr("'{name}' 핫키: 실행 {run} · 정지 {stop}").format(
            name=name, run=_hd(run_new) or tr('없음'), stop=_hd(stop_new) or tr('없음')))

    def _on_moved(self, name: str, group):
        self.store.move_to_group(name, group)
        self.reload_list(select=name)

    # ------------------------------------------------------------ 그룹
    def new_group(self):
        g, ok = QInputDialog.getText(self, tr("새 그룹"), tr("그룹 이름:"))
        if not ok or not (g or "").strip():
            return
        try:
            self.store.create_group(g)
        except StoreError as e:
            QMessageBox.warning(self, tr("새 그룹"), str(e))
            return
        self.reload_list()

    def rename_group(self, g: str):
        new, ok = QInputDialog.getText(self, tr("그룹 이름 바꾸기"), tr("새 이름:"), text=g)
        if not ok:
            return
        try:
            self.store.rename_group(g, new)
        except StoreError as e:
            QMessageBox.warning(self, tr("그룹 이름 바꾸기"), str(e))
            return
        self.reload_list()

    def delete_group(self, g: str):
        if QMessageBox.question(self, tr("그룹 삭제"), tr("'{g}' 그룹을 지울까요?\n(안의 매크로는 지우지 않고 맨 위로 옮깁니다)").format(g=g),
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.store.delete_group(g)
        self.reload_list()

    # ------------------------------------------------------------ 메뉴
    def _context_menu(self, pos):
        it = self.macro_list.itemAt(pos)
        if it is not None:
            self.macro_list.setCurrentItem(it)
        self.build_context_menu(it).exec(self.macro_list.mapToGlobal(pos))

    def build_context_menu(self, it) -> QMenu:
        """목록 우클릭 메뉴(시험에서 띄우지 않고 내용만 보려고 따로 둠)."""
        menu = QMenu(self)
        kind = it.data(0, ROLE_KIND) if it is not None else None
        if kind == "macro":
            name = it.data(0, ROLE_NAME)
            if name == self.running_name:
                menu.addAction(tr("정지 (Shift+F5)"), self.stop_macro)
            elif self.running_name:
                menu.addAction(tr("실행 (F5) — 다른 매크로 실행 중"), self.run_macro).setEnabled(False)
            else:
                menu.addAction(tr("실행 (F5)"), self.run_macro)
            menu.addAction(tr("편집 (Ctrl+E)"), self.edit_macro).setEnabled(name != self.running_name)
            menu.addAction(tr("이 매크로 예약…"), self.open_schedules)
            menu.addAction(tr("핫키 정하기…"), self.set_hotkeys)
            menu.addSeparator()
            menu.addAction(tr("복사 (Ctrl+C)"), self.copy_macro)
            menu.addAction(tr("붙여넣기 (Ctrl+V)"), self.paste_macro).setEnabled(self.copied is not None)
            menu.addAction(tr("복사본 만들기 (Ctrl+D)"), self.duplicate_macro)
            menu.addAction(tr("이름 바꾸기 (F2)"), self.rename_macro)
            menu.addSeparator()
            gm = menu.addMenu(tr("그룹으로 옮기기"))
            cur = self.store.group_of(name)
            for g, _ in self.store.tree()[0]:
                a = gm.addAction(g, lambda g=g, n=name: self._on_moved(n, g))
                a.setEnabled(g != cur)
            if cur:
                gm.addSeparator()
                gm.addAction(tr("그룹에서 빼기"), lambda n=name: self._on_moved(n, None))
            gm.addSeparator()
            gm.addAction(tr("새 그룹 만들어 옮기기…"), lambda n=name: self._move_to_new_group(n))
            menu.addAction(tr("핫키 설정"), self.set_hotkeys)
            menu.addSeparator()
            menu.addAction(tr("삭제 (Del)"), self.delete_macro)
        elif kind == "group":
            g = it.data(0, ROLE_NAME)
            menu.addAction(tr("이 그룹에 새 매크로"), lambda g=g: self.new_macro(g))
            menu.addAction(tr("붙여넣기 (Ctrl+V)"), self.paste_macro).setEnabled(self.copied is not None)
            menu.addSeparator()
            menu.addAction(tr("그룹 이름 바꾸기"), lambda g=g: self.rename_group(g))
            menu.addAction(tr("그룹 삭제"), lambda g=g: self.delete_group(g))
        else:
            menu.addAction(tr("새 매크로"), self.new_macro)
            menu.addAction(tr("새 그룹"), self.new_group)
            menu.addAction(tr("붙여넣기 (Ctrl+V)"), self.paste_macro).setEnabled(self.copied is not None)
        return menu

    def _move_to_new_group(self, name: str):
        g, ok = QInputDialog.getText(self, tr("새 그룹"), tr("그룹 이름:"))
        g = (g or "").strip()
        if not ok or not g:
            return
        if g not in self.store.groups():
            self.store.create_group(g)
        self._on_moved(name, g)

    def _open_folder(self, path: str):
        try:
            os.startfile(path)
        except Exception as e:
            QMessageBox.warning(self, tr("폴더 열기"), str(e))

    def _open_trace_folder(self):
        from engine.real import TRACE_ROOT
        os.makedirs(TRACE_ROOT, exist_ok=True)
        self._open_folder(TRACE_ROOT)

    def _set_language(self, code: str):
        from gui.v2 import i18n
        if code == i18n.current():
            return
        i18n.set_language(code, save=True)
        # 고른 언어의 말로 묻는다(다시 켜야 화면 전체에 적용)
        msg = {"ko": "언어를 바꿨습니다. 지금 프로그램을 다시 켤까요?\n(실행 중인 매크로가 있으면 먼저 멈춥니다)",
               "en": "Language changed. Restart the program now?\n(Any running macro will be stopped first)"}[code]
        if QMessageBox.question(self, "Language", msg) != QMessageBox.Yes:
            return
        self.stop_macro(tr("언어 바꾸기로 다시 켜기"))
        self._restart_app()

    def _restart_app(self):
        """같은 프로그램을 새로 띄우고 이 창은 닫는다(실행 파일이면 실행 파일, 아니면 python main.py)."""
        import sys
        from PySide6.QtCore import QProcess
        keep = ["--v3"]                       # 새 화면으로 다시 켠다(기본이 v2 인 동안 이게 없으면 옛 화면이 뜸). --run 은 다시 안 함
        if getattr(sys, "frozen", False):
            ok = QProcess.startDetached(sys.executable, keep)
        else:
            import os
            main = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "main.py")
            ok = QProcess.startDetached(sys.executable, [main] + keep)
        if ok:
            self.close()

    def _show_help(self):
        from .help_text import main_help, show_html
        show_html(self, tr("사용법"), main_help())

    def _show_background_help(self):
        from .help_text import background_help, show_html
        show_html(self, tr("뒤에서 실행이란"), background_help())

    # ================================================================ 핫키
    def register_hotkeys(self):
        hm = self.hotkey_manager
        if hm is None or not hm.is_available():
            return
        hm.clear_all_hotkeys()
        for name, (run, stop) in self.store.hotkeys().items():
            if run and stop and run == stop:
                hm.register_toggle_hotkey(run, lambda n=name: self.hotkey_run.emit(n),
                                          lambda k=run: self.hotkey_stop.emit(k), self.is_running)
                continue
            if run:
                hm.register_hotkey(run, lambda n=name: self.hotkey_run.emit(n))
            if stop:
                hm.register_hotkey(stop, lambda k=stop: self.hotkey_stop.emit(k))
        self._register_memory_hotkeys(hm)

    def _register_memory_hotkeys(self, hm):
        """메모리 매크로(부가 기능)를 켠 사람: 저장한 값에 정한 키 → 그 값 고정 켜기/끄기(혼자 하는 게임용)."""
        from .icons import memory_on
        if not memory_on():
            return
        try:
            from engine import memory as mm
            vals = mm.load_values()
        except Exception:
            return
        for name, sp in vals.items():
            if sp.get("hotkey"):
                hm.register_hotkey(sp["hotkey"], lambda n=name: QTimer.singleShot(0, lambda: self.toggle_memory_freeze(n)))

    def toggle_memory_freeze(self, name: str):
        from engine import memory as mm
        from engine.memwrite import Freezer, ProcessWriter
        sp = mm.load_values().get(name)
        if not sp:
            return
        pid = mm.pid_of_process(sp["process"]) if sp.get("process") else None
        if not pid:
            self.statusBar.showMessage(tr("'{n}': 프로그램이 켜져 있지 않아요").format(n=name), 6000)
            return
        fz = getattr(self, "_mem_freezers", {}).get(pid)
        try:
            if fz is None:
                self._mem_freezers = getattr(self, "_mem_freezers", {})
                fz = self._mem_freezers[pid] = Freezer(ProcessWriter(pid), 0.1)
            cur = fz.w.value(sp)
            on = fz.toggle("name:" + name, sp, sp.get("freeze_to", cur))
            self.statusBar.showMessage((tr("'{n}' 고정 켜짐({v})") if on else tr("'{n}' 고정 꺼짐")).format(
                n=name, v=sp.get("freeze_to", cur)), 6000)
        except mm.MemoryError_ as e:
            self.statusBar.showMessage(str(e), 8000)

    # ================================================================ 종료
    def closeEvent(self, e):
        if self.is_running():
            if QMessageBox.question(self, tr("종료"), tr("'{name}' 이(가) 실행 중입니다. 멈추고 종료할까요?").format(name=self.running_name),
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                e.ignore()
                return
            self.run_thread.stop(tr("프로그램 닫기"))
            self.run_thread.wait(5000)
        if self.hotkey_manager is not None:
            try:
                self.hotkey_manager.clear_all_hotkeys()
                self.hotkey_manager._stop_listener()
            except Exception:
                pass
        try:
            from engine import guard
            guard.mark_app_closed()              # 사람이 닫음 → 지킴이는 다시 켜지 않음
        except Exception:
            pass
        e.accept()

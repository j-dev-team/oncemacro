"""
v2 매크로 편집기.

왼쪽: 스텝 트리(만약 → 그러면/아니면, 반복·묶음 → 할 일). 추가·안에 추가·삭제·위/아래·복사·붙여넣기·
      감싸기·밖으로 빼기·스텝 하나 시험.
오른쪽: 고른 스텝의 입력칸(StepForm).
위: 매크로 설정(이름·설명·창·반복·회차 실패 처리·핫키).
아래: 형식 검사 결과(오류가 있으면 저장 안 됨, 오류 스텝은 빨간색).

원본은 깊은 복사본(MacroModel)으로 고치고, 입력칸은 자기 키만 덮어써서 모르는 값은 보존된다.
"""
from __future__ import annotations

import copy
import re
from typing import List, Optional, Tuple

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QScrollArea, QSplitter, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from engine.model import COMMON_STEP_KEYS, DEFAULT_SETTINGS, STEP_SPECS, MacroError, validate_macro
from gui.v2.describe import BRANCH_NAMES, STEP_NAMES, STEP_ORDER, step_text
from gui.v2.i18n import tr
from ..icons import PALETTE, step_icon
from gui.v2.model import MacroModel, StepNode, default_step, walk
from .friendly import friendly, friendly_list
from .step_form import JsonDialog, StepForm
from .widgets import ABSENT, OptValue, apply_opt, spin
from ..widgets import STEP_NUM_ROLE

ROLE = Qt.UserRole
_CLIPBOARD: List[dict] = []          # 편집기끼리 복사·붙여넣기(매크로 사이에도)
_PATH_RE = re.compile(r"^(steps(?:\[\d+\](?:\.(?:then|else|steps))?)*\[\d+\])")


def _has(icon_name: str) -> bool:
    from ..design.assets import has_icon
    return has_icon(icon_name)


def _EditorStepDelegate(parent=None):
    from ..widgets import StepRowDelegate
    return StepRowDelegate(parent=parent, editor=True)


def new_step_data(t: str) -> dict:
    """새 스텝 기본값. 클릭·이동·끌기는 누를 곳을 비워 둔다 — (0,0) 같은 기본 좌표로 왼쪽 위 구석을
    누르는 일을 막는다. 비어 있으면 엔진 검사가 저장·시험·실행을 막고, 입력칸이 '화면에서 찍기'를 앞에 보여 준다."""
    d = default_step(t)
    if t in ("click", "move"):
        d.pop("target", None)
    elif t == "drag":
        d.pop("from", None)
        d.pop("to", None)
    return d


def error_step_path(err: str) -> Optional[str]:
    """'steps[1].then[0].target.region: …' → 'steps[1].then[0]'"""
    m = _PATH_RE.match(err)
    return m.group(1) if m else None


class MacroEditorDialog(QDialog):
    def __init__(self, store, name: str, parent=None, env_factory=None):
        super().__init__(parent)
        self.store = store
        self.name = name
        self.env_factory = env_factory
        self.original = store.load(name)
        self.model = MacroModel(self.original)
        self.saved_name: Optional[str] = None
        self.updated_callers: List[str] = []
        self.dirty = False
        self._items_by_path = {}
        self._test_thread = None
        self.setWindowTitle(tr("매크로 편집 — {name}").format(name=name))
        self.resize(1280, 860)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)

        from .screen_picker import ScreenTools
        self.tools = ScreenTools(self, window_title=self._window_title,
                                 default_folder=lambda: "mcp/" + (self.name_edit.text().split("_")[0] or "gui"),
                                 hide_widgets=lambda: [self, self.parent()])
        self._validate_timer = QTimer(self)
        self._validate_timer.setSingleShot(True)
        self._validate_timer.timeout.connect(self.validate)
        self._build()
        self._fill_meta()
        self.rebuild_tree()
        self.validate()

    # ================================================================ UI
    def _build(self):
        """새 화면(시안 A) 편집기: 위 막대(이름·스텝 도구·저장) / 설정 한 줄 + 더 보기 / 부품 상자 | 스텝 트리 | 스텝 입력칸."""
        from ..design import theme as _theme
        from ..design.assets import icon as _icon
        from ..widgets import StepRowDelegate, card, label
        t = _theme.current()
        pad, gap = t["pad"], t["gap"]
        self.setObjectName("Root")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # ── 위 막대: 이름 + 스텝 도구 + 저장
        bar = QWidget()
        bar.setObjectName("Bar")
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(pad, 12, pad, 8)
        bh.setSpacing(6)
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("TitleEdit")
        self.name_edit.setToolTip(tr("이름"))
        self.name_edit.setMinimumWidth(180)
        self.name_edit.setMaximumWidth(360)
        self.name_edit.setStyleSheet(
            f"QLineEdit#TitleEdit{{font-size:{t['font_subtitle'] + 2}px; font-weight:600; background:transparent;"
            f" border:1px solid transparent; padding:0 6px;}}"
            f"QLineEdit#TitleEdit:hover{{border:1px solid {t['line']};}}"
            f"QLineEdit#TitleEdit:focus{{border:1px solid {t['accent']}; background:{t['surface']};}}")
        bh.addWidget(self.name_edit, 1)
        bh.addSpacing(8)

        def tb(text, ic, fn=None, menu=None, beside=True):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(text)
            b.setIcon(_icon(ic, t["text"], 18))
            b.setIconSize(QSize(18, 18))
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if beside else Qt.ToolButtonIconOnly)
            b.setFixedHeight(t["control_h"])
            b.setCursor(Qt.PointingHandCursor)
            if menu is not None:
                b.setMenu(menu)
                b.setPopupMode(QToolButton.InstantPopup)
            if fn is not None:
                b.clicked.connect(lambda _=False, f=fn: f())
            bh.addWidget(b)
            return b

        self.add_btn = tb(tr("스텝 추가"), "plus", menu=self._type_menu(self.add_step))
        self.add_in_btn = tb(tr("안에 추가"), "corner-down-right", menu=self._type_menu(self.add_inside), beside=False)
        wm = QMenu(self)
        for k in ("group", "repeat", "if"):
            wm.addAction(tr("{name} 안에 넣기").format(name=tr(STEP_NAMES[k])), lambda k=k: self.wrap_selected(k))
        tb(tr("감싸기"), "folder", menu=wm, beside=False)
        tb(tr("밖으로 빼기"), "log-out", self.unwrap_selected, beside=False)
        bh.addWidget(self._sep(t))
        tb(tr("복사"), "copy", self.copy_selected, beside=False)
        tb(tr("붙여넣기"), "clipboard-paste" if _has("clipboard-paste") else "clipboard", self.paste, beside=False)
        tb(tr("삭제"), "trash", self.delete_selected, beside=False)
        tb(tr("위로"), "arrow-up", lambda: self.move_selected(-1), beside=False)
        tb(tr("아래로"), "arrow-down", lambda: self.move_selected(1), beside=False)
        bh.addWidget(self._sep(t))
        tb(tr("이 스텝 시험"), "play", self.test_selected)
        bh.addStretch(1)
        cb = QPushButton(tr("취소"))
        cb.setAutoDefault(False)
        cb.clicked.connect(self.reject)
        sb = QPushButton(" " + tr("저장"))
        sb.setObjectName("Primary")
        sb.setIcon(_icon("check", t["on_accent"], 16))
        sb.setDefault(True)
        sb.clicked.connect(self.save)
        for b in (cb, sb):
            bh.addWidget(b)
        v.addWidget(bar)

        # ── 설정 한 줄(대상 창·뒤에서 실행·반복) + 더 보기
        meta = card()
        mv = QVBoxLayout(meta)
        mv.setContentsMargins(pad - 6, 8, pad - 6, 8)
        mv.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.win_combo = QComboBox()
        self.win_combo.setEditable(True)
        self.win_combo.setMinimumWidth(150)
        self.win_combo.lineEdit().setPlaceholderText(tr("비우면 화면 전체"))
        self.win_combo.setToolTip(tr("창 제목 일부. 넣으면 모든 좌표·영역이 그 창 안쪽 기준이 됩니다."))
        rb = QToolButton()
        rb.setIcon(_icon("app-window", t["text"], 18))
        rb.setToolTip(tr("열린 창 목록"))
        rb.clicked.connect(self._refresh_windows)
        self.bg_check = QCheckBox(tr("뒤에서 실행"))
        self.bg_check.setToolTip(tr("창을 앞으로 안 가져오고 진짜 마우스도 안 씀(다른 작업 가능). "
                                    "창이 가려져 있어도 됨. 최소화돼 있으면 화면에 안 보이게 되살려서 이어 감(끝나면 다시 최소화). 키 입력은 프로그램에 따라 안 먹을 수 있음"))
        self.hide_check = QCheckBox(tr("숨겨서 실행"))
        self.hide_check.setToolTip(tr("실행하는 동안 대상 창을 화면에서 안 보이게 둡니다. 끝나면 원래대로 돌아옵니다. 뒤에서 실행을 켜야 쓸 수 있음"))
        self.nowrap_check = QCheckBox(tr("호환 모드"))
        self.nowrap_check.setToolTip(tr("어떤 프로그램에서 뒤에서 실행이 시작되지 않거나 보안 프로그램과 부딪힐 때 켜 보세요. "
                                        "대신 일부 프로그램은 클릭이 안 먹을 수 있음"))
        qb = QToolButton()
        qb.setIcon(_icon("circle-question-mark", t["muted"], 16))
        qb.setToolTip(tr("'뒤에서 실행'이 무엇인지, 언제 켜는지, 안 먹을 때 확인할 것"))

        def _bg_help():
            from ..help_text import background_help, show_html
            from gui.v2.i18n import tr as _tr
            show_html(self, _tr("뒤에서 실행이란"), background_help())
        qb.clicked.connect(_bg_help)
        self.rep_mode = QComboBox()
        self.rep_mode.addItem(tr("정해진 횟수"), "times")
        self.rep_mode.addItem(tr("계속(정지할 때까지)"), "forever")
        self.rep_times = spin(1, 1000000, 1, 90)
        self.more_btn = QToolButton()
        self.more_btn.setText(tr("고급 설정"))
        self.more_btn.setToolTip(tr("설명·실패 처리·핫키·뒤에서 실행 방식·AI 도우미·스스로 고치기·글로 직접 고치기"))
        self.more_btn.setCheckable(True)
        self.more_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.more_btn.setIcon(_icon("chevron-down", t["text"], 16))
        for w in (label(tr("대상 창"), "Section"), self.win_combo, rb, self.bg_check, self.hide_check, qb):
            row.addWidget(w)
        row.addSpacing(10)
        for w in (label(tr("반복"), "Section"), self.rep_mode, self.rep_times):
            row.addWidget(w)
        row.addStretch(1)
        row.addWidget(self.more_btn)
        mv.addLayout(row)

        # 더 보기 칸
        self.more_box = QWidget()
        mf = QFormLayout(self.more_box)
        mf.setContentsMargins(0, 4, 0, 0)
        mf.setHorizontalSpacing(12)
        mf.setVerticalSpacing(8)
        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText(tr("이 매크로가 하는 일(선택)"))
        mf.addRow(tr("설명"), self.desc_edit)
        frow = QHBoxLayout()
        self.fail_mode = QComboBox()
        self.fail_mode.addItem(tr("회차 실패 시 멈춤"), "stop")
        self.fail_mode.addItem(tr("회차 실패 시 그 회차 다시"), "retry")
        self.fail_max = OptValue(tr("기본값(3)"), tr("무제한"), 1, 1000, 0, 1, 3, integer=True)
        self.fail_delay = OptValue(tr("기본값(1초)"), None, 0, 600, 1, 0.5, 1.0)
        for w in (self.fail_mode, QLabel(tr("연속 최대")), self.fail_max, QLabel(tr("다시 하기 전 대기(초)")), self.fail_delay):
            frow.addWidget(w)
        frow.addStretch(1)
        mf.addRow(tr("실행"), frow)
        hrow = QHBoxLayout()
        self.hk_run = QLineEdit()
        self.hk_stop = QLineEdit()
        for e in (self.hk_run, self.hk_stop):
            e.setReadOnly(True)
            e.setFixedWidth(130)
        b1 = QPushButton(tr("실행 핫키"))
        b2 = QPushButton(tr("정지 핫키"))
        b3 = QPushButton(tr("핫키 지우기"))
        for b in (b1, b2, b3):
            b.setMinimumWidth(0)
        b1.clicked.connect(lambda: self._pick_hotkey(self.hk_run, tr("실행 핫키")))
        b2.clicked.connect(lambda: self._pick_hotkey(self.hk_stop, tr("정지 핫키")))
        b3.clicked.connect(lambda: (self.hk_run.clear(), self.hk_stop.clear(), self._meta_changed()))
        for w in (b1, self.hk_run, b2, self.hk_stop, b3, label(tr("같은 키 = 실행/정지 토글"), "Muted")):
            hrow.addWidget(w)
        hrow.addStretch(1)
        mf.addRow(tr("핫키"), hrow)
        mf.addRow(tr("뒤에서 실행 방식"), self.nowrap_check)
        ai = self._build_ai_group()
        mf.addRow(ai)
        jrow = QHBoxLayout()
        jb = QPushButton(tr("매크로 전체를 글로 고치기(JSON)"))
        jb.setMinimumWidth(0)
        jb.clicked.connect(self._edit_macro_json)
        jb.setAutoDefault(False)
        self.json_btn = jb
        jrow.addWidget(jb)
        jrow.addStretch(1)
        mf.addRow(tr("직접 고치기"), jrow)
        self.more_box.setVisible(False)
        self.more_btn.toggled.connect(self._toggle_more)
        mv.addWidget(self.more_box)
        mw = QWidget()
        ml = QVBoxLayout(mw)
        ml.setContentsMargins(pad, 0, pad, 0)
        ml.addWidget(meta)
        v.addWidget(mw)

        for w in (self.name_edit, self.desc_edit):
            w.textChanged.connect(self._meta_changed)
        self.win_combo.currentTextChanged.connect(self._meta_changed)
        self.win_combo.currentTextChanged.connect(lambda tx: self.bg_check.setEnabled(bool(tx.strip())))
        self.bg_check.toggled.connect(self._meta_changed)
        self.bg_check.toggled.connect(lambda on: self.nowrap_check.setEnabled(on))
        self.bg_check.toggled.connect(lambda on: self.hide_check.setEnabled(on))
        self.nowrap_check.toggled.connect(self._meta_changed)
        self.hide_check.toggled.connect(self._meta_changed)
        self.rep_mode.currentIndexChanged.connect(self._meta_changed)
        self.rep_times.valueChanged.connect(self._meta_changed)
        self.fail_mode.currentIndexChanged.connect(self._meta_changed)
        self.fail_max.changed.connect(self._meta_changed)
        self.fail_delay.changed.connect(self._meta_changed)

        # ── 본문: 부품 상자 | 스텝 트리 | 스텝 입력칸
        body = QWidget()
        hb = QHBoxLayout(body)
        hb.setContentsMargins(pad, gap, pad, 4)
        hb.setSpacing(0)
        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(gap)
        hb.addWidget(split)
        split.addWidget(self._build_palette())
        tree_card = card()
        tv = QVBoxLayout(tree_card)
        tv.setContentsMargins(6, 10, 6, 6)
        tv.setSpacing(4)
        th = QHBoxLayout()
        th.setContentsMargins(10, 0, 10, 0)
        self.tree_title = label(tr("스텝"), "Section")
        th.addWidget(self.tree_title)
        th.addStretch(1)
        th.addWidget(label(tr("오른쪽 클릭: 복사·옮기기·시험"), "Muted"))
        tv.addLayout(th)
        from ..widgets import ChevronTree
        self.tree = ChevronTree()
        self.tree.setHeaderLabels([tr("스텝")])
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(20)
        self.tree.setItemDelegate(_EditorStepDelegate(parent=self.tree))
        self.tree.currentItemChanged.connect(self._on_current)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        tv.addWidget(self.tree)
        split.addWidget(tree_card)

        from gui.v3.macro_picker import PickerSource
        self.form = StepForm(self.tools, macro_names=lambda: [n for n in self.store.names() if n != self.name],
                             picker_source=lambda: PickerSource.from_store(self.store, exclude=[self.name]))
        self.form.changed.connect(self._step_changed)
        self.form.type_change_requested.connect(self._change_type)
        form_card = card()
        fv = QVBoxLayout(form_card)
        fv.setContentsMargins(4, 6, 4, 4)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QScrollArea.NoFrame)
        sc.setWidget(self.form)
        sc.viewport().setAutoFillBackground(False)
        self.form.setAutoFillBackground(False)
        fv.addWidget(sc)
        split.addWidget(form_card)
        form_card.setMinimumWidth(420)          # 1280 화면에서도 입력칸 글자가 잘리지 않게
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 1)
        split.setSizes([190, 500, 560])
        v.addWidget(body, 1)

        # ── 아래: 형식 검사 결과
        foot = QHBoxLayout()
        foot.setContentsMargins(pad + 4, 2, pad, 8)
        self.status = QLabel()
        self.status.setWordWrap(True)
        foot.addWidget(self.status, 1)
        v.addLayout(foot)

    def _sep(self, t):
        s = QFrame()
        s.setFixedSize(1, 20)
        s.setStyleSheet(f"background:{t['line']};")
        return s

    def _toggle_more(self, on: bool):
        from ..design import theme as _theme
        from ..design.assets import icon as _icon
        self.more_box.setVisible(on)
        self.more_btn.setIcon(_icon("chevron-up" if on else "chevron-down", _theme.current()["text"], 16))

    def _build_ai_group(self) -> QGroupBox:
        """막히면 AI 한 번 부르기(꺼짐이 기본). 켜기·횟수 한도·저장된 해결 규칙 지우기."""
        g = QGroupBox(tr("막히면 AI 한 번 부르기"))
        lay = QVBoxLayout(g)
        row = QHBoxLayout()
        self.ai_check = QCheckBox(tr("켜기"))
        self.ai_check.setToolTip(tr("스텝이 다시 시도까지 다 실패해 실행이 멈추기 직전에만, 이 컴퓨터의 AI 프로그램을 한 번 부릅니다. 기본은 꺼짐"))
        self.ai_hour = spin(1, 1000, 3, 70)
        self.ai_day = spin(1, 10000, 10, 70)
        self.ai_count = QLabel()
        self.ai_clear = QPushButton(tr("저장된 해결 지우기"))
        self.ai_clear.setMinimumWidth(0)
        self.ai_clear.clicked.connect(self._clear_rescues)
        for w in (self.ai_check, QLabel(tr("시간당")), self.ai_hour, QLabel(tr("하루")), self.ai_day,
                  QLabel("   "), self.ai_count, self.ai_clear):
            row.addWidget(w)
        row.addStretch(1)
        lay.addLayout(row)
        self.ai_cli = QLabel()
        lay.addWidget(self.ai_cli)
        note = QLabel(tr("막혔을 때 그 순간의 화면 사진이 이 컴퓨터의 AI 프로그램으로 보내집니다. 화면에 개인정보가 보이면 함께 보내질 수 있습니다."))
        note.setWordWrap(True)
        note.setStyleSheet("color:#a05000")
        lay.addWidget(note)
        # 스스로 고치기(오래 돌며 이상해지는 것 알아채기·고치기). 기본 끔
        hrow = QHBoxLayout()
        self.heal_mode = QComboBox()
        for label, val in ((tr("끔"), "off"), (tr("알림만"), "notify"), (tr("값 조정까지"), "tune"),
                           (tr("고칠 방법 제안까지"), "propose")):
            self.heal_mode.addItem(label, val)
        self.heal_mode.setToolTip(tr("알림만: 진전 없음·인식 점수 하락·처음 보는 창·느려짐을 알아채 기록만 합니다.\n"
                                     "값 조정까지: 그림 다시 따기·기다리는 시간 같은 값을 시험 삼아 바꿔 보고, 나빠지면 되돌립니다.\n"
                                     "고칠 방법 제안까지: 스텝을 더하거나 바꾸는 방법을 제안하고, 사람이 승인해야 반영합니다."))
        self.heal_watch = QLineEdit()
        self.heal_watch.setPlaceholderText(tr("목표 변수(쉼표로, 예: 남은개수) — 이 값이 안 변하면 '진전 없음'"))
        for w in (QLabel(tr("스스로 고치기")), self.heal_mode, self.heal_watch):
            hrow.addWidget(w)
        lay.addLayout(hrow)
        self.heal_mode.currentIndexChanged.connect(self._meta_changed)
        self.heal_watch.textChanged.connect(self._meta_changed)
        for w in (self.ai_hour, self.ai_day):
            w.valueChanged.connect(self._meta_changed)
        self.ai_check.toggled.connect(self._meta_changed)
        self.ai_check.clicked.connect(self._ai_check_clicked)
        return g

    def _ai_check_clicked(self, on: bool):
        """켤 때 이 컴퓨터에서 아직 동의 안 했으면 동의를 받는다(안 하면 도로 끔)."""
        if not on:
            return
        try:
            from engine.rescue import load_ai_config, save_ai_config
            cfg = load_ai_config(self.store.root)
            if cfg.get("consent") is True:
                return
            ok = QMessageBox.question(self, tr("막히면 AI 한 번 부르기"), tr("막혔을 때 그 순간의 화면 사진과 실행 기록이 이 컴퓨터의 AI 프로그램을 거쳐 AI 서비스로 전송됩니다. 화면에 개인정보가 보이면 함께 전송될 수 있습니다. 동의합니까?")) == QMessageBox.Yes
            if ok:
                cfg["consent"] = True
                save_ai_config(self.store.root, cfg)
        except Exception:
            ok = False
        if not ok:
            self.ai_check.setChecked(False)

    def _ai_cli_text(self) -> str:
        try:
            from engine.rescue import CliAI, load_ai_config
            name = CliAI(load_ai_config(self.store.root)).describe()
        except Exception:
            name = ""
        return tr("찾은 명령줄 AI: {name}").format(name=name or tr("없음"))

    def _rescue_count(self) -> int:
        r = self.model.meta.get("rescues")
        return len(r) if isinstance(r, list) else 0

    def _refresh_ai_labels(self):
        n = self._rescue_count()
        self.ai_count.setText(tr("저장된 해결 {n}개").format(n=n))
        self.ai_clear.setEnabled(n > 0)
        self.ai_cli.setText(self._ai_cli_text())

    def _clear_rescues(self):
        n = self._rescue_count()
        if not n:
            return
        if QMessageBox.question(self, tr("저장된 해결 지우기"),
                                tr("저장된 해결 {n}개를 지울까요? 다음에 막히면 AI를 다시 부를 수 있습니다.").format(n=n)
                                ) != QMessageBox.Yes:
            return
        self.model.meta.pop("rescues", None)
        self._refresh_ai_labels()
        self._meta_changed()

    def _build_palette(self) -> QWidget:
        """부품 상자: 스텝 종류를 묶음별 아이콘으로. 더블클릭 = 고른 스텝 아래에 추가."""
        from ..design import theme as _theme
        from ..design.assets import icon as _icon
        from ..widgets import card, label
        th = _theme.current()
        w = card()
        w.setMinimumWidth(170)
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 10, 8, 8)
        v.setSpacing(6)
        v.addWidget(label(tr("부품 상자"), "Section"))
        find = QLineEdit()
        find.setPlaceholderText(tr("부품 찾기"))
        find.setClearButtonEnabled(True)
        find.addAction(_icon("search", th["muted"], 14), QLineEdit.LeadingPosition)
        v.addWidget(find)
        t = QTreeWidget()
        t.setHeaderHidden(True)
        t.setRootIsDecorated(False)
        t.setIndentation(0)
        t.setStyleSheet(f"QTreeWidget::item{{min-height:{th['row_palette']}px; padding-left:6px;}}")
        for title, types in PALETTE:
            g = QTreeWidgetItem([tr(title)])
            f = g.font(0)
            f.setBold(True)
            g.setFont(0, f)
            t.addTopLevelItem(g)
            for k in types:
                it = QTreeWidgetItem([tr(STEP_NAMES.get(k, k))])
                it.setIcon(0, step_icon(k))
                it.setData(0, Qt.UserRole, k)
                it.setToolTip(0, k)
                g.addChild(it)
            g.setExpanded(True)

        def add(item, _col=0):
            k = item.data(0, Qt.UserRole)
            if k:
                self.add_step(k)

        def menu(pos):
            item = t.itemAt(pos)
            k = item.data(0, Qt.UserRole) if item is not None else None
            if not k:
                return
            m = QMenu(t)
            m.addAction(tr("고른 스텝 아래에 추가"), lambda: self.add_step(k))
            m.addAction(tr("고른 스텝 안에 추가(만약·반복·묶음)"), lambda: self.add_inside(k))
            m.exec(t.viewport().mapToGlobal(pos))
        def filt(text):
            q = text.strip().lower()
            for i in range(t.topLevelItemCount()):
                g = t.topLevelItem(i)
                any_shown = False
                for j in range(g.childCount()):
                    c = g.child(j)
                    hit = not q or q in c.text(0).lower() or q in (c.data(0, Qt.UserRole) or "")
                    c.setHidden(not hit)
                    any_shown = any_shown or hit
                g.setHidden(not any_shown)
        find.textChanged.connect(filt)
        t.itemDoubleClicked.connect(add)
        t.setContextMenuPolicy(Qt.CustomContextMenu)
        t.customContextMenuRequested.connect(menu)
        v.addWidget(t, 1)
        v.addWidget(label(tr("더블클릭: 고른 스텝 아래에 추가 · 오른쪽 클릭: 안에 추가"), "Muted"))
        v.itemAt(v.count() - 1).widget().setWordWrap(True)
        self.palette = t
        self.palette_find = find
        return w

    def _type_menu(self, fn) -> QMenu:
        m = QMenu(self)
        groups = [("마우스", ["click", "move", "drag", "mouse_down", "mouse_up"]),
                  ("키보드", ["key", "type_text", "clipboard"]),
                  ("기다리기", ["wait", "delay"]),
                  ("흐름", ["if", "repeat", "each", "for_each", "group", "break", "continue", "call", "return", "stop"]),
                  ("변수·기타", ["remember", "set", "list", "text", "date", "calc", "set_result", "comment"]),
                  ("파일", ["file"]),
                  ("묻기·알림", ["ask", "notify"]),
                  ("프로그램", ["launch", "close_window", "wait_window", "snapshot"]),
                  ("웹(요소로)", ["web"]),
                  ("오피스", ["excel", "hwp", "word", "pdf", "mail"])]
        from gui.v3.icons import memory_on
        for title, types in groups:
            sub = m.addMenu(tr(title))
            for t in types:
                sub.addAction(tr(STEP_NAMES[t]), lambda t=t: fn(t))
        return m

    # ================================================================ 설정
    def _fill_meta(self):
        meta = self.model.meta
        self.name_edit.setText(meta.get("name", self.name))
        self.desc_edit.setText(meta.get("description", ""))
        self._refresh_windows()
        self.win_combo.setCurrentText(((meta.get("window") or {}).get("title")) or "")
        self.bg_check.setChecked(bool((meta.get("window") or {}).get("background")))
        self.bg_check.setEnabled(bool(self._window_title()))
        self.nowrap_check.setChecked((meta.get("window") or {}).get("wrapper") is False)
        self.nowrap_check.setEnabled(self.bg_check.isChecked())
        self.hide_check.setChecked(bool((meta.get("window") or {}).get("hidden")))
        self.hide_check.setEnabled(self.bg_check.isChecked())
        ai = meta.get("ai_rescue") if isinstance(meta.get("ai_rescue"), dict) else {}
        self.ai_check.setChecked(bool(ai.get("on", False)))
        self.ai_hour.setValue(int(ai.get("per_hour", 3) or 3))
        self.ai_day.setValue(int(ai.get("per_day", 10) or 10))
        self._refresh_ai_labels()
        sh = meta.get("self_heal") if isinstance(meta.get("self_heal"), dict) else {}
        i = self.heal_mode.findData(sh.get("mode", "off"))
        self.heal_mode.setCurrentIndex(i if i >= 0 else 0)
        self.heal_watch.setText(", ".join(x for x in (sh.get("watch_vars") or []) if isinstance(x, str)))
        rep = meta.get("repeat") or {"times": 1}
        self.rep_mode.setCurrentIndex(1 if rep.get("forever") else 0)
        self.rep_times.setValue(int(rep.get("times", 1) or 1))
        self.rep_times.setEnabled(not rep.get("forever"))
        f = meta.get("on_iteration_fail") or {}
        self.fail_mode.setCurrentIndex(1 if f.get("action") == "retry" else 0)
        self.fail_max.set_value(f["max_consecutive"] if "max_consecutive" in f else ABSENT)
        self.fail_delay.set_value(f["delay"] if "delay" in f else ABSENT)
        self._meta_changed_enable()
        self.hk_run.setText(meta.get("run_hotkey", ""))
        self.hk_stop.setText(meta.get("stop_hotkey", ""))
        self._meta_loaded = self._widget_state()
        self.dirty = False

    def _widget_state(self) -> dict:
        return {"name": self.name_edit.text().strip(), "desc": self.desc_edit.text().strip(),
                "win": self._window_title(), "bg": self.bg_check.isChecked(),
                "nowrap": self.nowrap_check.isChecked(), "hidden": self.hide_check.isChecked(),
                "ai": (self.ai_check.isChecked(), int(self.ai_hour.value()), int(self.ai_day.value())),
                "heal": (self.heal_mode.currentData(), self.heal_watch.text().strip()),
                "rep": (self.rep_mode.currentData(), int(self.rep_times.value())),
                "fail": (self.fail_mode.currentData(), self.fail_max.value(), self.fail_delay.value()),
                "run_hotkey": self.hk_run.text().strip(), "stop_hotkey": self.hk_stop.text().strip()}

    def _refresh_windows(self):
        cur = self.win_combo.currentText()
        titles = []
        try:
            from engine.win_window import list_windows
            for w in list_windows():
                t = (w.title or "").strip()
                if t and t not in titles and t != self.windowTitle():
                    titles.append(t)
        except Exception:
            pass
        self.win_combo.blockSignals(True)
        self.win_combo.clear()
        self.win_combo.addItem("")
        self.win_combo.addItems(titles)
        self.win_combo.setCurrentText(cur)
        self.win_combo.blockSignals(False)

    def _window_title(self) -> Optional[str]:
        t = self.win_combo.currentText().strip()
        return t or None

    def _collect_meta(self):
        """바뀐 칸만 meta 에 반영한다(안 고친 칸은 원래 값·키 그대로)."""
        m = self.model.meta
        cur, old = self._widget_state(), getattr(self, "_meta_loaded", {})
        if cur["name"] != old.get("name") or "name" not in m:
            m["name"] = cur["name"]
        if cur["desc"] != old.get("desc"):
            if cur["desc"]:
                m["description"] = cur["desc"]
            else:
                m.pop("description", None)
        if cur["win"] != old.get("win"):
            if cur["win"]:
                w = copy.deepcopy(m.get("window")) if isinstance(m.get("window"), dict) else {}
                w["title"] = cur["win"]
                m["window"] = w
            else:
                m.pop("window", None)
        if cur["bg"] != old.get("bg") and isinstance(m.get("window"), dict):
            if cur["bg"]:
                m["window"]["background"] = True
            else:
                m["window"].pop("background", None)
        if (cur["hidden"] != old.get("hidden") or cur["bg"] != old.get("bg")) and isinstance(m.get("window"), dict):
            if cur["hidden"] and cur["bg"]:
                m["window"]["hidden"] = True
            else:
                m["window"].pop("hidden", None)
        if cur["nowrap"] != old.get("nowrap") and isinstance(m.get("window"), dict):
            if cur["nowrap"]:
                m["window"]["wrapper"] = False
            else:
                m["window"].pop("wrapper", None)
        if cur["ai"] != old.get("ai"):
            on, per_hour, per_day = cur["ai"]
            a = copy.deepcopy(m.get("ai_rescue")) if isinstance(m.get("ai_rescue"), dict) else {}
            a["on"], a["per_hour"], a["per_day"] = on, per_hour, per_day
            if not on and per_hour == 3 and per_day == 10 and set(a) <= {"on", "per_hour", "per_day"}:
                m.pop("ai_rescue", None)          # 기본값·꺼짐이면 키 자체를 없앰
            else:
                m["ai_rescue"] = a
        if cur.get("heal") != old.get("heal"):
            hmode, watch = cur["heal"]
            sh = copy.deepcopy(m.get("self_heal")) if isinstance(m.get("self_heal"), dict) else {}
            sh["mode"] = hmode
            wv = [x.strip() for x in watch.replace("，", ",").split(",") if x.strip()]
            if wv:
                sh["watch_vars"] = wv
            else:
                sh.pop("watch_vars", None)
            if hmode == "off" and set(sh) <= {"mode"}:
                m.pop("self_heal", None)          # 끔·기본값이면 키 자체를 없앰
            else:
                m["self_heal"] = sh
        if cur["rep"] != old.get("rep"):
            mode, times = cur["rep"]
            m["repeat"] = {"forever": True} if mode == "forever" else {"times": times}
        if cur["fail"] != old.get("fail"):
            mode, mx, delay = cur["fail"]
            f = copy.deepcopy(m.get("on_iteration_fail")) if isinstance(m.get("on_iteration_fail"), dict) else {}
            f["action"] = mode
            apply_opt(f, "max_consecutive", mx)
            apply_opt(f, "delay", delay)
            m["on_iteration_fail"] = f
        for key in ("run_hotkey", "stop_hotkey"):
            if cur[key] != old.get(key):
                if cur[key]:
                    m[key] = cur[key]
                else:
                    m.pop(key, None)

    def _meta_changed_enable(self):
        self.rep_times.setEnabled(self.rep_mode.currentData() != "forever")
        retry = self.fail_mode.currentData() == "retry"
        self.fail_max.setEnabled(retry)
        self.fail_delay.setEnabled(retry)

    def _meta_changed(self, *_):
        self._meta_changed_enable()
        self.dirty = True
        self._validate_soon()

    def _pick_hotkey(self, edit: QLineEdit, title: str):
        from gui.v3.hotkey_dialog import HotkeyDialog
        d = HotkeyDialog(self, title, edit.text())
        if d.exec():
            edit.setText(d.get_hotkey() or "")
            self._meta_changed()

    # ================================================================ 트리
    def rebuild_tree(self, select: Optional[object] = None):
        """select: StepNode 또는 (부모 노드, 가지 키)."""
        self.tree.blockSignals(True)
        self.tree.clear()
        sel_item = None
        try:
            self.tree_title.setText(tr("스텝 {n}개").format(n=sum(1 for _ in walk(self.model.steps))))
        except Exception:
            pass

        def add(parent_item, nodes: List[StepNode]):
            nonlocal sel_item
            for num, n in enumerate(nodes, 1):
                it = QTreeWidgetItem([step_text(n.data)])
                it.setData(0, STEP_NUM_ROLE, num)
                it.setIcon(0, step_icon(n.data.get("type", "") if isinstance(n.data, dict) else ""))
                it.setData(0, ROLE, ("step", n))
                if n.type == "comment":
                    it.setForeground(0, QBrush(QColor("#777777")))
                (parent_item.addChild(it) if parent_item is not None else self.tree.addTopLevelItem(it))
                if n is select:
                    sel_item = it
                if n.type == "if":
                    for k in ("then", "else"):
                        h = QTreeWidgetItem([tr(BRANCH_NAMES[k])])
                        h.setData(0, ROLE, ("branch", n, k))
                        h.setForeground(0, QBrush(QColor("#1565c0")))
                        it.addChild(h)
                        if isinstance(select, tuple) and select[0] is n and select[1] == k:
                            sel_item = h
                        add(h, n.children(k))
                        h.setExpanded(True)
                elif n.is_container():
                    add(it, n.children("steps"))
                it.setExpanded(True)

        add(None, self.model.steps)
        self.tree.blockSignals(False)
        if sel_item is not None:
            self.tree.setCurrentItem(sel_item)
            self.tree.scrollToItem(sel_item)
        else:
            self._on_current(self.tree.currentItem(), None)
        self._mark_errors()

    def _sel(self) -> Tuple[str, object, object]:
        it = self.tree.currentItem()
        if it is None:
            return "none", None, None
        d = it.data(0, ROLE)
        if d[0] == "step":
            return "step", d[1], None
        return "branch", d[1], d[2]

    def _locate(self, node: StepNode, nodes: Optional[List[StepNode]] = None, parent=None, key=None):
        """노드가 들어 있는 (목록, 위치, 부모 노드, 가지 키)."""
        nodes = self.model.steps if nodes is None else nodes
        for i, n in enumerate(nodes):
            if n is node:
                return nodes, i, parent, key
            for k in n.child_keys():
                r = self._locate(node, n.children(k), n, k)
                if r:
                    return r
        return None

    def _insert(self, new: StepNode):
        kind, a, b = self._sel()
        if kind == "step":
            lst, i, _, _ = self._locate(a)
            lst.insert(i + 1, new)
        elif kind == "branch":
            a.children(b, create=True).append(new)
        else:
            self.model.steps.append(new)
        self._structure_changed(new)

    def add_step(self, t: str):
        self._insert(StepNode(new_step_data(t)))

    def add_inside(self, t: str):
        kind, a, b = self._sel()
        new = StepNode(new_step_data(t))
        if kind == "branch":
            a.children(b, create=True).append(new)
        elif kind == "step" and a.is_container():
            a.children(a.child_keys()[0], create=True).append(new)
        else:
            QMessageBox.information(self, tr("안에 추가"), tr("만약·반복·묶음 스텝(또는 그 '그러면/아니면')을 고른 뒤 쓰세요."))
            return
        self._structure_changed(new)

    def delete_selected(self):
        kind, a, b = self._sel()
        if kind != "step":
            return
        lst, i, parent, key = self._locate(a)
        if a.is_container() and any(a.children(k) for k in a.child_keys()):
            if QMessageBox.question(self, tr("삭제"), tr("안에 든 스텝까지 모두 지울까요?"),
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        del lst[i]
        nxt = lst[min(i, len(lst) - 1)] if lst else ((parent, key) if parent is not None else None)
        self._structure_changed(nxt)

    def move_selected(self, d: int):
        kind, a, _ = self._sel()
        if kind != "step":
            return
        lst, i, _, _ = self._locate(a)
        j = i + d
        if 0 <= j < len(lst):
            lst[i], lst[j] = lst[j], lst[i]
            self._structure_changed(a)

    def copy_selected(self):
        kind, a, _ = self._sel()
        if kind == "step":
            _CLIPBOARD[:] = [a.to_dict()]
            self.status.setText(tr("스텝 복사됨 — 붙여넣기는 고른 스텝 다음(또는 고른 가지 안)에 들어갑니다."))

    def paste(self):
        if not _CLIPBOARD:
            return
        self._insert(StepNode(copy.deepcopy(_CLIPBOARD[0])))

    def wrap_selected(self, t: str):
        kind, a, _ = self._sel()
        if kind != "step":
            return
        lst, i, _, _ = self._locate(a)
        w = StepNode(new_step_data(t))
        w.children("then" if t == "if" else "steps", create=True).append(a)
        lst[i] = w
        self._structure_changed(w)

    def unwrap_selected(self):
        """고른 스텝을 감싼 만약·반복·묶음 밖(바로 다음 자리)으로 꺼낸다."""
        kind, a, _ = self._sel()
        if kind != "step":
            return
        lst, i, parent, _ = self._locate(a)
        if parent is None:
            return
        plist, pi, _, _ = self._locate(parent)
        del lst[i]
        plist.insert(pi + 1, a)
        self._structure_changed(a)

    def _structure_changed(self, select=None):
        self.dirty = True
        self.rebuild_tree(select)
        self.validate()              # 스텝을 넣고 빼면 바로 검사(0.3초 사이에 '통과'가 남아 보이지 않게)

    def _tree_menu(self, pos):
        it = self.tree.itemAt(pos)
        if it is not None:
            self.tree.setCurrentItem(it)
        m = QMenu(self)
        for title, fn in ((tr("스텝 추가"), self.add_step), (tr("안에 추가"), self.add_inside)):
            sub = self._type_menu(fn)
            sub.setTitle(title)
            m.addMenu(sub)
        m.addSeparator()
        m.addAction(tr("복사"), self.copy_selected)
        m.addAction(tr("붙여넣기"), self.paste).setEnabled(bool(_CLIPBOARD))
        m.addAction(tr("삭제"), self.delete_selected)
        m.addSeparator()
        m.addAction(tr("위로"), lambda: self.move_selected(-1))
        m.addAction(tr("아래로"), lambda: self.move_selected(1))
        m.addAction(tr("밖으로 빼기"), self.unwrap_selected)
        m.addSeparator()
        m.addAction(tr("이 스텝 시험"), self.test_selected)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    # ================================================================ 입력칸
    def _on_current(self, cur, _prev):
        if cur is None:
            self.form.set_node(None)
            return
        d = cur.data(0, ROLE)
        self.form.set_node(d[1] if d[0] == "step" else None)

    def _step_changed(self):
        it = self.tree.currentItem()
        if it is not None and it.data(0, ROLE)[0] == "step":
            it.setText(0, step_text(it.data(0, ROLE)[1].data))
            it.setIcon(0, step_icon(it.data(0, ROLE)[1].data.get("type", "")))
        self.dirty = True
        self._validate_soon()

    def _change_type(self, new_type: str):
        kind, node, _ = self._sel()
        if kind != "step":
            return
        will_drop = []
        keep = {"if": ("then", "else"), "repeat": ("steps",), "group": ("steps",),
                "for_each": ("steps",), "each": ("steps",)}.get(new_type, ())
        for k, ch in node.branches.items():
            movable = (k == "then" and "steps" in keep) or (k == "steps" and "then" in keep)
            if ch and k not in keep and not movable:
                will_drop.extend(ch)
        if will_drop and QMessageBox.question(
                self, tr("종류 바꾸기"), tr("안에 든 스텝 {n}개가 지워집니다. 바꿀까요?").format(n=len(will_drop)),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            self.form.set_node(node)
            return
        node.set_type(new_type)
        allowed = COMMON_STEP_KEYS | STEP_SPECS.get(new_type, set()) | set(DEFAULT_SETTINGS) | {"type"}
        for k in list(node.data):                         # 새 종류에 없는 필드는 뺀다
            if k not in allowed:
                del node.data[k]
        for k, val in new_step_data(new_type).items():   # 새 종류에 꼭 필요한 값 채우기
            if k not in node.data and k not in node.child_keys():
                node.data[k] = val
        self._structure_changed(node)

    # ================================================================ 검사·저장
    def _validate_soon(self):
        self._validate_timer.start(300)

    def current_macro(self) -> dict:
        self._collect_meta()
        return self.model.to_dict()

    def validate(self) -> List[str]:
        m = self.current_macro()
        errs = validate_macro(m)
        self._errors = errs
        if errs:
            self.status.setText("<span style='color:#c62828'><b>" + tr("고칠 곳 {n}개").format(n=len(errs)) + "</b> — "
                                + "<br>".join(friendly_list(errs, m)) + "</span>")
            self.status.setToolTip("\n".join(errs[:20]))
        elif not m.get("steps"):
            self.status.setText("<span style='color:#666'>" + tr("왼쪽 부품 상자에서 할 일을 더블클릭해 넣으세요.") + "</span>")
            self.status.setToolTip("")
        else:
            self.status.setText("<span style='color:#2e7d32'>" + tr("바로 실행할 수 있어요") + "</span>"
                                + (tr(" — 저장하지 않은 변경 있음") if self.dirty else ""))
            self.status.setToolTip("")
        self._mark_errors()
        return errs

    def _mark_errors(self):
        bad = {}
        for e in getattr(self, "_errors", []) or []:
            p = error_step_path(e)
            if p:
                bad.setdefault(p, []).append(e)
        node_path = {id(n): p for p, n in walk(self.model.steps)}
        md = self.model.to_dict()

        def visit(it: QTreeWidgetItem):
            d = it.data(0, ROLE)
            if d and d[0] == "step":
                p = node_path.get(id(d[1]))
                msgs = bad.get(p)
                default = QColor("#777777") if d[1].type == "comment" else QColor("#000000")
                it.setForeground(0, QBrush(QColor("#c62828") if msgs else default))
                it.setToolTip(0, "\n".join(friendly(e, md) for e in msgs) if msgs else "")
            for i in range(it.childCount()):
                visit(it.child(i))
        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))

    def save(self):
        errs = self.validate()
        if errs:
            p = error_step_path(errs[0])
            node = dict(walk(self.model.steps)).get(p) if p else None
            if node is not None:
                self.rebuild_tree(node)
            # 중간 저장은 되게(고칠 곳 표시는 그대로). 저장된 파일은 엔진 검사에서 걸려 실행·시험·핫키·예약이 막힌다
            if QMessageBox.question(
                    self, tr("저장"),
                    tr("아직 정하지 않은 곳이 있어요:\n\n") + "\n".join(friendly_list(errs, self.current_macro(), 10))
                    + tr("\n\n이대로 저장할까요? 고칠 때까지 실행·시험·핫키·예약 실행은 되지 않아요."),
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
                return
        m = self.current_macro()
        try:
            self.updated_callers = self.store.save(m, old_name=self.name, draft=bool(errs))
        except (MacroError, ValueError, Exception) as e:
            QMessageBox.warning(self, tr("저장"), tr("저장 실패: {e}").format(e=e))
            return
        self.saved_name = m["name"]
        self.dirty = False
        self.accept()

    def reject(self):
        if self._test_thread is not None and self._test_thread.isRunning():
            self._test_thread.stop()
            self._test_thread.wait(3000)
        if self.dirty and QMessageBox.question(self, tr("편집 취소"), tr("저장하지 않은 변경을 버릴까요?"),
                                               QMessageBox.Yes | QMessageBox.No,
                                               QMessageBox.No) != QMessageBox.Yes:
            return
        super().reject()

    def _edit_macro_json(self):
        d = JsonDialog(self.current_macro(), self, title=tr("매크로 JSON"),
                       hint=tr("매크로 전체입니다. 고친 뒤 확인을 누르면 편집기에 반영됩니다(저장은 '저장' 버튼)."))
        if not d.exec():
            return
        if not isinstance(d.value, dict):
            return
        self.model = MacroModel(d.value)
        self._fill_meta()
        self.dirty = True
        self.rebuild_tree()
        self.validate()

    # ================================================================ 스텝 하나 시험
    def test_selected(self):
        kind, node, _ = self._sel()
        if kind != "step":
            QMessageBox.information(self, tr("스텝 시험"), tr("시험할 스텝을 고르세요."))
            return
        meta = self.current_macro()
        mini = {"version": 2, "name": tr("{name} (스텝 시험)").format(name=self.name_edit.text().strip() or self.name),
                "repeat": {"times": 1}, "steps": [node.to_dict()]}
        for k in ("window", "settings"):
            if k in meta:
                mini[k] = copy.deepcopy(meta[k])
        errs = validate_macro(mini)
        if errs:
            QMessageBox.warning(self, tr("스텝 시험"), tr("이 스텝은 아직 시험할 수 없습니다:\n")
                                + "\n".join(friendly_list(errs, mini, 6)))
            return
        if QMessageBox.question(self, tr("스텝 시험"), tr("이 스텝을 실제로 실행합니다(마우스·키보드가 움직임).\n"
                                "멈추려면 Ctrl+Shift+F12.\n계속할까요?"),
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return
        from ..run_thread import RunThread
        from .screen_picker import Concealed
        # 편집기(실행 중인 대화상자)는 hide() 하면 닫혀 버리므로 Concealed 로 잠깐 안 보이게 한다
        self._concealed = Concealed([self, self.parent()])
        self._concealed.__enter__()
        t = RunThread(mini, env_factory=self.env_factory)
        t.run_finished.connect(lambda res, n=node: self._test_done(res, n))
        t.ask_requested.connect(lambda req, th=t: self._on_ask(th, req))
        self._test_thread = t
        t.start()

    def _on_ask(self, thread, req: dict):
        from ..ask_dialog import ask
        status, value = ask(None, req)
        thread.answer(status, value)

    def _test_done(self, res: dict, node: StepNode):
        c = getattr(self, "_concealed", None)
        if c is not None:
            c.__exit__(None, None, None)
            self._concealed = None
        self.raise_()
        self.activateWindow()
        self._test_thread = None
        st = res.get("status")
        word = {"ok": tr("성공"), "failed": tr("실패"), "stopped": tr("정지됨")}.get(st, st)
        msg = tr("결과: {word} ({sec:.2f}초)").format(word=word, sec=res.get('duration', 0))
        if res.get("error"):
            msg += tr("\n이유: {reason}").format(reason=res['error'].get('reason'))
        self.status.setText(tr("스텝 시험 — {msg}").format(msg=msg.replace(chr(10), ' / ')))
        QMessageBox.information(self, tr("스텝 시험"), msg)

"""
스텝 하나의 입력칸 (편집기 오른쪽). 고르는 스텝이 바뀔 때마다 새로 만든다.

입력칸은 자기 키만 node.data 에 덮어쓴다. 화면에 없는 필드(스텝별 설정 덮어쓰기 등)는
'JSON 으로 고치기' 로 고친다.
"""
from __future__ import annotations

import copy
import json
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from gui.v2.describe import (LIST_ACTIONS, MAIL_ACTIONS, MAIL_SERVICES, MAIL_VIAS, ASK_KINDS, CLIPBOARD_ACTIONS, EACH_SOURCES, FILE_ACTIONS, NOTIFY_CHANNELS, OVERWRITE_NAMES,
                              STEP_ORDER_V3 as STEP_ORDER, TEXT_ACTIONS, office_action_name, step_name)
from gui.v2.i18n import tr
from gui.v2.model import StepNode
from .cond_editor import CondEditor
from .target_editor import TargetEditor
from .widgets import ABSENT, LiteralEdit, OptValue, apply_opt, dspin, spin

_NO = object()

HELP = {
    "memory": "메모리 매크로(부가 기능): 대상 프로그램이 들고 있는 값(돈·에너지 등)을 화면 인식 없이 바로 읽어 변수에 넣습니다. 읽기만 하고 바꾸지 않습니다.",
    "list": "목록 변수를 다룹니다: 줄 하나씩 더하기(같은 것 빼기 가능), 칸 기준 정렬(숫자·날짜·글자를 알아서 구분, 여러 칸), 같은 것 빼기, 개수. 다 모은 목록은 엑셀 쓰기·CSV 쓰기에 그대로 넣으세요.",
    "mail": "메일을 찾고, 본문을 읽고, 첨부를 저장하고, 읽음 표시·폴더 옮기기·보내기를 합니다. 아웃룩(이 컴퓨터), 웹메일(네이버·다음·네이트·지메일), 메일 서버 직접 연결 중에 고릅니다.",
    "pdf": "PDF 의 글을 읽습니다. 글 전체, 규칙으로 값 하나(예: 합계 금액), 표를 줄 목록으로 가져올 수 있어요. 워드가 없어도 됩니다.",
    "text": "글자를 만들거나 고쳐서 변수에 넣습니다. 글자 안의 {변수}는 그 값으로 바뀝니다. 예: 파일 이름 '재직_{이름}_{오늘}.hwp', "
            "복사한 글에서 금액만 뽑기, '12,500'을 숫자로.",
    "date": "오늘(또는 정한 날짜)에 날·달을 더하고 원하는 모양의 글자로 만듭니다. 예: yyyy-MM-dd → 2026-11-18, "
            "yyyy년 M월 d일 (요일) → 2026년 11월 18일 (수). '두 날짜 사이'는 날 수를 셉니다.",
    "calc": "숫자 계산 결과를 변수에 넣습니다. 예: 가격 * 수량, round(합계 / 3, 1).",
    "ask": "매크로가 잠깐 멈추고 사람에게 묻습니다(글 입력·예/아니·목록에서 고르기·파일·폴더). 답은 변수에 들어갑니다. "
           "기다릴 시간이 지나거나 AI·명령 줄로 돌릴 때는 기본값을 씁니다(기본값이 없으면 실패).",
    "notify": "윈도우 알림·소리·메신저(웹훅)로 알립니다. 오래 도는 매크로가 끝났거나 문제가 생겼을 때 쓰세요.",
    "each": "목록의 것을 하나씩 변수에 넣고 '할 일'을 되풀이합니다. 엑셀 표의 줄(제목 이름으로 칸을 씀), 폴더 안 파일, "
            "글의 줄, 목록 변수(파일 목록·나누기 결과), 숫자 범위를 돌 수 있어요. 화면의 그림을 하나씩은 '찾은 것마다'를 쓰세요.",
    "file": "파일·폴더를 다룹니다. 지우기는 기본으로 휴지통에 보내 되살릴 수 있고(고급에서 영구 삭제를 고를 수 있음), 같은 이름이 있을 때 어떻게 할지 고릅니다"
            "(기본은 멈춤, '바꾸기'를 골라도 원래 파일은 휴지통으로). 경로 안 {변수}는 값으로 바뀝니다.",
    "clipboard": "복사한 글·파일·그림을 다룹니다. '복사해서 읽기'는 Ctrl+C 를 누르고 새로 복사된 글을 변수에 넣습니다"
                 "(복사가 안 되면 실패). 읽은 글은 '글자 만들기'로 고치고 '만약'의 포함 비교로 판단하세요.",
    "type_text": "글자를 입력합니다(한글 가능). 글자 안의 {변수}는 그 값으로 바뀝니다. 예: '{이름} 님'.",
    "group": "안의 스텝을 차례로 실행합니다. '실패 시 건너뜀' 과 같이 쓰면 중간에 실패해도 나머지를 건너뛰고 다음으로 갑니다.",
    "break": "가장 가까운 반복을 끝냅니다.",
    "continue": "가장 가까운 반복의 이번 회차를 끝내고 다음 회차로 갑니다.",
    "if": "조건이 맞으면 '그러면', 아니면 '아니면' 아래 스텝을 실행합니다. 조건은 한 번이라도 보이면 참입니다.",
    "wait": "조건이 맞을 때까지 기다립니다. 제한 시간이 지나면 실패입니다.",
    "click": "대상이 나타나 자리를 잡으면 클릭합니다. 이미지가 안 보이면 제한 시간까지 기다립니다.",
    "menu": "창 위쪽 메뉴줄의 항목을 이름으로 고릅니다. 창을 앞으로 가져오지 않아 '뒤에서 실행'에서도 됩니다. 표준 메뉴가 없는 프로그램이면 실패합니다(그때는 클릭 스텝에 '이 스텝만 잠깐 앞에서'를 켜세요).",
    "scroll": "마우스 휠을 굴립니다. 위치를 주면 그 자리로 옮긴 뒤 굴립니다. 칸 수 -3 = 아래로 세 칸.",
    "web": "좌표·그림 대신 웹 페이지 요소로 웹 자동화 브라우저를 다룹니다. 선택자 예: text=로그인(보이는 글자), "
           "#아이디, input[name=\"q\"], loc=role:button[name='검색']. 정확히 하나만 맞아야 하고, 여러 개면 끝에 >> nth=0 을 붙입니다. "
           "AI(MCP macro_web_view)가 페이지를 보고 선택자를 골라 줄 수 있습니다.",
    "excel": "엑셀 파일을 화면 좌표가 아니라 셀 이름으로 다룹니다(창이 가려져도 됨). 글자 안 {변수} 는 변수 값으로 바뀝니다 — 예: 칸 B{행}. "
             "먼저 '파일 열기', 끝에 '저장'·'닫기'. 매크로가 켠 엑셀은 매크로가 끝날 때 닫힙니다(저장 안 한 변경은 버림).",
    "hwp": "한글 문서의 누름틀·글자를 이름으로 다룹니다. 누름틀 이름은 한글에서 누름틀 고치기로 정합니다. "
           "처음에 한글 '자동화 보안 승인' 창이 뜨면 허용해 주세요. 글자 안 {변수} 는 변수 값으로 바뀝니다.",
    "word": "워드 문서의 책갈피·글자를 이름으로 다룹니다. 책갈피는 워드의 삽입 → 책갈피로 만듭니다. 글자 안 {변수} 는 변수 값으로 바뀝니다.",
    "for_each": "화면에서 그 그림을 모두 찾아 위→아래(줄 안에서는 왼→오) 순서로 하나씩 변수에 넣고 '할 일'을 실행합니다. "
                "안에서는 대상에 '기준 변수(anchor)'를 주면 그 위치 기준 상대 좌표로 볼 수 있습니다.",
}


class StepForm(QWidget):
    changed = Signal()
    type_change_requested = Signal(str)

    def __init__(self, tools=None, macro_names: Optional[Callable[[], List[str]]] = None, parent=None,
                 picker_source: Optional[Callable] = None):
        super().__init__(parent)
        self.tools = tools
        self.macro_names = macro_names or (lambda: [])
        self.picker_source = picker_source      # 매크로 고르기 창(검색·묶음)용. 없으면 이름 목록으로
        self.node: Optional[StepNode] = None
        self._loading = False
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(4, 4, 4, 4)
        self.body: Optional[QWidget] = None
        self.set_node(None)

    # ================================================================ 만들기
    def set_node(self, node: Optional[StepNode]):
        self.node = node
        if self.body is not None:
            self.body.setParent(None)
            self.body.deleteLater()
        self.body = QWidget()
        self.outer.addWidget(self.body)
        v = QVBoxLayout(self.body)
        v.setContentsMargins(0, 0, 0, 0)
        if node is None:
            v.addWidget(QLabel(tr("왼쪽에서 스텝을 고르거나 '스텝 추가' 로 새로 만드세요.")))
            v.addStretch(1)
            return
        self._loading = True
        f = QFormLayout()
        v.addLayout(f)
        self.form = f
        t = node.type
        tc = QComboBox()
        for k in STEP_ORDER:
            tc.addItem(step_name(k), k)
            tc.setItemData(tc.count() - 1, k, Qt.ToolTipRole)        # 내부 이름은 툴팁에만
        if tc.findData(t) < 0:
            tc.addItem(t, t)
        tc.setCurrentIndex(tc.findData(t))
        tc.currentIndexChanged.connect(lambda _=None: self._type_combo(tc))
        f.addRow(tr("종류"), tc)
        if t in HELP:
            h = QLabel(tr(HELP[t]))
            h.setWordWrap(True)
            h.setStyleSheet("color:#666")
            f.addRow("", h)
        builder = getattr(self, f"_b_{t}", None)
        if builder:
            builder(f)
        if t != "comment":
            self._common(f)
        else:
            self._advanced(f, with_fg=False)
        v.addStretch(1)
        self._loading = False

    # ------------------------------------------------------------ 도우미
    @property
    def d(self) -> dict:
        return self.node.data

    def _changed(self):
        if not self._loading:
            self.changed.emit()

    def _put(self, key, value, default=_NO):
        """default 와 같고 원래 키가 없었으면 키를 만들지 않는다."""
        if default is not _NO and value == default and key not in self.d:
            return
        self.d[key] = value

    def _opt(self, key, label, default_label, null_label=None, lo=0.0, hi=3600.0, dec=1, step=0.5,
             initial=10.0, integer=False):
        w = OptValue(default_label, null_label, lo, hi, dec, step, initial, integer)
        w.set_value(self.d[key] if key in self.d else ABSENT)

        def upd():
            apply_opt(self.d, key, w.value())
            self._changed()
        w.changed.connect(upd)
        self.form.addRow(label, w)
        return w

    def _line(self, key, label, placeholder=""):
        e = QLineEdit(str(self.d.get(key, "")))
        e.setPlaceholderText(placeholder)

        def upd(text):
            self.d[key] = text
            self._changed()
        e.textChanged.connect(upd)
        self.form.addRow(label, e)
        return e

    def _target(self, key, label, optional=False):
        te = TargetEditor(self.tools)
        te.set_target(self.d.get(key) if isinstance(self.d.get(key), dict) else None)   # 없으면 '정하기 전'
        if optional:
            on = QCheckBox(tr("위치 지정(안 하면 지금 마우스 위치)"))
            on.setChecked(key in self.d)
            te.setVisible(on.isChecked())

            def tog(v):
                te.setVisible(v)
                tg = te.target() if v else None
                if tg is not None:
                    self.d[key] = tg
                else:
                    self.d.pop(key, None)
                self._changed()
            on.toggled.connect(tog)
            self.form.addRow(label, on)
            self.form.addRow("", te)
        else:
            self.form.addRow(label, te)

        def upd():
            if optional and not on.isChecked():
                return
            tg = te.target()
            if tg is None:
                self.d.pop(key, None)
            else:
                self.d[key] = tg
            self._changed()
        te.changed.connect(upd)
        return te

    def _cond(self, key, label):
        ce = CondEditor(self.tools)
        ce.set_cond(self.d.get(key))

        def upd():
            self.d[key] = ce.cond()
            self._changed()
        ce.changed.connect(upd)
        self.form.addRow(label, ce)
        return ce

    def _button(self):
        c = QComboBox()
        for k, lab in (("left", tr("왼쪽")), ("right", tr("오른쪽")), ("middle", tr("가운데"))):
            c.addItem(lab, k)
        c.setCurrentIndex(max(0, c.findData(self.d.get("button", "left"))))

        def upd(_=None):
            self._put("button", c.currentData(), "left")
            self._changed()
        c.currentIndexChanged.connect(upd)
        self.form.addRow(tr("버튼"), c)

    def _timeout(self, default_label=None):
        default_label = default_label or tr("기본값(30초)")
        return self._opt("timeout", tr("제한 시간(초)"), default_label, tr("무한"), 0, 3600, 1, 1, 10)

    # ================================================================ 종류별
    def _b_click(self, f):
        self._target("target", tr("대상"))
        self._button()
        c = QComboBox()
        c.addItem(tr("한 번"), 1)
        c.addItem(tr("두 번(더블클릭)"), 2)
        c.setCurrentIndex(1 if self.d.get("count") == 2 else 0)

        def upd(_=None):
            self._put("count", c.currentData(), 1)
            self._changed()
        c.currentIndexChanged.connect(upd)
        f.addRow(tr("클릭 수"), c)
        self._timeout()
        # 클릭 뒤 확인
        on = QCheckBox(tr("클릭 뒤 결과 확인(안 되면 다시 클릭)"))
        v = self.d.get("verify") if isinstance(self.d.get("verify"), dict) else None
        on.setChecked(v is not None)
        box = QWidget()
        bf = QFormLayout(box)
        bf.setContentsMargins(0, 0, 0, 0)
        ce = CondEditor(self.tools)
        ce.set_cond((v or {}).get("cond", {"gone": {"image": ""}}))
        vt = dspin(0, 600, float((v or {}).get("timeout", 2.0)), 1, 0.5)
        vr = spin(0, 20, int((v or {}).get("retries", 2)), 60)
        bf.addRow(tr("확인할 조건"), ce)
        bf.addRow(tr("기다릴 시간(초)"), vt)
        bf.addRow(tr("다시 클릭 횟수"), vr)
        box.setVisible(on.isChecked())          # 끈 동안은 접어 둔다(겹쳐 보이지 않게)

        def upd_v(*_):
            if on.isChecked():
                cur = copy.deepcopy(self.d.get("verify")) if isinstance(self.d.get("verify"), dict) else {}
                cur["cond"] = ce.cond()
                cur["timeout"] = round(float(vt.value()), 2)
                cur["retries"] = int(vr.value())
                self.d["verify"] = cur
            else:
                self.d.pop("verify", None)
            box.setVisible(on.isChecked())
            self._changed()
        on.toggled.connect(upd_v)
        ce.changed.connect(upd_v)
        vt.valueChanged.connect(upd_v)
        vr.valueChanged.connect(upd_v)
        f.addRow(on)
        f.addRow(box)

    def _b_move(self, f):
        self._target("target", tr("대상"))
        self._timeout()

    def _b_menu(self, f):
        self._line("path", tr("메뉴 경로"), tr("예: 서식 > 글꼴  (메뉴 글자 그대로, > 로 나눔)"))

    def _b_scroll(self, f):
        self._target("target", tr("위치"), optional=True)
        a = spin(-100, 100, int(self.d.get("amount", -3)), 70)

        def upd(_=None):
            self.d["amount"] = int(a.value())
            self._changed()
        a.valueChanged.connect(upd)
        f.addRow(tr("칸 수(+ 위, - 아래)"), a)
        h = QCheckBox(tr("가로로(+ 오른쪽, - 왼쪽)"))
        h.setChecked(bool(self.d.get("horizontal")))

        def upd_h(on):
            if on:
                self.d["horizontal"] = True
            else:
                self.d.pop("horizontal", None)
            self._changed()
        h.toggled.connect(upd_h)
        f.addRow(h)
        self._timeout()

    def _b_drag(self, f):
        self._target("from", tr("시작"))
        self._target("to", tr("끝"))
        self._opt("duration_ms", tr("끄는 시간(ms)"), tr("기본값(300)"), None, 0, 20000, 0, 50, 300, integer=True)
        self._button()

    def _b_mouse_down(self, f):
        self._target("target", tr("위치"), optional=True)
        self._button()

    _b_mouse_up = _b_mouse_down

    def _b_key(self, f):
        self._line("keys", tr("키"), tr("예: enter, ctrl+c, alt+tab, f5, num1, space"))
        self._opt("count", tr("누르는 횟수"), tr("1번"), None, 1, 1000, 0, 1, 1, integer=True)

    def _b_type_text(self, f):
        e = QPlainTextEdit(str(self.d.get("text", "")))
        e.setMaximumHeight(90)

        def upd():
            self.d["text"] = e.toPlainText()
            self._changed()
        e.textChanged.connect(upd)
        f.addRow(tr("글자(한글 가능)"), e)

    def _b_wait(self, f):
        self._cond("until", tr("기다릴 조건"))
        self._timeout()

    def _b_delay(self, f):
        s = dspin(0, 86400, float(self.d.get("seconds", 1.0)), 2, 0.1)

        def upd(_=None):
            v = round(float(s.value()), 3)
            self.d["seconds"] = int(v) if v == int(v) and isinstance(self.d.get("seconds"), int) else v
            self._changed()
        s.valueChanged.connect(upd)
        f.addRow(tr("쉬는 시간(초)"), s)

    def _b_remember(self, f):
        self._line("var", tr("변수 이름"))
        c = QComboBox()
        c.addItem(tr("현재 마우스 위치"), "mouse")
        c.addItem(tr("대상의 위치"), "target")
        is_mouse = self.d.get("what", "mouse") == "mouse"
        c.setCurrentIndex(0 if is_mouse else 1)
        te = TargetEditor(self.tools)
        te.set_target(self.d.get("what") if isinstance(self.d.get("what"), dict) else {"image": ""})
        te.setVisible(not is_mouse)

        def upd(*_):
            m = c.currentData() == "mouse"
            te.setVisible(not m)
            self.d["what"] = "mouse" if m else te.target()
            self._changed()
        c.currentIndexChanged.connect(upd)
        te.changed.connect(upd)
        f.addRow(tr("무엇을"), c)
        f.addRow("", te)
        self._timeout()

    def _b_if(self, f):
        self._cond("cond", tr("조건"))
        self._opt("within", tr("기다려 볼 시간(초)"), tr("바로 판단"), None, 0, 600, 1, 0.5, 3)

    def _b_repeat(self, f):
        c = QComboBox()
        for k, lab in (("times", tr("정해진 횟수")), ("forever", tr("계속(정지할 때까지)")),
                       ("until", tr("조건이 맞을 때까지(회차 끝에 확인)")), ("while", tr("조건이 맞는 동안(회차 시작 전 확인)"))):
            c.addItem(lab, k)
        mode = next((k for k in ("times", "forever", "until", "while") if k in self.d), "times")
        c.setCurrentIndex(c.findData(mode))
        times = spin(0, 1000000, int(self.d.get("times", 2)), 90)
        ce = CondEditor(self.tools)
        ce.set_cond(self.d.get(mode) if mode in ("until", "while") else {"exists": {"image": ""}})
        f.addRow(tr("반복 방식"), c)
        f.addRow(tr("횟수"), times)
        f.addRow(tr("조건"), ce)

        def show():
            m = c.currentData()
            times.setEnabled(m == "times")
            ce.setVisible(m in ("until", "while"))

        def upd(*_):
            m = c.currentData()
            for k in ("times", "forever", "until", "while"):
                if k != m:
                    self.d.pop(k, None)
            if m == "times":
                self.d["times"] = int(times.value())
            elif m == "forever":
                self.d["forever"] = True
            else:
                self.d[m] = ce.cond()
            show()
            self._changed()
        c.currentIndexChanged.connect(upd)
        times.valueChanged.connect(upd)
        ce.changed.connect(upd)
        show()
        self._opt("max_times", tr("최대 반복 수"), tr("제한 없음"), None, 1, 1000000, 0, 1, 30, integer=True)
        self._opt("max_seconds", tr("최대 시간(초)"), tr("제한 없음"), None, 1, 864000, 0, 10, 600)

    def _b_group(self, f):
        pass

    def _b_launch(self, f):
        self._line("target", tr("실행할 것"), tr("steam://rungameid/... 또는 프로그램 경로"))

    def _b_snapshot(self, f):
        self._line("name", tr("파일 이름"), tr("화면"))

    def _b_web(self, f):
        from PySide6.QtCore import QTimer
        from gui.v2.describe import WEB_ACTIONS
        need = {"goto": ["url"], "click": ["selector"], "fill": ["selector", "text"], "select": ["selector", "text"],
                "press": ["text", "selector?"], "wait": ["selector", "state"], "read": ["selector", "var"],
                "url": ["var"], "screenshot": ["name"], "table": ["selector?", "var"],
                "download": ["selector?", "url?", "path", "overwrite"]}
        ac = QComboBox()
        for k, lab in WEB_ACTIONS.items():
            ac.addItem(tr(lab), k)
            ac.setItemData(ac.count() - 1, k, Qt.ToolTipRole)
        cur = self.d.get("action", "goto")
        if ac.findData(cur) < 0:
            ac.addItem(str(cur), cur)
        ac.setCurrentIndex(ac.findData(cur))

        def upd_action(_=None):
            a = ac.currentData()
            if a == self.d.get("action"):
                return
            self.d["action"] = a
            keep = {x.rstrip("?") for x in need.get(a, [])}
            for k in ("url", "selector", "text", "var", "state", "name", "path", "overwrite"):
                if k not in keep:
                    self.d.pop(k, None)
            if a == "goto" and "url" not in self.d:
                self.d["url"] = "https://"
            if a == "press" and "text" not in self.d:
                self.d["text"] = "Enter"
            self._changed()
            QTimer.singleShot(0, lambda: self.set_node(self.node))     # 동작에 맞는 칸으로 다시 그림
        ac.currentIndexChanged.connect(upd_action)
        f.addRow(tr("동작"), ac)
        fields = need.get(cur, [])
        if "url" in fields:
            self._line("url", tr("주소"), "https://...")
        if "url?" in fields:
            ue = self._str_field("url", tr("링크 대신 주소를 바로(선택)"))
            f.addRow(tr("주소"), ue)
        if "selector" in fields or "selector?" in fields:
            e = QLineEdit(str(self.d.get("selector", "")))
            hint = {"table": tr(" (비우면 첫 표)"), "download": tr(" (받을 링크)")}.get(cur, tr(" (비우면 지금 칸에)"))
            e.setPlaceholderText(tr("text=로그인 / #아이디 / input[name=\"q\"]") + (hint if "selector?" in fields else ""))

            def upd_sel(text):
                if text.strip() or "selector" in fields:
                    self.d["selector"] = text.strip()
                else:
                    self.d.pop("selector", None)
                self._changed()
            e.textChanged.connect(upd_sel)
            f.addRow(tr("요소(선택자)"), e)
        if "text" in fields:
            lab = {"fill": tr("넣을 글자"), "select": tr("고를 값·글자"), "press": tr("키(Enter, Tab, Control+A)")}.get(cur, tr("글자"))
            row = QHBoxLayout()
            use_var = QCheckBox(tr("변수에서"))
            v0 = self.d.get("text", "")
            use_var.setChecked(isinstance(v0, dict))
            te = QLineEdit(v0["var"] if isinstance(v0, dict) else str(v0))

            def upd_text(*_):
                t = te.text()
                self.d["text"] = {"var": t.strip()} if use_var.isChecked() else t
                self._changed()
            te.textChanged.connect(upd_text)
            use_var.toggled.connect(upd_text)
            if cur == "press":
                use_var.setVisible(False)
            row.addWidget(te, 1)
            row.addWidget(use_var)
            f.addRow(lab, row)
        if "var" in fields:
            self._line("var", tr("넣을 변수 이름"), tr("제목"))
        if "state" in fields:
            sc = QComboBox()
            for k, lab in (("visible", tr("보이게")), ("attached", tr("페이지에 생기면(안 보여도)")), ("hidden", tr("안 보이게")),
                           ("detached", tr("페이지에서 없어지면"))):
                sc.addItem(lab, k)
            sc.setCurrentIndex(max(0, sc.findData(self.d.get("state", "visible"))))

            def upd_state(_=None):
                k = sc.currentData()
                if k == "visible":
                    self.d.pop("state", None)
                else:
                    self.d["state"] = k
                self._changed()
            sc.currentIndexChanged.connect(upd_state)
            f.addRow(tr("기다릴 상태"), sc)
        if "name" in fields:
            self._line("name", tr("사진 이름"), tr("페이지"))
        if "path" in fields:
            f.addRow(tr("저장할 곳"), self._str_field("path", tr("폴더 또는 파일. 비우면 자료 폴더의 downloads")))
        if "overwrite" in fields:
            ow = QComboBox()
            for k, lab in OVERWRITE_NAMES.items():
                ow.addItem(tr(lab), k)
            ow.setCurrentIndex(max(0, ow.findData(self.d.get("overwrite", "number"))))

            def upd_ow(_=None):
                if ow.currentData() == "number":
                    self.d.pop("overwrite", None)
                else:
                    self.d["overwrite"] = ow.currentData()
                self._changed()
            ow.currentIndexChanged.connect(upd_ow)
            f.addRow(tr("같은 이름이 있으면"), ow)
        if cur == "table":
            h = QLabel(tr("줄마다 {변수.제목}·{변수.1}(첫 칸)·{변수.행} 으로 씁니다. '목록마다'로 돌거나 엑셀 쓰기·CSV 쓰기에 그대로 넣으세요."))
            h.setWordWrap(True)
            h.setStyleSheet("color:#666")
            f.addRow("", h)
        self._opt("timeout", tr("제한 시간(초)"), tr("기본값(5초)"), None, 0, 600, 1, 1, 10.0)
        e = QLineEdit(str(self.d.get("page", "")))
        e.setPlaceholderText(tr("p1 (보통 비워 둠)"))

        def upd_page(text):
            if text.strip():
                self.d["page"] = text.strip()
            else:
                self.d.pop("page", None)
            self._changed()
        e.textChanged.connect(upd_page)
        f.addRow(tr("탭 이름"), e)

    def _office_form(self, f, kind):
        from PySide6.QtCore import QTimer
        from engine.office import ACTIONS, REQUIRED
        fields_of = {
            ("excel", "open"): ["path", "visible"], ("excel", "read"): ["sheet", "cell", "var"],
            ("excel", "write"): ["sheet", "cell", "value"], ("excel", "last_row"): ["sheet", "cell", "var"],
            ("excel", "run_macro"): ["name", "var"],
            ("word", "open"): ["path", "visible"], ("word", "replace"): ["find", "text"],
            ("word", "fill_bookmark"): ["name", "text"], ("word", "read"): ["name", "var"], ("word", "save_as"): ["path"],
            ("hwp", "open"): ["path", "visible"], ("hwp", "fill_field"): ["name", "text"],
            ("hwp", "read_field"): ["name", "var"], ("hwp", "replace"): ["find", "text"], ("hwp", "save_as"): ["path"],
            ("excel", "print"): ["sheet", "to_file", "printer", "copies"],
            ("excel", "new"): ["sheet", "visible"], ("excel", "save_as"): ["path", "format", "overwrite"],
            ("word", "print"): ["to_file", "printer", "copies"], ("hwp", "print"): ["to_file", "printer", "copies"],
        }
        labels = {"path": (tr("파일 경로"), tr("C:\\문서\\고객.xlsx  (저장할 땐 .pdf 로 끝나면 PDF)")),
                  "sheet": (tr("시트"), tr("비우면 지금 시트 / 시트 이름 / 1")), "cell": (tr("칸"), tr("A1, B{행}, A1:C10 / 마지막 행은 열 글자(A)")),
                  "value": (tr("넣을 값"), tr("글자·숫자. {변수} 가능")), "var": (tr("넣을 변수 이름"), tr("결과")),
                  "name": ({"excel": tr("엑셀 매크로 이름"), "word": tr("책갈피 이름(비우면 문서 전체)"), "hwp": tr("누름틀 이름")}[kind], ""),
                  "find": (tr("찾을 글자"), tr("[날짜]")), "text": (tr("바꿀·넣을 글자"), tr("{변수} 가능")),
                  "to_file": (tr("종이 대신 PDF 파일로"), tr("비우면 프린터로 인쇄. 예: 출력\\{오늘}.pdf")),
                  "printer": (tr("프린터"), tr("비우면 기본 프린터")), "copies": (tr("몇 부"), "1"),
                  "format": (tr("파일 형식"), tr("xlsx / csv / pdf (비우면 이름 끝을 따름)")),
                  "overwrite": (tr("같은 이름이 있으면"), tr("fail(멈춤) / number(번호) / skip / replace"))}
        ac = QComboBox()
        for a in ACTIONS[kind]:
            ac.addItem(office_action_name(a), a)
            ac.setItemData(ac.count() - 1, a, Qt.ToolTipRole)
        cur = self.d.get("action", "open")
        if ac.findData(cur) < 0:
            ac.addItem(str(cur), cur)
        ac.setCurrentIndex(ac.findData(cur))

        def upd_action(_=None):
            a = ac.currentData()
            if a == self.d.get("action"):
                return
            self.d["action"] = a
            keep = set(fields_of.get((kind, a), []))
            for k in ("path", "sheet", "cell", "value", "var", "name", "find", "text", "visible", "pdf", "to_file",
                      "printer", "copies", "format", "overwrite"):
                if k not in keep:
                    self.d.pop(k, None)
            for k in REQUIRED.get((kind, a), []):
                self.d.setdefault(k, "")
            self._changed()
            QTimer.singleShot(0, lambda: self.set_node(self.node))
        ac.currentIndexChanged.connect(upd_action)
        f.addRow(tr("동작"), ac)
        for k in fields_of.get((kind, cur), []):
            if k == "visible":
                cb = QCheckBox(tr("프로그램 창 보이기(시험할 때 켜면 보면서 확인 가능)"))
                cb.setChecked(bool(self.d.get("visible")))

                def upd_vis(v):
                    if v:
                        self.d["visible"] = True
                    else:
                        self.d.pop("visible", None)
                    self._changed()
                cb.toggled.connect(upd_vis)
                f.addRow("", cb)
                continue
            lab, ph = labels[k]
            if k == "value":
                self._literal("value", lab)
                continue
            e = QLineEdit(str(self.d.get(k, "")))
            e.setPlaceholderText(ph)
            req = k in REQUIRED.get((kind, cur), [])

            def upd(text, k=k, req=req):
                if k == "copies":
                    if text.strip().isdigit() and int(text) > 1:
                        self.d[k] = int(text)
                    else:
                        self.d.pop(k, None)
                    self._changed()
                    return
                if text.strip() or req:
                    self.d[k] = text if k in ("text", "find") else text.strip()
                else:
                    self.d.pop(k, None)
                self._changed()
            e.textChanged.connect(upd)
            f.addRow(lab, e)

    def _b_excel(self, f):
        self._office_form(f, "excel")

    def _b_word(self, f):
        self._office_form(f, "word")

    def _b_hwp(self, f):
        self._office_form(f, "hwp")

    def _b_for_each(self, f):
        self._line("var", tr("변수 이름"), tr("카드"))
        self._target("target", tr("찾을 그림"))

    def _sub_field(self, src: str, key: str, placeholder: str = "", is_int: bool = False):
        """목록마다의 rows/files/range 안쪽 칸."""
        cur = self.d.get(src) if isinstance(self.d.get(src), dict) else {}
        e = QLineEdit("" if cur.get(key) is None else str(cur.get(key)))
        e.setPlaceholderText(placeholder)

        def upd(text):
            d = self.d.get(src) if isinstance(self.d.get(src), dict) else {}
            text = text.strip()
            if text == "":
                d.pop(key, None)
            else:
                d[key] = int(text) if is_int and text.lstrip("-").isdigit() else text
            self.d[src] = d
            self._changed()
        e.textChanged.connect(upd)
        return e

    def _b_each(self, f):
        self._line("var", tr("하나씩 넣을 변수 이름"), tr("항목"))
        sc = QComboBox()
        for k, lab in EACH_SOURCES.items():
            sc.addItem(tr(lab), k)
        cur = next((k for k in EACH_SOURCES if k in self.d), "list")
        sc.setCurrentIndex(sc.findData(cur))
        f.addRow(tr("무엇을 돌까"), sc)
        lst = QLineEdit(self.d.get("list") if isinstance(self.d.get("list"), str) else "")
        lst.setPlaceholderText(tr("목록이 든 변수 이름. 예: 파일들"))

        def upd_list(text):
            if sc.currentData() == "list":
                self.d["list"] = text.strip()
                self._changed()
        lst.textChanged.connect(upd_list)
        lines = QLineEdit(self.d.get("lines") if isinstance(self.d.get("lines"), str) else "")
        lines.setPlaceholderText(tr("글이 든 변수 이름. 예: 복사한글"))

        def upd_lines(text):
            if sc.currentData() == "lines":
                self.d["lines"] = text.strip()
                self._changed()
        lines.textChanged.connect(upd_lines)
        sub_ = QCheckBox(tr("아래 폴더까지"))
        sub_.setChecked(bool((self.d.get("files") or {}).get("sub")) if isinstance(self.d.get("files"), dict) else False)

        def upd_sub(on):
            d = self.d.get("files") if isinstance(self.d.get("files"), dict) else {}
            if on:
                d["sub"] = True
            else:
                d.pop("sub", None)
            self.d["files"] = d
            self._changed()
        sub_.toggled.connect(upd_sub)
        show = self._rows(f, [
            ("list", tr("목록 변수"), lst, ["list"]),
            ("rows.sheet", tr("시트"), self._sub_field("rows", "sheet", tr("비우면 지금 시트")), ["rows"]),
            ("rows.path", tr("엑셀 파일"), self._sub_field("rows", "path", tr("비우면 이미 연 파일")), ["rows"]),
            ("rows.header", tr("제목 줄"), self._sub_field("rows", "header", tr("기본 1 (없으면 0)"), True), ["rows"]),
            ("rows.from", tr("시작 줄"), self._sub_field("rows", "from", tr("기본: 제목 다음 줄"), True), ["rows"]),
            ("rows.to", tr("끝 줄"), self._sub_field("rows", "to", tr("비우면 마지막 줄까지"), True), ["rows"]),
            ("rows.group_by", tr("한 건이 여러 줄이면"), self._sub_field("rows", "group_by", tr("새 건이 시작되는 칸(예: A). 다음 줄은 {항목.줄2.E}")), ["rows"]),
            ("rows.group", tr("또는 몇 줄씩"), self._sub_field("rows", "group", tr("예: 2"), True), ["rows"]),
            ("files.path", tr("폴더"), self._sub_field("files", "path", tr("예: C:\\자료\\받은편지")), ["files"]),
            ("files.pattern", tr("이름 모양"), self._sub_field("files", "pattern", tr("예: *.pdf  (비우면 전부)")), ["files"]),
            ("files.sub", "", sub_, ["files"]),
            ("lines", tr("글 변수"), lines, ["lines"]),
            ("range.from", tr("부터"), self._sub_field("range", "from", tr("기본 1"), True), ["range"]),
            ("range.to", tr("까지"), self._sub_field("range", "to", tr("예: 10 또는 {끝}"), True), ["range"]),
        ], sc.currentData)
        hint = QLabel(tr("엑셀 표의 줄은 {항목.이름}·{항목.A}·{항목.행} 처럼 칸 이름으로 씁니다. 파일은 {항목} 이 경로예요."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666")
        f.addRow("", hint)
        self._line("index_var", tr("몇 번째인지 넣을 변수(선택)"), tr("예: 번호"))

        def upd_src(_=None):
            new = sc.currentData()
            for k in EACH_SOURCES:
                if k != new:
                    self.d.pop(k, None)
            if new == "list":
                self.d["list"] = lst.text().strip()
            elif new == "lines":
                self.d["lines"] = lines.text().strip()
            elif new == "range":
                self.d.setdefault("range", {"from": 1, "to": 10})
            else:
                self.d.setdefault(new, {} if new == "rows" else {"path": ""})
            show()
            self._changed()
        sc.currentIndexChanged.connect(upd_src)
        show()

    def _b_ask(self, f):
        kc = QComboBox()
        for k, lab in ASK_KINDS.items():
            kc.addItem(tr(lab), k)
        kc.setCurrentIndex(max(0, kc.findData(self.d.get("kind", "input"))))
        f.addRow(tr("무엇을 물을까"), kc)
        msg = self._str_field("message", tr("예: 몇 월 자료를 처리할까요?  ({변수} 가능)"))
        opts = QLineEdit(", ".join(self.d["options"]) if isinstance(self.d.get("options"), list)
                         else str(self.d.get("options", "")))
        opts.setPlaceholderText(tr("쉼표로 나눈 글, 또는 목록 변수 이름"))

        def upd_opts(text):
            text = text.strip()
            if "," in text:
                self.d["options"] = [x.strip() for x in text.split(",") if x.strip()]
            elif text:
                self.d["options"] = text
            else:
                self.d.pop("options", None)
            self._changed()
        opts.textChanged.connect(upd_opts)
        to = OptValue(tr("기다림(답할 때까지)"), None, 1, 86400, 0, 10, 60, integer=True)
        to.set_value(self.d["timeout"] if "timeout" in self.d else ABSENT)

        def upd_to():
            apply_opt(self.d, "timeout", to.value())
            self._changed()
        to.changed.connect(upd_to)
        show = self._rows(f, [
            ("message", tr("물을 말"), msg, list(ASK_KINDS)),
            ("options", tr("고를 것"), opts, ["choose"]),
            ("var", tr("답을 넣을 변수"), self._str_field("var", tr("예: 답")), list(ASK_KINDS)),
            ("default", tr("기본값"), self._str_field("default", tr("답이 없을 때·AI가 돌릴 때 쓸 값")), list(ASK_KINDS)),
            ("timeout", tr("기다릴 시간(초)"), to, list(ASK_KINDS)),
        ], kc.currentData)

        def upd_kind(_=None):
            self._put("kind", kc.currentData(), "input")
            show()
            self._changed()
        kc.currentIndexChanged.connect(upd_kind)
        show()

    def _b_notify(self, f):
        self._line("title", tr("제목"), tr("비우면 매크로 이름"))
        msg = QPlainTextEdit(str(self.d.get("message", "")))
        msg.setMaximumHeight(70)
        msg.setPlaceholderText(tr("예: {건수}건 처리 끝  ({변수} 가능)"))

        def upd_msg():
            self.d["message"] = msg.toPlainText()
            self._changed()
        msg.textChanged.connect(upd_msg)
        f.addRow(tr("내용"), msg)
        ch = self.d.get("channels") or ["toast"]
        ch = [ch] if isinstance(ch, str) else list(ch)
        boxes = {}
        row = QHBoxLayout()
        for k, lab in NOTIFY_CHANNELS.items():
            b = QCheckBox(tr(lab))
            b.setChecked(k in ch)
            boxes[k] = b
            row.addWidget(b)
        row.addStretch(1)
        f.addRow(tr("보낼 곳"), row)
        url = self._str_field("url", tr("메신저 웹훅 주소(비우면 settings/notify.json 의 주소)"))
        url_lab = QLabel(tr("웹훅 주소"))
        f.addRow(url_lab, url)

        def upd_ch(_=None):
            sel = [k for k, b in boxes.items() if b.isChecked()] or ["toast"]
            if sel == ["toast"]:
                self.d.pop("channels", None)
            else:
                self.d["channels"] = sel
            url.setVisible(boxes["webhook"].isChecked())
            url_lab.setVisible(boxes["webhook"].isChecked())
            self._changed()
        for b in boxes.values():
            b.toggled.connect(upd_ch)
        url.setVisible(boxes["webhook"].isChecked())
        url_lab.setVisible(boxes["webhook"].isChecked())
        h = QLabel(tr("보낸 알림은 항상 logs/notify/notify.jsonl 에도 남습니다. 못 보내도 매크로는 멈추지 않아요."))
        h.setWordWrap(True)
        h.setStyleSheet("color:#666")
        f.addRow("", h)

    def _b_list(self, f):
        self._line("var", tr("목록 변수 이름"), tr("목록"))
        ac = QComboBox()
        for k, lab in LIST_ACTIONS.items():
            ac.addItem(tr(lab), k)
        ac.setCurrentIndex(max(0, ac.findData(self.d.get("action", "add"))))
        f.addRow(tr("할 일"), ac)
        val = QPlainTextEdit(json.dumps(self.d["value"], ensure_ascii=False) if isinstance(self.d.get("value"), dict)
                             else str(self.d.get("value", "")))
        val.setMaximumHeight(70)
        val.setPlaceholderText(tr('글자 하나: {이름}  ·  줄 하나: {"날짜": "{날짜}", "금액": "{금액}", "비고": ""}'))

        def upd_val():
            t = val.toPlainText().strip()
            if t.startswith("{") and t.endswith("}") and ":" in t:
                try:
                    self.d["value"] = json.loads(t)
                except ValueError:
                    self.d["value"] = t
            else:
                self.d["value"] = t
            self._changed()
        val.textChanged.connect(upd_val)
        uq = QCheckBox(tr("이미 있으면 더하지 않기"))
        uq.setChecked(bool(self.d.get("unique")))

        def upd_uq(on):
            if on:
                self.d["unique"] = True
            else:
                self.d.pop("unique", None)
            self._changed()
        uq.toggled.connect(upd_uq)
        by = QLineEdit(self.d["by"] if isinstance(self.d.get("by"), str) else
                       ", ".join(k.get("key", "") for k in (self.d.get("by") or [])))
        by.setPlaceholderText(tr("정렬할 칸, 여러 개는 쉼표. 예: 날짜, 시간 (비우면 값 자체)"))

        def upd_by(text):
            if text.strip():
                self.d["by"] = text.strip()
            else:
                self.d.pop("by", None)
            self._changed()
        by.textChanged.connect(upd_by)
        desc = QCheckBox(tr("큰 것부터(내림)"))
        desc.setChecked(self.d.get("order") == "desc")

        def upd_desc(on):
            if on:
                self.d["order"] = "desc"
            else:
                self.d.pop("order", None)
            self._changed()
        desc.toggled.connect(upd_desc)
        show = self._rows(f, [
            ("value", tr("더할 것"), val, ["add"]),
            ("unique", "", uq, ["add"]),
            ("by", tr("기준 칸"), by, ["sort"]),
            ("order", "", desc, ["sort"]),
            ("to_var", tr("결과를 넣을 변수(선택)"), self._str_field("to_var", tr("비우면 같은 변수")), ["sort", "unique", "count"]),
        ], ac.currentData)

        def upd_action(_=None):
            self.d["action"] = ac.currentData()
            show()
            self._changed()
        ac.currentIndexChanged.connect(upd_action)
        show()

    def _b_break(self, f):
        pass

    _b_continue = _b_break

    def _b_call(self, f):
        from gui.v3.macro_picker import MacroPicker, PickerSource
        src = self.picker_source or (lambda: PickerSource.from_names(self.macro_names()))
        c = MacroPicker(src, current=str(self.d.get("macro", "")), roots_only=False, editable=True,
                        title=tr("부를 매크로 고르기"))

        def upd(text):
            self.d["macro"] = text.strip()
            self._changed()
        c.changed.connect(upd)
        f.addRow(tr("부를 매크로"), c)
        e = QLineEdit(str(self.d.get("result_var", "")))
        e.setPlaceholderText(tr("비우면 결과를 안 받음"))

        def upd_r(text):
            if text.strip():
                self.d["result_var"] = text.strip()
            else:
                self.d.pop("result_var", None)
            self._changed()
        e.textChanged.connect(upd_r)
        f.addRow(tr("결과를 넣을 변수"), e)

    def _literal(self, key, label, optional=False):
        le = LiteralEdit()
        le.set_literal(self.d.get(key, ""))
        on = None
        if optional:
            on = QCheckBox(tr("값 돌려주기"))
            on.setChecked(key in self.d)
            le.setEnabled(on.isChecked())
            f2 = QHBoxLayout()
            f2.addWidget(on)
            f2.addWidget(le)
            self.form.addRow(label, f2)
        else:
            self.form.addRow(label, le)

        def upd(*_):
            if on is not None:
                le.setEnabled(on.isChecked())
                if not on.isChecked():
                    self.d.pop(key, None)
                    self._changed()
                    return
            self.d[key] = le.literal()
            self._changed()
        le.changed.connect(upd)
        if on is not None:
            on.toggled.connect(upd)

    def _b_set_result(self, f):
        self._literal("value", tr("결과값"))

    def _b_set(self, f):
        self._line("var", tr("변수 이름"))
        c = QComboBox()
        c.addItem(tr("값 넣기"), "value")
        c.addItem(tr("숫자 더하기"), "add")
        mode = "add" if "add" in self.d else "value"
        c.setCurrentIndex(c.findData(mode))
        le = LiteralEdit()
        le.set_literal(self.d.get(mode, 0 if mode == "add" else ""))
        f.addRow(tr("방식"), c)
        f.addRow(tr("값"), le)

        def upd(*_):
            m = c.currentData()
            self.d.pop("add" if m == "value" else "value", None)
            v = le.literal()
            if m == "add" and not isinstance(v, (int, float)):
                v = 1
            self.d[m] = v
            self._changed()
        c.currentIndexChanged.connect(upd)
        le.changed.connect(upd)

    # ---------------------------------------------------------------- 사무: 글자·날짜·계산
    def _rows(self, f, specs, current: Callable[[], str]):
        """동작마다 필요한 칸만 보이게. specs: [(key, 라벨, 위젯, [동작들])]."""
        rows = []
        for key, label, w, acts in specs:
            lab = QLabel(label)
            f.addRow(lab, w)
            rows.append((lab, w, acts))

        def show():
            a = current()
            for lab, w, acts in rows:
                on = a in acts
                lab.setVisible(on)
                w.setVisible(on)
        return show

    def _str_field(self, key, placeholder="", default=""):
        e = QLineEdit(str(self.d.get(key, default)))
        e.setPlaceholderText(placeholder)

        def upd(text):
            if text == "" and key not in ("text",):
                self.d.pop(key, None)
            else:
                self.d[key] = text
            self._changed()
        e.textChanged.connect(upd)
        return e

    def _int_field(self, key, lo, hi, default):
        s = spin(lo, hi, int(self.d.get(key, default)), 80)

        def upd(v):
            self.d[key] = int(v)
            self._changed()
        s.valueChanged.connect(upd)
        return s

    def _b_text(self, f):
        self._line("var", tr("넣을 변수 이름"))
        ac = QComboBox()
        for k, lab in TEXT_ACTIONS.items():
            ac.addItem(tr(lab), k)
            ac.setItemData(ac.count() - 1, k, Qt.ToolTipRole)
        ac.setCurrentIndex(max(0, ac.findData(self.d.get("action", "set"))))
        f.addRow(tr("할 일"), ac)
        text = self._str_field("text", tr("예: 재직_{이름}_{오늘}.hwp  ({변수}는 그 값으로 바뀜)"))
        regex = QCheckBox(tr("찾는 글자를 규칙(정규식)으로"))
        regex.setChecked(bool(self.d.get("regex")))

        def upd_rx(on):
            if on:
                self.d["regex"] = True
            else:
                self.d.pop("regex", None)
            self._changed()
        regex.toggled.connect(upd_rx)
        all_ = QCheckBox(tr("맞는 것을 모두 목록으로"))
        all_.setChecked(bool(self.d.get("all")))

        def upd_all(on):
            if on:
                self.d["all"] = True
            else:
                self.d.pop("all", None)
            self._changed()
        all_.toggled.connect(upd_all)
        not_join = [a for a in TEXT_ACTIONS if a != "join"]
        show = self._rows(f, [
            ("text", tr("글자"), text, not_join),
            ("find", tr("찾을 글자"), self._str_field("find", tr("예: . 또는 -")), ["replace"]),
            ("with", tr("바꿀 글자"), self._str_field("with", tr("비우면 지움")), ["replace"]),
            ("regex", "", regex, ["replace"]),
            ("pattern", tr("찾는 규칙"), self._str_field("pattern", tr("예: ([\\d,]+)원  → 괄호 안만 뽑음")), ["extract"]),
            ("all", "", all_, ["extract"]),
            ("sep", tr("나누는 글자"), self._str_field("sep", tr("비우면 빈칸으로 나눔")), ["split", "join"]),
            ("index", tr("몇 번째(1=첫째, -1=마지막)"), self._int_field("index", -999, 999, 1), ["split"]),
            ("start", tr("몇 번째 글자부터(1부터)"), self._int_field("start", -9999, 9999, 1), ["slice"]),
            ("count", tr("몇 글자"), self._int_field("count", 0, 99999, 1), ["slice"]),
            ("width", tr("전체 자릿수"), self._int_field("width", 1, 50, 2), ["pad"]),
            ("list", tr("목록 변수 이름"), self._str_field("list", tr("예: 목록")), ["join"]),
        ], ac.currentData)

        def upd_action(_=None):
            a = ac.currentData()
            if a == "set":
                self.d.pop("action", None)
            else:
                self.d["action"] = a
            if a == "join":
                self.d.pop("text", None)
            else:
                self.d.setdefault("text", text.text())
            show()
            self._changed()
        ac.currentIndexChanged.connect(upd_action)
        show()

    def _b_date(self, f):
        self._line("var", tr("넣을 변수 이름"))
        ac = QComboBox()
        ac.addItem(tr("날짜 글자 만들기"), "format")
        ac.addItem(tr("두 날짜 사이 (to - from)"), "diff")
        ac.setCurrentIndex(max(0, ac.findData(self.d.get("action", "format"))))
        f.addRow(tr("할 일"), ac)
        add = dict(self.d.get("add") or {})
        days = spin(-100000, 100000, int(add.get("days", 0)), 90)
        months = spin(-1200, 1200, int(add.get("months", 0)), 90)

        def upd_add(*_):
            a = {k: v for k, v in (("months", months.value()), ("days", days.value())) if v}
            for k in ("years", "hours", "minutes"):          # 화면에 없는 칸은 그대로 둔다
                if k in (self.d.get("add") or {}):
                    a[k] = self.d["add"][k]
            if a:
                self.d["add"] = a
            else:
                self.d.pop("add", None)
            self._changed()
        days.valueChanged.connect(upd_add)
        months.valueChanged.connect(upd_add)
        unit = QComboBox()
        for k, lab in (("days", tr("날")), ("hours", tr("시간")), ("minutes", tr("분"))):
            unit.addItem(lab, k)
        unit.setCurrentIndex(max(0, unit.findData(self.d.get("unit", "days"))))

        def upd_unit(_=None):
            self._put("unit", unit.currentData(), "days")
            self._changed()
        unit.currentIndexChanged.connect(upd_unit)
        show = self._rows(f, [
            ("from", tr("기준 날짜"), self._str_field("from", tr("비우면 지금. 예: 2026-11-18, {입사일}")), ["format", "diff"]),
            ("add", tr("더할 날 수(- 는 빼기)"), days, ["format", "diff"]),
            ("months", tr("더할 달 수"), months, ["format", "diff"]),
            ("format", tr("모양"), self._str_field("format", tr("예: yyyy-MM-dd, yyyy년 M월 d일 (요일)")), ["format"]),
            ("to", tr("끝 날짜"), self._str_field("to", tr("비우면 지금")), ["diff"]),
            ("unit", tr("단위"), unit, ["diff"]),
        ], ac.currentData)

        def upd_action(_=None):
            self._put("action", ac.currentData(), "format")
            if ac.currentData() == "format" and self.d.get("action") == "format":
                self.d.pop("action", None)
            show()
            self._changed()
        ac.currentIndexChanged.connect(upd_action)
        show()

    def _b_clipboard(self, f):
        ac = QComboBox()
        for k, lab in CLIPBOARD_ACTIONS.items():
            ac.addItem(tr(lab), k)
            ac.setItemData(ac.count() - 1, k, Qt.ToolTipRole)
        ac.setCurrentIndex(max(0, ac.findData(self.d.get("action", "read"))))
        f.addRow(tr("할 일"), ac)
        to = OptValue(tr("기본값(2초)"), None, 0.1, 60, 1, 0.5, 2.0)
        to.set_value(self.d["timeout"] if "timeout" in self.d else ABSENT)

        def upd_to():
            apply_opt(self.d, "timeout", to.value())
            self._changed()
        to.changed.connect(upd_to)
        show = self._rows(f, [
            ("var", tr("넣을 변수 이름"), self._str_field("var", tr("예: 복사한글")), ["copy", "read", "files", "save_image"]),
            ("text", tr("넣을 글"), self._str_field("text", tr("{변수}는 그 값으로 바뀜")), ["write"]),
            ("path", tr("저장할 파일"), self._str_field("path", tr("예: C:\\자료\\그림_{오늘}.png")), ["save_image"]),
            ("timeout", tr("기다릴 시간"), to, ["copy"]),
        ], ac.currentData)

        def upd_action(_=None):
            self.d["action"] = ac.currentData()
            show()
            self._changed()
        ac.currentIndexChanged.connect(upd_action)
        show()

    def _b_file(self, f):
        ac = QComboBox()
        for k, lab in FILE_ACTIONS.items():
            ac.addItem(tr(lab), k)
            ac.setItemData(ac.count() - 1, k, Qt.ToolTipRole)
        ac.setCurrentIndex(max(0, ac.findData(self.d.get("action", "copy"))))
        f.addRow(tr("할 일"), ac)
        ow = QComboBox()
        for k, lab in OVERWRITE_NAMES.items():
            ow.addItem(tr(lab), k)
        ow.setCurrentIndex(max(0, ow.findData(self.d.get("overwrite", "fail"))))

        def upd_ow(_=None):
            self._put("overwrite", ow.currentData(), "fail")
            if ow.currentData() == "fail" and self.d.get("overwrite") == "fail":
                self.d.pop("overwrite", None)
            self._changed()
        ow.currentIndexChanged.connect(upd_ow)
        sub_ = QCheckBox(tr("아래 폴더까지"))
        sub_.setChecked(bool(self.d.get("sub")))
        app = QCheckBox(tr("끝에 이어 쓰기"))
        app.setChecked(bool(self.d.get("append")))

        def flag(key, box):
            def upd(on):
                if on:
                    self.d[key] = True
                else:
                    self.d.pop(key, None)
                self._changed()
            box.toggled.connect(upd)
        flag("sub", sub_)
        flag("append", app)
        perm = QCheckBox(tr("고급: 영구 삭제(휴지통을 거치지 않음, 되살릴 수 없음)"))
        perm.setChecked(bool(self.d.get("permanent")))
        perm.setStyleSheet("QCheckBox { color: #c62828; }")
        flag("permanent", perm)
        srt = QComboBox()
        for k, lab in (("name", tr("이름순")), ("modified", tr("오래된 것부터")), ("newest", tr("새것부터"))):
            srt.addItem(lab, k)
        srt.setCurrentIndex(max(0, srt.findData(self.d.get("sort", "name"))))

        def upd_srt(_=None):
            self._put("sort", srt.currentData(), "name")
            self._changed()
        srt.currentIndexChanged.connect(upd_srt)
        txt = QPlainTextEdit(str(self.d.get("text", "")))
        txt.setMaximumHeight(80)

        def upd_txt():
            self.d["text"] = txt.toPlainText()
            self._changed()
        txt.textChanged.connect(upd_txt)
        moving = ["copy", "move", "rename", "zip", "unzip", "write_text", "write_csv"]
        data = QLineEdit(self.d["data"] if isinstance(self.d.get("data"), str) else "")
        data.setPlaceholderText(tr("표가 든 변수 이름. 예: 표"))

        def upd_data(text):
            self.d["data"] = text.strip()
            self._changed()
        data.textChanged.connect(upd_data)
        hdr = QCheckBox(tr("첫 줄은 제목"))
        hdr.setChecked(self.d.get("header", True) is not False)

        def upd_hdr(on):
            if on:
                self.d.pop("header", None)
            else:
                self.d["header"] = False
            self._changed()
        hdr.toggled.connect(upd_hdr)
        show = self._rows(f, [
            ("path", tr("파일·폴더"), self._str_field("path", tr("예: C:\\자료\\보고서.xlsx  ·  {파일}")), list(FILE_ACTIONS)),
            ("to", tr("보낼 곳"), self._str_field("to", tr("폴더면 그 안에 같은 이름으로. 예: 보관\\{달}\\")),
             ["copy", "move", "zip", "unzip"]),
            ("name", tr("새 이름"), self._str_field("name", tr("예: {날짜}_거래처.pdf")), ["rename"]),
            ("pattern", tr("이름 모양"), self._str_field("pattern", tr("예: *.pdf;*.xlsx  (비우면 전부)")), ["list"]),
            ("sub", "", sub_, ["list"]),
            ("sort", tr("순서"), srt, ["list"]),
            ("text", tr("쓸 글"), txt, ["write_text"]),
            ("data", tr("쓸 표"), data, ["write_csv"]),
            ("header", "", hdr, ["read_csv"]),
            ("append", "", app, ["write_text", "write_csv"]),
            ("permanent", "", perm, ["delete"]),
            ("overwrite", tr("같은 이름이 있으면"), ow, moving),
            ("var", tr("결과를 넣을 변수"), self._str_field("var", tr("예: 목록")), list(FILE_ACTIONS)),
        ], ac.currentData)

        def upd_action(_=None):
            self.d["action"] = ac.currentData()
            if ac.currentData() != "delete":
                self.d.pop("permanent", None)
                perm.setChecked(False)
            show()
            self._changed()
        ac.currentIndexChanged.connect(upd_action)
        show()

    def _b_memory(self, f):
        from engine import memory as mm
        names = sorted(mm.load_values())
        c = QComboBox()
        c.setEditable(True)
        c.addItems(names)
        v = self.d.get("value")
        c.setCurrentText(v if isinstance(v, str) else "")
        adv = QLineEdit(json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else "")
        adv.setPlaceholderText(tr('고급: 주소 직접 {"offset": "0x1234", "kind": "int32"}'))

        def upd_name(text):
            if text.strip():
                self.d["value"] = text.strip()
                adv.blockSignals(True)
                adv.setText("")
                adv.blockSignals(False)
            self._changed()

        def upd_adv(text):
            t_ = text.strip()
            if t_.startswith("{"):
                try:
                    self.d["value"] = json.loads(t_)
                except ValueError:
                    return
                c.blockSignals(True)
                c.setCurrentText("")
                c.blockSignals(False)
                self._changed()
        c.currentTextChanged.connect(upd_name)
        adv.textChanged.connect(upd_adv)
        pick = QPushButton(tr("값 찾기…"))
        pick.setToolTip(tr("프로그램에서 값을 찾아 이름을 붙이는 창을 엽니다"))

        def open_finder():
            from gui.v3.memory_finder import MemoryFinder
            MemoryFinder(self.window()).exec()
            cur = c.currentText()
            c.blockSignals(True)
            c.clear()
            c.addItems(sorted(mm.load_values()))
            c.setCurrentText(cur)
            c.blockSignals(False)
        pick.clicked.connect(open_finder)
        ac = QComboBox()
        for k, lab in (("read", tr("값 읽기 → 변수")), ("write", tr("값 바꾸기(혼자 하는 게임용)")),
                       ("freeze", tr("값 고정 켜기(혼자 하는 게임용)")), ("unfreeze", tr("값 고정 끄기"))):
            ac.addItem(lab, k)
        ac.setCurrentIndex(max(0, ac.findData(self.d.get("action", "read"))))
        f.addRow(tr("할 일"), ac)
        rowx = QHBoxLayout()
        rowx.addWidget(c, 1)
        rowx.addWidget(pick)
        f.addRow(tr("값(저장한 이름)"), rowx)
        f.addRow(tr("또는 주소"), adv)
        setv = QLineEdit("" if self.d.get("set") is None else str(self.d.get("set")))
        setv.setPlaceholderText(tr("예: 9999  ·  {변수}"))

        def upd_set(text):
            t_ = text.strip()
            try:
                self.d["set"] = int(t_) if t_.lstrip("-").isdigit() else float(t_)
            except ValueError:
                self.d["set"] = t_
            if not t_:
                self.d.pop("set", None)
            self._changed()
        setv.textChanged.connect(upd_set)
        ivl = QLineEdit("" if self.d.get("interval") is None else str(self.d.get("interval")))
        ivl.setPlaceholderText("0.1")

        def upd_ivl(text):
            try:
                self.d["interval"] = float(text)
            except ValueError:
                self.d.pop("interval", None)
            self._changed()
        ivl.textChanged.connect(upd_ivl)
        show = self._rows(f, [
            ("var", tr("넣을 변수 이름"), self._str_field("var", tr("예: 돈")), ["read"]),
            ("set", tr("넣을 값"), setv, ["write", "freeze"]),
            ("interval", tr("몇 초마다 되돌리기"), ivl, ["freeze"]),
        ], ac.currentData)

        def upd_action(_=None):
            self.d["action"] = ac.currentData()
            if self.d["action"] != "read":
                self.d.pop("var", None)
            show()
            self._changed()
        ac.currentIndexChanged.connect(upd_action)
        show()
        h = QLabel(tr("읽기는 대상 프로그램의 값을 보기만 합니다. 바꾸기·고정은 혼자 하는 게임용이고, 쓴 것은 기록에 남습니다. "
                      "이 단계가 돌 때만 붙고, 매크로가 끝나면 고정도 풀립니다."))
        h.setWordWrap(True)
        h.setStyleSheet("color:#666")
        f.addRow("", h)

    def _b_pdf(self, f):
        ac = QComboBox()
        for k, lab in (("text", tr("글 전체 읽기")), ("extract", tr("규칙으로 값 뽑기")), ("table", tr("표 읽기(줄 목록)"))):
            ac.addItem(lab, k)
        ac.setCurrentIndex(max(0, ac.findData(self.d.get("action", "text"))))
        f.addRow(tr("할 일"), ac)
        show = self._rows(f, [
            ("path", tr("PDF 파일"), self._str_field("path", tr("예: 받은편지\\청구서.pdf  ·  {파일}")), ["text", "extract", "table"]),
            ("pattern", tr("찾는 규칙"), self._str_field("pattern", tr("예: 합계 금액:\\s*([\\d,]+)  → 괄호 안만")), ["extract"]),
            ("index", tr("몇 번째 표"), self._int_field("index", -99, 99, 1), ["table"]),
            ("var", tr("넣을 변수 이름"), self._str_field("var", tr("예: 금액")), ["text", "extract", "table"]),
        ], ac.currentData)
        h = QLabel(tr("프로그램에 든 PDF 부품으로 읽습니다(워드 없어도 됨). 그림으로 스캔한 PDF 는 글자가 없다고 알려 줘요."))
        h.setWordWrap(True)
        h.setStyleSheet("color:#666")
        f.addRow("", h)
        word = QCheckBox(tr("고급: 워드로 열어 읽기(표가 잘 안 읽힐 때)"))
        word.setChecked(self.d.get("via") == "word")

        def upd_word(on):
            if on:
                self.d["via"] = "word"
            else:
                self.d.pop("via", None)
            self._changed()
        word.toggled.connect(upd_word)
        f.addRow("", word)

        def upd_action(_=None):
            self._put("action", ac.currentData(), "text")
            if ac.currentData() == "text" and self.d.get("action") == "text":
                self.d.pop("action", None)
            show()
            self._changed()
        ac.currentIndexChanged.connect(upd_action)
        show()

    def _b_mail(self, f):
        vc = QComboBox()
        for k, lab in MAIL_VIAS.items():
            vc.addItem(tr(lab), k)
        vc.setCurrentIndex(max(0, vc.findData(self.d.get("via", "outlook"))))
        f.addRow(tr("어디로"), vc)
        sc = QComboBox()
        for k, lab in MAIL_SERVICES.items():
            sc.addItem(tr(lab), k)
        sc.setCurrentIndex(max(0, sc.findData(self.d.get("service", "naver"))))
        sc_lab = QLabel(tr("웹메일"))
        f.addRow(sc_lab, sc)
        acc = self._str_field("account", tr("설정 → 메일 계정에서 만든 이름"))
        acc_lab = QLabel(tr("계정 이름"))
        f.addRow(acc_lab, acc)
        ac = QComboBox()
        for k, lab in MAIL_ACTIONS.items():
            ac.addItem(tr(lab), k)
        ac.setCurrentIndex(max(0, ac.findData(self.d.get("action", "find"))))
        f.addRow(tr("할 일"), ac)
        unread = QCheckBox(tr("안 읽은 메일만"))
        unread.setChecked(bool(self.d.get("unread")))
        has_att = QCheckBox(tr("첨부가 있는 메일만"))
        has_att.setChecked(bool(self.d.get("has_attachment")))
        now = QCheckBox(tr("바로 보내기(끄면 임시 보관함에 저장만)"))
        now.setChecked(bool(self.d.get("send_now")))
        now.setStyleSheet("QCheckBox { color: #c62828; }")

        def flag(key, box):
            def u(on):
                if on:
                    self.d[key] = True
                else:
                    self.d.pop(key, None)
                self._changed()
            box.toggled.connect(u)
        flag("unread", unread)
        flag("has_attachment", has_att)
        flag("send_now", now)
        body = QPlainTextEdit(str(self.d.get("body", "")))
        body.setMaximumHeight(90)
        body.setPlaceholderText(tr("{변수} 가능"))

        def upd_body():
            self.d["body"] = body.toPlainText()
            self._changed()
        body.textChanged.connect(upd_body)
        many = ["read", "save_attachments", "mark_read", "move"]
        show = self._rows(f, [
            ("mail_folder", tr("메일함"), self._str_field("mail_folder", tr("비우면 받은편지함")), ["find"]),
            ("from", tr("보낸 사람(일부)"), self._str_field("from", tr("예: 거래처")), ["find"]),
            ("subject", tr("제목(일부)"), self._str_field("subject", tr("예: 청구서")), ["find"]),
            ("unread", "", unread, ["find"]),
            ("has_attachment", "", has_att, ["find"]),
            ("days", tr("최근 며칠"), self._int_field("days", 0, 3650, 0), ["find"]),
            ("mail", tr("다룰 메일"), self._str_field("mail", tr("찾기 결과를 넣은 변수 이름. 예: 메일들")), many),
            ("path", tr("저장할 폴더"), self._str_field("path", tr("예: 받은첨부\\{오늘}")), ["save_attachments"]),
            ("pattern", tr("파일 모양"), self._str_field("pattern", tr("예: *.pdf  (비우면 전부)")), ["save_attachments"]),
            ("to_folder", tr("옮길 메일함"), self._str_field("to_folder", tr("예: 처리완료")), ["move"]),
            ("to", tr("받는 사람"), self._str_field("to", tr("여러 명은 ; 로")), ["send"]),
            ("cc", tr("참조"), self._str_field("cc", ""), ["send"]),
            ("subject2", tr("제목"), self._str_field("subject", tr("{변수} 가능")), ["send"]),
            ("body", tr("본문"), body, ["send"]),
            ("attachments", tr("첨부 파일"), self._str_field("attachments", tr("여러 개는 ; 로. 예: 출력\\정리.xlsx")), ["send"]),
            ("send_now", "", now, ["send"]),
            ("var", tr("결과를 넣을 변수"), self._str_field("var", tr("예: 메일들")), ["find", "read", "save_attachments"]),
        ], ac.currentData)

        def show_via():
            v = vc.currentData()
            sc.setVisible(v == "web")
            sc_lab.setVisible(v == "web")
            acc.setVisible(v == "server")
            acc_lab.setVisible(v == "server")

        def upd_via(_=None):
            self.d["via"] = vc.currentData()
            if vc.currentData() == "web":
                self.d["service"] = sc.currentData()
            else:
                self.d.pop("service", None)
            if vc.currentData() != "server":
                self.d.pop("account", None)
            show_via()
            self._changed()
        vc.currentIndexChanged.connect(upd_via)

        def upd_service(_=None):
            if vc.currentData() == "web":
                self.d["service"] = sc.currentData()
                self._changed()
        sc.currentIndexChanged.connect(upd_service)

        def upd_action(_=None):
            self.d["action"] = ac.currentData()
            show()
            self._changed()
        ac.currentIndexChanged.connect(upd_action)
        show()
        show_via()
        h = QLabel(tr("보내기는 기본으로 임시 보관함에만 저장합니다. 웹메일은 그 브라우저에 미리 로그인해 두세요(로그인 화면이 나오면 멈추고 알려요)."))
        h.setWordWrap(True)
        h.setStyleSheet("color:#666")
        f.addRow("", h)

    def _b_calc(self, f):
        self._line("var", tr("넣을 변수 이름"))
        self._line("expr", tr("계산식"), tr("예: 가격 * 수량 * 1.1   ·   round(합계 / 3, 1)"))
        h = QLabel(tr("변수 이름을 그대로 씁니다. '1,200' 같은 글자도 숫자로 계산해요. + - * / 괄호, round·int·abs·min·max."))
        h.setWordWrap(True)
        h.setStyleSheet("color:#666")
        f.addRow("", h)

    def _b_return(self, f):
        self._literal("value", tr("돌려줄 값"), optional=True)

    def _b_stop(self, f):
        self._line("reason", tr("이유"))

    def _b_comment(self, f):
        e = QPlainTextEdit(str(self.d.get("text", "")))
        e.setMaximumHeight(120)

        def upd():
            self.d["text"] = e.toPlainText()
            self._changed()
        e.textChanged.connect(upd)
        f.addRow(tr("메모"), e)

    # ================================================================ 공통
    def _common(self, f):
        note = QLineEdit(str(self.d.get("note", "")))
        note.setPlaceholderText(tr("스텝 설명(목록에 같이 보임)"))

        def upd_note(text):
            if text:
                self.d["note"] = text
            else:
                self.d.pop("note", None)
            self._changed()
        note.textChanged.connect(upd_note)
        f.addRow(tr("메모"), note)

        of = self.d.get("on_fail", "fail")
        c = QComboBox()
        c.addItem(tr("멈춤(실패로 끝남)"), "fail")
        c.addItem(tr("건너뛰고 계속"), "skip")
        c.addItem(tr("다시 시도"), "retry")
        c.addItem(tr("매크로 끝내기(값 돌려줌)"), "return")
        c.setCurrentIndex(c.findData("return" if isinstance(of, dict) else of) if c.findData(
            "return" if isinstance(of, dict) else of) >= 0 else 0)
        rv = LiteralEdit()
        rv.set_literal(of.get("return", "") if isinstance(of, dict) else "")
        rt = spin(0, 100, int(self.d.get("retries", 2)), 60)
        row = QHBoxLayout()
        row.addWidget(c)
        rv_lab = QLabel(tr("돌려줄 값"))
        rt_lab = QLabel(tr("몇 번"))
        row.addWidget(rv_lab)
        row.addWidget(rv)
        row.addWidget(rt_lab)
        row.addWidget(rt)
        row.addStretch(1)

        def show():
            m = c.currentData()
            for w in (rv_lab, rv):
                w.setVisible(m == "return")      # 고른 것에 필요한 칸만 보이게(좁은 화면에서 잘리지 않게)
            for w in (rt_lab, rt):
                w.setVisible(m == "retry")

        def upd(*_):
            m = c.currentData()
            if m == "fail":
                if self.d.get("on_fail") != "fail":     # 원래 "fail" 이라고 적혀 있었으면 그대로 둔다
                    self.d.pop("on_fail", None)
            elif m == "return":
                self.d["on_fail"] = {"return": rv.literal()}
            else:
                self.d["on_fail"] = m
            if m == "retry":
                self.d["retries"] = int(rt.value())
            show()
            self._changed()
        c.currentIndexChanged.connect(upd)
        rv.changed.connect(upd)
        rt.valueChanged.connect(upd)
        show()
        f.addRow(tr("실패하면"), row)
        self._advanced(f)

    def _advanced(self, f, with_fg: bool = True):
        """고급(접힘): 뒤에서 실행 중 잠깐 앞에서 · 글로 직접 고치기."""
        more = QCheckBox(tr("고급"))
        more.setChecked(bool(self.d.get("foreground")))
        f.addRow(more)
        box = QWidget()
        bf = QFormLayout(box)
        bf.setContentsMargins(16, 0, 0, 0)
        f.addRow(box)
        box.setVisible(more.isChecked())
        more.toggled.connect(box.setVisible)
        if with_fg:
            self._foreground(bf)
        jb = QPushButton(tr("이 스텝을 글로 직접 고치기(JSON)"))
        jb.setMinimumWidth(0)
        jb.clicked.connect(self._edit_json)
        row = QHBoxLayout()
        row.addWidget(jb)
        row.addStretch(1)
        bf.addRow(row)

    def _foreground(self, f):
        fg = QCheckBox(tr("이 스텝만 잠깐 앞에서"))
        fg.setToolTip(tr("'뒤에서 실행' 중 이 스텝만 대상 창을 잠깐 앞으로 가져와 진짜 마우스·키보드로 하고, "
                         "끝나면 원래 쓰던 창과 마우스 자리로 돌려 줍니다. 뒤에서 안 먹는 동작(메뉴줄 클릭 등)에만 켜세요."))
        fg.setChecked(bool(self.d.get("foreground")))

        def upd_fg(on):
            if on:
                self.d["foreground"] = True
            else:
                self.d.pop("foreground", None)
            self._changed()
        fg.toggled.connect(upd_fg)
        hint = QLabel(tr("잠깐 화면을 가져갔다가 돌려줍니다(연달아 켠 스텝은 한 번에)."))
        hint.setStyleSheet("color:#666")
        f.addRow(fg)
        f.addRow(hint)

    # ================================================================ 기타
    def _type_combo(self, tc: QComboBox):
        if self._loading or self.node is None:
            return
        new = tc.currentData()
        if new != self.node.type:
            self.type_change_requested.emit(new)

    def _edit_json(self):
        if self.node is None:
            return
        d = JsonDialog(self.node.data, self)
        if not d.exec():
            return
        val = d.value
        if not isinstance(val, dict) or "type" not in val:
            QMessageBox.warning(self, "JSON", tr("스텝은 'type' 이 있는 객체여야 합니다."))
            return
        for k in self.node.child_keys():
            val.pop(k, None)        # 자식 스텝은 트리에서 고친다
        new_type = val["type"]
        if new_type != self.node.type:
            self.node.set_type(new_type)
        self.node.data = val
        self.set_node(self.node)
        self.changed.emit()


class JsonDialog(QDialog):
    def __init__(self, data, parent=None, title=None, hint=None):
        super().__init__(parent)
        title = title or tr("JSON 으로 고치기")
        hint = hint or tr("자식 스텝(then/else/steps)은 여기 없습니다. 트리에서 고치세요.")
        self.setWindowTitle(title)
        self.resize(640, 480)
        self.value = None
        v = QVBoxLayout(self)
        lab = QLabel(hint)
        lab.setWordWrap(True)
        v.addWidget(lab)
        self.edit = QPlainTextEdit(json.dumps(data, ensure_ascii=False, indent=2))
        v.addWidget(self.edit)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _ok(self):
        try:
            self.value = json.loads(self.edit.toPlainText())
        except ValueError as e:
            QMessageBox.warning(self, "JSON", tr("JSON 형식 오류: {e}").format(e=e))
            return
        self.accept()

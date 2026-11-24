"""
조건(cond) 편집: 보임 / 사라짐 / 변수 비교 / 아님 / 모두 / 하나라도.
'아님'·'모두'·'하나라도' 의 안쪽 조건은 목록에서 골라 대화상자로 고친다.
"""
from __future__ import annotations

import copy

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from gui.v2.describe import cond_text
from gui.v2.i18n import tr
from .target_editor import TargetEditor
from .widgets import fit_stack, ABSENT, LiteralEdit, OptValue, apply_opt

KINDS = [("exists", "보이면"), ("gone", "사라지면"), ("var", "변수 비교"), ("web", "웹 요소가 보이면"),
         ("file", "파일이 있으면"), ("memory", "메모리 값 비교"),
         ("not", "아님(반대)"), ("all", "모두 맞으면"), ("any", "하나라도 맞으면")]
OPS = [("eq", "=="), ("ne", "!="), ("gt", ">"), ("lt", "<"), ("ge", ">="), ("le", "<="),
       ("is_set_true", "있음"), ("is_set_false", "없음"),
       ("contains", "포함"), ("not_contains", "포함 안 함"), ("starts_with", "~로 시작"), ("ends_with", "~로 끝남"),
       ("matches", "규칙(정규식)에 맞음"), ("is_empty_true", "비었음"), ("is_empty_false", "안 비었음")]
_FLAG_OPS = ("is_set", "is_empty")       # 값 칸이 필요 없는 비교
DEFAULT_CHILD = {"exists": {"image": ""}}


def kind_of(c) -> str:
    if isinstance(c, dict):
        for k, _ in KINDS:
            if k in c:
                return "var" if k == "var" else k
    return "exists"


class CondEditor(QWidget):
    changed = Signal()

    def __init__(self, tools=None, parent=None):
        super().__init__(parent)
        self.tools = tools
        self._orig = copy.deepcopy(DEFAULT_CHILD)
        self._children = []         # all/any
        self._child = None          # not
        self._loading = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.addWidget(QLabel(tr("조건")))
        self.kind = QComboBox()
        from gui.v3.icons import memory_on
        self._memory_on = False                 # 11-19: 메모리 조건은 화면에서 숨김(예전에 쓴 조건을 열 때만 보임)
        for k, label in KINDS:
            if k == "memory" and not self._memory_on:      # 부가 기능이 꺼져 있으면 안 보임(이미 쓴 조건을 열 때만 추가)
                continue
            self.kind.addItem(tr(label), k)
        top.addWidget(self.kind)
        top.addStretch(1)
        v.addLayout(top)
        self.stack = QStackedWidget()
        v.addWidget(self.stack)
        self.stack.currentChanged.connect(lambda _=None: fit_stack(self.stack))   # 지금 쪽 크기만큼만
        self.pages = {}

        # 보임/사라짐
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(0, 0, 0, 0)
        self.target = TargetEditor(tools)
        f.addRow(self.target)
        self.gone_for = OptValue(tr("바로(0초)"), None, 0, 3600, 1, 0.5, 1.0)
        self.gone_for_label = QLabel(tr("이 시간 동안 안 보여야"))
        f.addRow(self.gone_for_label, self.gone_for)
        self.stack.addWidget(w)
        self.pages["exists"] = self.pages["gone"] = w
        self.target.changed.connect(self._emit)
        self.gone_for.changed.connect(self._emit)

        # 변수
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(0, 0, 0, 0)
        self.var_name = QLineEdit()
        self.var_op = QComboBox()
        for k, label in OPS:
            self.var_op.addItem(tr(label), k)
        self.var_val = LiteralEdit()
        f.addRow(tr("변수"), self.var_name)
        f.addRow(tr("비교"), self.var_op)
        f.addRow(tr("값"), self.var_val)
        self.stack.addWidget(w)
        self.pages["var"] = w
        self.var_name.textChanged.connect(self._emit)
        self.var_op.currentIndexChanged.connect(self._on_op)
        self.var_val.changed.connect(self._emit)

        # 웹 요소
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(0, 0, 0, 0)
        self.web_sel = QLineEdit()
        self.web_sel.setPlaceholderText(tr("text=로그아웃 / #아이디 / input[name=\"q\"]"))
        f.addRow(tr("요소(선택자)"), self.web_sel)
        self.stack.addWidget(w)
        self.pages["web"] = w

        # 파일
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(0, 0, 0, 0)
        self.file_path = QLineEdit()
        self.file_path.setPlaceholderText(tr("예: 내려받기\\보고서_{오늘}.xlsx"))
        self.file_state = QComboBox()
        self.file_state.addItem(tr("있으면"), True)
        self.file_state.addItem(tr("없으면"), False)
        f.addRow(tr("파일·폴더"), self.file_path)
        f.addRow(tr("상태"), self.file_state)
        self.stack.addWidget(w)
        self.pages["file"] = w
        self.file_path.textChanged.connect(self._emit)
        self.file_state.currentIndexChanged.connect(self._emit)
        self.web_sel.textChanged.connect(self._emit)

        # 메모리 값(부가 기능)
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(0, 0, 0, 0)
        self.mem_name = QComboBox()
        self.mem_name.setEditable(True)
        try:
            from engine.memory import load_values
            self.mem_name.addItems(sorted(load_values()))
        except Exception:
            pass
        self.mem_op = QComboBox()
        for k, label in [o for o in OPS if o[0] in ("eq", "ne", "gt", "lt", "ge", "le")] + [("changed", "바뀌면(기다리기에서만)")]:
            self.mem_op.addItem(tr(label), k)
        self.mem_val = LiteralEdit()
        f.addRow(tr("메모리 값(저장한 이름)"), self.mem_name)
        f.addRow(tr("비교"), self.mem_op)
        f.addRow(tr("값"), self.mem_val)
        self.stack.addWidget(w)
        self.pages["memory"] = w
        self.mem_name.currentTextChanged.connect(self._emit)
        self.mem_op.currentIndexChanged.connect(lambda _=None: (self.mem_val.setEnabled(self.mem_op.currentData() != "changed"),
                                                                self._emit()))
        self.mem_val.changed.connect(self._emit)

        # 아님
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        self.not_label = QLabel()
        self.not_label.setWordWrap(True)
        b = QPushButton(tr("안쪽 조건 고치기"))
        b.setMinimumWidth(0)
        b.clicked.connect(self._edit_not)
        h.addWidget(self.not_label, 1)
        h.addWidget(b)
        self.stack.addWidget(w)
        self.pages["not"] = w

        # 모두/하나라도
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setMinimumHeight(90)
        self.list.itemDoubleClicked.connect(lambda _: self._edit_child())
        h.addWidget(self.list, 1)
        bv = QVBoxLayout()
        for label, fn in (("추가", self._add_child), ("고치기", self._edit_child), ("삭제", self._del_child),
                          ("위로", lambda: self._move_child(-1)), ("아래로", lambda: self._move_child(1))):
            b = QPushButton(tr(label))
            b.setMinimumWidth(0)
            b.clicked.connect(fn)
            bv.addWidget(b)
        bv.addStretch(1)
        h.addLayout(bv)
        self.stack.addWidget(w)
        self.pages["all"] = self.pages["any"] = w

        self.kind.currentIndexChanged.connect(self._kind_changed)
        fit_stack(self.stack)

    # ------------------------------------------------------------ 값
    def set_cond(self, c):
        self._loading = True
        self._orig = copy.deepcopy(c) if isinstance(c, dict) else copy.deepcopy(DEFAULT_CHILD)
        self._children = []
        self._child = None
        c = self._orig
        k = kind_of(c)
        self.kind.setCurrentIndex(self.kind.findData(k))
        self._show_page(k)
        if k in ("exists", "gone"):
            self.target.set_target(c.get(k) if isinstance(c.get(k), dict) else {"image": ""})
            self.gone_for.set_value(c.get("for", ABSENT))
        elif k == "var":
            self.var_name.setText(str(c.get("var", "")))
            if "is_set" in c or "is_empty" in c:
                f = "is_set" if "is_set" in c else "is_empty"
                self.var_op.setCurrentIndex(self.var_op.findData(f + ("_true" if c[f] else "_false")))
                self.var_val.set_literal("")
            else:
                op = next((o for o, _ in OPS if o in c), "eq")
                self.var_op.setCurrentIndex(self.var_op.findData(op))
                self.var_val.set_literal(c.get(op, ""))
            self.var_val.setEnabled(not str(self.var_op.currentData()).startswith(_FLAG_OPS))
        elif k == "web":
            self.web_sel.setText(str((c.get("web") or {}).get("selector", "")))
        elif k == "file":
            fc = c.get("file") or {}
            self.file_path.setText(str(fc.get("path", "")))
            self.file_state.setCurrentIndex(0 if fc.get("exists", True) else 1)
        elif k == "memory":
            mc = c.get("memory") or {}
            if self.kind.findData("memory") < 0:
                self.kind.addItem(tr("메모리 값 비교"), "memory")
                self.kind.setCurrentIndex(self.kind.findData("memory"))
            v = mc.get("value")
            self.mem_name.setCurrentText(v if isinstance(v, str) else "")
            op = next((o for o in ("eq", "ne", "gt", "lt", "ge", "le", "changed") if o in mc), "eq")
            self.mem_op.setCurrentIndex(max(0, self.mem_op.findData(op)))
            self.mem_val.set_literal("" if op == "changed" else mc.get(op, ""))
            self.mem_val.setEnabled(op != "changed")
        elif k == "not":
            self._child = copy.deepcopy(c.get("not") or DEFAULT_CHILD)
            self.not_label.setText(cond_text(self._child))
        elif k in ("all", "any"):
            self._children = copy.deepcopy(c.get(k) or [])
            self._refresh_list()
        self._loading = False

    def cond(self) -> dict:
        k = self.kind.currentData()
        same = kind_of(self._orig) == k
        c = copy.deepcopy(self._orig) if same else {}
        if k in ("exists", "gone"):
            c.pop("exists" if k == "gone" else "gone", None)
            c[k] = self.target.target()
            if k == "gone":
                apply_opt(c, "for", self.gone_for.value())
            else:
                c.pop("for", None)
        elif k == "var":
            for o, _ in OPS:
                c.pop(o, None)
            c.pop("is_set", None)
            c.pop("is_empty", None)
            c["var"] = self.var_name.text().strip()
            op = self.var_op.currentData()
            if op.startswith(_FLAG_OPS):
                f = "is_set" if op.startswith("is_set") else "is_empty"
                c[f] = op.endswith("_true")
            else:
                c[op] = self.var_val.literal()
        elif k == "web":
            w = dict(c.get("web") or {}) if same else {}
            w["selector"] = self.web_sel.text().strip()
            c = {"web": w}
        elif k == "file":
            fc = {"path": self.file_path.text().strip()}
            if not self.file_state.currentData():
                fc["exists"] = False
            elif same and (self._orig.get("file") or {}).get("exists") is True:
                fc["exists"] = True             # 원래 적혀 있던 '있음'은 그대로 둠(뜻은 같지만 파일이 안 바뀌게)
            c = {"file": fc}
        elif k == "memory":
            old = (self._orig.get("memory") or {}) if same else {}
            name = self.mem_name.currentText().strip()
            mc = {"value": name if name else old.get("value", "")}
            op = self.mem_op.currentData()
            mc[op] = True if op == "changed" else self.mem_val.literal()
            c = {"memory": mc}
        elif k == "not":
            c = {"not": copy.deepcopy(self._child or DEFAULT_CHILD)}
        elif k in ("all", "any"):
            c = {k: copy.deepcopy(self._children)}
        return c

    # ------------------------------------------------------------ 내부
    def _emit(self, *_):
        if not self._loading:
            self.changed.emit()

    def _show_page(self, k):
        self.stack.setCurrentWidget(self.pages[k])
        g = k == "gone"
        self.gone_for.setVisible(g)
        self.gone_for_label.setVisible(g)

    def _kind_changed(self, *_):
        k = self.kind.currentData()
        self._show_page(k)
        if self._loading:
            return
        if k in ("all", "any") and not self._children:
            prev = self.cond_before_kind_change()
            self._children = [prev] if prev else [copy.deepcopy(DEFAULT_CHILD)]
            self._refresh_list()
        if k == "not" and self._child is None:
            self._child = self.cond_before_kind_change() or copy.deepcopy(DEFAULT_CHILD)
            self.not_label.setText(cond_text(self._child))
        if k in ("exists", "gone") and kind_of(self._orig) not in ("exists", "gone"):
            self.target.set_target({"image": ""})
        self.changed.emit()

    def cond_before_kind_change(self):
        """종류를 '모두/아님' 으로 바꿀 때, 원래 조건을 안쪽으로 넣어 준다."""
        k0 = kind_of(self._orig)
        if k0 in ("exists", "gone", "var", "web"):
            return copy.deepcopy(self._orig)
        return None

    def _on_op(self, *_):
        self.var_val.setEnabled(not str(self.var_op.currentData()).startswith(_FLAG_OPS))
        self._emit()

    def _refresh_list(self):
        self.list.clear()
        for ch in self._children:
            self.list.addItem(cond_text(ch))

    def _dialog(self, c):
        d = CondDialog(c, self.tools, self)
        return d.result_cond() if d.exec() else None

    def _edit_not(self):
        r = self._dialog(self._child or DEFAULT_CHILD)
        if r is not None:
            self._child = r
            self.not_label.setText(cond_text(r))
            self.changed.emit()

    def _add_child(self):
        r = self._dialog(DEFAULT_CHILD)
        if r is not None:
            self._children.append(r)
            self._refresh_list()
            self.list.setCurrentRow(len(self._children) - 1)
            self.changed.emit()

    def _edit_child(self):
        i = self.list.currentRow()
        if i < 0:
            return
        r = self._dialog(self._children[i])
        if r is not None:
            self._children[i] = r
            self._refresh_list()
            self.list.setCurrentRow(i)
            self.changed.emit()

    def _del_child(self):
        i = self.list.currentRow()
        if i >= 0:
            del self._children[i]
            self._refresh_list()
            self.changed.emit()

    def _move_child(self, d):
        i = self.list.currentRow()
        j = i + d
        if i < 0 or not (0 <= j < len(self._children)):
            return
        self._children[i], self._children[j] = self._children[j], self._children[i]
        self._refresh_list()
        self.list.setCurrentRow(j)
        self.changed.emit()


class CondDialog(QDialog):
    def __init__(self, cond, tools=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("조건 고치기"))
        self.resize(720, 360)
        v = QVBoxLayout(self)
        self.editor = CondEditor(tools)
        self.editor.set_cond(cond)
        v.addWidget(self.editor)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def result_cond(self):
        return self.editor.cond()

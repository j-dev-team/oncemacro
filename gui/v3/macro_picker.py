"""매크로 고르기 부품(11-18): 예약·매크로 호출 단계 등 매크로를 고르는 곳은 전부 이것을 쓴다.

- 글자를 치면 바로 걸러짐(대소문자·띄어쓰기·밑줄 무시, 이름 일부만 쳐도 됨)
- 기본은 '맨 위 매크로'(다른 매크로가 부르지 않는 것)만. '다른 매크로가 부르는 것도 보기'를 켜면 전부
- 메인 목록과 같은 묶음(폴더) 구조, 맨 위에 '최근 실행'
- 목록은 화면을 넘지 않는 높이에서 스크롤

MacroPicker: 고른 이름 칸 + [고르기…] 단추(칸에 직접 쳐도 됨). MacroPickerDialog: 고르기 창.
"""
from __future__ import annotations

import os
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from gui.v2.i18n import tr

ROLE_NAME = Qt.UserRole + 1


def norm(s: str) -> str:
    return "".join((s or "").lower().split()).replace("_", "").replace("-", "")


def matches(name: str, query: str) -> bool:
    q = norm(query)
    return not q or q in norm(name)


class PickerSource:
    """고를 수 있는 매크로들: 이름·묶음·부르는 관계·최근 실행. 저장소(MacroStore)에서 만든다."""

    def __init__(self, names: List[str], groups: List[Tuple[str, List[str]]] = (), loose: Optional[List[str]] = None,
                 called: Iterable[str] = (), recent: Iterable[str] = ()):
        self.names = [n for n in names]
        seen = {n for _, ns in groups for n in ns}
        self.groups = [(g, [n for n in ns if n in self.names]) for g, ns in groups]
        self.loose = loose if loose is not None else sorted(n for n in self.names if n not in seen)
        self.called = set(called)
        self.recent = [n for n in recent if n in self.names]

    @classmethod
    def from_store(cls, store, exclude: Iterable[str] = (), recent: Iterable[str] = (), hide_test: bool = True):
        ex = set(exclude)
        names = [n for n in store.names() if n not in ex and not (hide_test and n.startswith("_"))]
        try:
            groups, loose = store.tree()
        except Exception:
            groups, loose = [], None
        groups = [(g, [n for n in ns if n in names]) for g, ns in groups]
        if loose is not None:
            loose = [n for n in loose if n in names]
        return cls(names, groups, loose, called_names(store), recent)

    @classmethod
    def from_names(cls, names: List[str]):
        return cls(list(names))


_CALLED_CACHE: Dict[str, Tuple[float, List[str]]] = {}


def called_names(store) -> set:
    """다른 매크로가 call 로 부르는 매크로 이름들(파일이 바뀐 것만 다시 읽음)."""
    from gui.v2.model import walk_dict
    out = set()
    for n in store.names():
        try:
            fp = store.path(n)
            mt = os.path.getmtime(fp)
        except Exception:
            fp, mt = n, 0.0
        hit = _CALLED_CACHE.get(fp)
        if hit is None or hit[0] != mt:
            try:
                m = store.load(n)
                calls = [s.get("macro") for _, s in walk_dict(m.get("steps", []))
                         if isinstance(s, dict) and s.get("type") == "call" and s.get("macro") != n]
            except Exception:
                calls = []
            hit = _CALLED_CACHE[fp] = (mt, calls)
        out.update(c for c in hit[1] if c)
    return out


class MacroPickerDialog(QDialog):
    def __init__(self, source: PickerSource, current: str = "", parent=None, roots_only: bool = True,
                 title: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title or tr("매크로 고르기"))
        self.src = source
        self.chosen = ""
        v = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("이름 일부를 치세요 (띄어쓰기 무시)"))
        self.search.setClearButtonEnabled(True)
        v.addWidget(self.search)
        self.show_all = QCheckBox(tr("다른 매크로가 부르는 매크로도 보기"))
        self.show_all.setChecked(not roots_only or (current in source.called))
        self.show_all.setToolTip(tr("끄면 맨 위 매크로(다른 매크로가 부르지 않는 것)만 보입니다"))
        v.addWidget(self.show_all)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        v.addWidget(self.tree, 1)
        self.count = QLabel("")
        self.count.setObjectName("Muted")
        v.addWidget(self.count)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("고르기"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("취소"))
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        self.ok_btn = bb.button(QDialogButtonBox.Ok)
        v.addWidget(bb)
        self.search.textChanged.connect(lambda _=None: self.refill())
        self.show_all.toggled.connect(lambda _=None: self.refill())
        self.tree.itemDoubleClicked.connect(lambda it, _c=0: it.data(0, ROLE_NAME) and self._accept())
        self.tree.currentItemChanged.connect(lambda *_: self.ok_btn.setEnabled(self._current() != ""))
        self._fit_height()
        self.refill(select=current)
        self.search.setFocus()

    def _fit_height(self):
        try:
            scr = (self.parent().screen() if self.parent() is not None else None) or self.screen()
            h = scr.availableGeometry().height()
        except Exception:
            h = 800
        self.resize(460, min(560, int(h * 0.75)))
        self.setMaximumHeight(int(h * 0.9))

    def visible_names(self) -> List[str]:
        return [n for n in self.src.names if (self.show_all.isChecked() or n not in self.src.called)
                and matches(n, self.search.text())]

    def refill(self, select: str = ""):
        select = select or self._current()
        keep = set(self.visible_names())
        self.tree.clear()
        sel_item = None

        def add(parent, name):
            nonlocal sel_item
            it = QTreeWidgetItem([name])
            it.setData(0, ROLE_NAME, name)
            if name in self.src.called:
                it.setToolTip(0, tr("다른 매크로가 부르는 매크로"))
            (parent.addChild(it) if parent is not None else self.tree.addTopLevelItem(it))
            if name == select and sel_item is None:
                sel_item = it
            return it

        def folder(label):
            g = QTreeWidgetItem([label])
            g.setFlags(g.flags() & ~Qt.ItemIsSelectable)
            f = g.font(0)
            f.setBold(True)
            g.setFont(0, f)
            return g

        searching = bool(norm(self.search.text()))
        recent = [n for n in self.src.recent if n in keep][:5]
        if recent and not searching:
            g = folder("🕘 " + tr("최근 실행"))
            self.tree.addTopLevelItem(g)
            for n in recent:
                add(g, n)
            g.setExpanded(True)
        for gname, ns in self.src.groups:
            shown = [n for n in ns if n in keep]
            if not shown:
                continue
            g = folder("📁 " + gname)
            self.tree.addTopLevelItem(g)
            for n in shown:
                add(g, n)
            g.setExpanded(searching or len(self.src.groups) <= 3 or select in shown)
        for n in self.src.loose:
            if n in keep:
                add(None, n)
        if sel_item is None and searching:          # 찾는 중이면 첫 결과를 골라 둠(엔터로 바로 고름)
            for i in range(self.tree.topLevelItemCount()):
                top = self.tree.topLevelItem(i)
                cand = top if top.data(0, ROLE_NAME) else (top.child(0) if top.childCount() else None)
                if cand is not None:
                    sel_item = cand
                    break
        if sel_item is not None:
            p = sel_item.parent()
            if p is not None:
                p.setExpanded(True)
            self.tree.setCurrentItem(sel_item)
            self.tree.scrollToItem(sel_item)
        total = len(self.src.names) if self.show_all.isChecked() else len([n for n in self.src.names if n not in self.src.called])
        self.count.setText(tr("{shown}개 보임 / {total}개").format(shown=len(keep), total=total)
                           + ("" if self.show_all.isChecked() else tr(" (다른 매크로가 부르는 {n}개는 숨김)").format(
                               n=len([n for n in self.src.names if n in self.src.called]))))
        self.ok_btn.setEnabled(self._current() != "")

    def _current(self) -> str:
        it = self.tree.currentItem()
        return (it.data(0, ROLE_NAME) or "") if it is not None else ""

    def _accept(self):
        name = self._current()
        if name:
            self.chosen = name
            self.accept()

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._accept()
            return
        if ev.key() in (Qt.Key_Down, Qt.Key_Up) and self.search.hasFocus():
            self.tree.setFocus()
        super().keyPressEvent(ev)


class MacroPicker(QWidget):
    """고른 매크로 이름 칸 + [고르기…]. editable=True 면 칸에 직접 쳐도 됨(아직 없는 이름 등)."""
    changed = Signal(str)

    def __init__(self, source_fn: Callable[[], PickerSource], current: str = "", parent=None,
                 roots_only: bool = True, editable: bool = False, title: str = ""):
        super().__init__(parent)
        self.source_fn = source_fn
        self.roots_only = roots_only
        self.title = title
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(current or "")
        self.edit.setReadOnly(not editable)
        self.edit.setPlaceholderText(tr("매크로를 고르세요"))
        self.edit.textChanged.connect(lambda t: self.changed.emit(t.strip()))
        h.addWidget(self.edit, 1)
        self.btn = QPushButton(tr("고르기…"))
        self.btn.clicked.connect(self.pick)
        h.addWidget(self.btn)
        if not editable:
            self.edit.mousePressEvent = lambda ev: self.pick()

    def name(self) -> str:
        return self.edit.text().strip()

    def set_name(self, name: str):
        self.edit.setText(name or "")

    def pick(self) -> bool:
        d = MacroPickerDialog(self.source_fn(), self.name(), self.window(), roots_only=self.roots_only,
                              title=self.title)
        if d.exec() and d.chosen:
            self.set_name(d.chosen)
            return True
        return False

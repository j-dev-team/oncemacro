"""
대상(target) 편집: 버튼 이름(창 요소) / 이미지 / 색(한 점) / 색(영역) / 선명한 색 / 좌표 / 변수.

같은 종류 안에서 고치면 이 화면이 모르는 키도 그대로 남는다. 종류를 바꾸면 새로 만든다(offset 만 유지).
'화면에서 찍기/지정/자르기' 는 tools(ScreenTools) 가 있을 때만 동작한다.
"""
from __future__ import annotations

import copy
import os
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from gui.v2.i18n import tr
from .widgets import (fit_stack, ABSENT, ColorEdit, OptValue, RegionEdit, XYEdit, apply_opt, hues_text,
                      parse_hues, spin)

KINDS = [("element", "버튼 이름(창 요소)"), ("image", "이미지"), ("color_at", "색 (한 점)"), ("color_region", "색 (영역 안)"),
         ("vivid", "선명한 색 (영역 안)"), ("point", "좌표"), ("var", "변수(기억한 좌표)")]


EL_TYPES = [("", "아무 종류"), ("button", "버튼"), ("edit", "입력칸"), ("text", "글자"), ("checkbox", "체크 상자"),
            ("radio", "선택 단추"), ("combo", "고르기 상자"), ("menuitem", "메뉴 항목"), ("tabitem", "탭"),
            ("listitem", "목록 항목"), ("treeitem", "트리 항목"), ("link", "링크"), ("dataitem", "표 칸")]


def _put(t: dict, key: str, val, default) -> None:
    """원래 키가 있었거나 기본값과 다를 때만 넣는다(기본값을 일부러 안 적은 매크로를 그대로 두려고)."""
    if key in t or val != default:
        t[key] = val


def kind_of(t) -> str:
    if not isinstance(t, dict):
        return "point"
    if "image" in t:
        return "image"
    if "color" in t:
        return "color_region" if "region" in t else "color_at"
    if "vivid" in t:
        return "vivid"
    if "var" in t:
        return "var"
    if "element" in t:
        return "element"
    return "point"


class TargetEditor(QWidget):
    changed = Signal()

    def __init__(self, tools=None, parent=None, allow_kinds=None):
        super().__init__(parent)
        self.tools = tools
        self._orig: dict = {"point": [0, 0]}
        self._loading = False
        self._pending = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.addWidget(QLabel(tr("종류")))
        self.kind = QComboBox()
        for k, label in KINDS:
            if allow_kinds is None or k in allow_kinds:
                self.kind.addItem(tr(label), k)
        top.addWidget(self.kind)
        top.addStretch(1)
        v.addLayout(top)
        self.stack = QStackedWidget()
        v.addWidget(self.stack)
        self.stack.currentChanged.connect(lambda _=None: fit_stack(self.stack))   # 지금 쪽 크기만큼만
        self.pages = {}
        self._build_unset()
        self._build_image()
        self._build_color_at()
        self._build_color_region()
        self._build_vivid()
        self._build_point()
        self._build_var()
        self._build_element()
        self.offset_on = QCheckBox(tr("찾은 위치를 조금 옮기기"))
        self.offset_on.setToolTip(tr("찾은 위치에서 x·y 만큼 옮긴 곳을 씁니다(오른쪽·아래가 +). 예: 글자 옆 칸을 누를 때."))
        self.offset = XYEdit(pick_label=None)
        v.addWidget(self.offset_on)
        v.addWidget(self.offset)
        self.offset.setVisible(False)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.offset_on.toggled.connect(self.offset.setVisible)
        self.offset_on.toggled.connect(self._emit)
        self.offset.changed.connect(self._emit)
        fit_stack(self.stack)

    # ------------------------------------------------------------ 페이지
    def _page(self, key) -> QFormLayout:
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(w)
        self.pages[key] = w
        return f

    def _build_unset(self):
        """아직 대상을 안 정한 상태: (0,0) 대신 '화면에서 찍기'를 앞에 보여 준다."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 2, 0, 2)
        msg = QLabel(tr("아직 정하지 않았어요. 화면에서 직접 고르세요."))
        msg.setWordWrap(True)
        msg.setObjectName("Muted")
        lay.addWidget(msg)
        row = QHBoxLayout()
        self.unset_pick = QPushButton(tr("화면에서 찍기"))
        self.unset_pick.setObjectName("Primary")
        self.unset_pick.setToolTip(tr("화면이 잠깐 어두워지면 누를 곳을 한 번 클릭하세요."))
        self.unset_cut = QPushButton(tr("그림으로 찾기"))
        self.unset_cut.setToolTip(tr("버튼 모양을 잘라 두면, 자리가 바뀌어도 그 그림을 찾아 누릅니다."))
        self.unset_el = QPushButton(tr("버튼 이름으로"))
        self.unset_el.setToolTip(tr("일반 프로그램의 버튼·입력칸을 이름으로 찾습니다. 화면 크기·배율이 바뀌어도 잘 찾아요(게임 화면은 안 됨)."))
        self.unset_el.clicked.connect(self._pick_element_from_unset)
        for b in (self.unset_pick, self.unset_cut, self.unset_el):
            b.setMinimumWidth(0)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.unset_pick.clicked.connect(self._pick_from_unset)
        self.unset_cut.clicked.connect(self._cut_from_unset)
        self.stack.addWidget(w)
        self.pages["unset"] = w

    def _build_image(self):
        f = self._page("image")
        self.img_path = QLineEdit()
        self.img_path.setPlaceholderText(tr("그림 파일, 예: 내폴더/확인버튼.png"))
        self.img_path.setToolTip(tr("image 폴더 기준 경로"))
        f.addRow(tr("이미지"), self.img_path)
        row = QHBoxLayout()
        b2 = QPushButton(tr("화면에서 자르기"))
        b1 = QPushButton(tr("찾아보기"))
        for b in (b1, b2):
            b.setMinimumWidth(0)
        b1.clicked.connect(self._browse_image)
        b2.clicked.connect(self._capture_image)
        row.addWidget(b2)
        row.addWidget(b1)
        row.addStretch(1)
        f.addRow("", row)
        self.img_preview = QLabel()
        f.addRow("", self.img_preview)
        self.img_region_on = QCheckBox(tr("이 영역 안에서만 찾기"))
        self.img_region = RegionEdit()
        f.addRow(self.img_region_on)
        f.addRow(self.img_region)
        self.img_region.setVisible(False)
        self.img_region_on.toggled.connect(self.img_region.setVisible)
        # 자세히(접힘): 얼마나 똑같아야 하는지·색 검사·크기 달라도
        self.img_more = QCheckBox(tr("자세히(얼마나 똑같아야 찾았다고 볼지)"))
        f.addRow(self.img_more)
        adv = QWidget()
        af = QFormLayout(adv)
        af.setContentsMargins(16, 0, 0, 0)
        self.img_conf = OptValue(tr("기본값(0.8)"), None, 0.3, 1.0, 3, 0.01, 0.8)
        self.img_conf.setToolTip(tr("1에 가까울수록 똑같아야 찾았다고 봅니다. 잘 못 찾으면 낮추고, 엉뚱한 걸 찾으면 높이세요."))
        af.addRow(tr("닮은 정도"), self.img_conf)
        self.img_cc = OptValue(tr("기본값(0.85)"), tr("끔"), 0.3, 1.0, 3, 0.01, 0.85)
        self.img_cc.setToolTip(tr("모양이 같아도 색이 다르면 다른 것으로 봅니다(켜진 버튼·꺼진 버튼 구분)."))
        af.addRow(tr("색도 비교"), self.img_cc)
        self.img_multi = QCheckBox(tr("크기가 조금 달라도 찾기(느림)"))
        af.addRow(self.img_multi)
        f.addRow(adv)
        adv.setVisible(False)
        self.img_more.toggled.connect(adv.setVisible)
        self._img_adv = adv
        self.img_path.textChanged.connect(self._on_image_path)
        self.img_region_on.toggled.connect(self._emit)
        self.img_region.changed.connect(self._emit)
        self.img_region.pick.connect(lambda: self._pick_region(self.img_region, self.img_region_on))
        for w in (self.img_conf, self.img_cc):
            w.changed.connect(self._emit)
        self.img_multi.toggled.connect(self._emit)

    def _build_color_at(self):
        f = self._page("color_at")
        self.ca_color = ColorEdit()
        self.ca_at = XYEdit()
        self.ca_tol = spin(0, 255, 10, 60)
        f.addRow(tr("색"), self.ca_color)
        f.addRow(tr("위치"), self.ca_at)
        f.addRow(tr("허용 오차"), self.ca_tol)
        self.ca_color.changed.connect(self._emit)
        self.ca_at.changed.connect(self._emit)
        self.ca_tol.valueChanged.connect(self._emit)
        self.ca_color.pick.connect(self._pick_color_at)
        self.ca_at.pick.connect(self._pick_color_at)

    def _build_color_region(self):
        f = self._page("color_region")
        self.cr_color = ColorEdit()
        self.cr_region = RegionEdit()
        self.cr_tol = spin(0, 255, 10, 60)
        mode = QHBoxLayout()
        self.cr_mode = QComboBox()
        self.cr_mode.addItem(tr("픽셀 수 이상(위치 = 평균)"), "min_pixels")
        self.cr_mode.addItem(tr("덩어리 두께 이상(위치 = 가장 두꺼운 곳)"), "blob_depth")
        self.cr_val = spin(1, 100000, 10, 80)
        mode.addWidget(self.cr_mode)
        mode.addWidget(self.cr_val)
        mode.addStretch(1)
        f.addRow(tr("색"), self.cr_color)
        f.addRow(tr("영역"), self.cr_region)
        f.addRow(tr("허용 오차"), self.cr_tol)
        f.addRow(tr("있다고 볼 기준"), mode)
        self.cr_color.changed.connect(self._emit)
        self.cr_region.changed.connect(self._emit)
        self.cr_tol.valueChanged.connect(self._emit)
        self.cr_mode.currentIndexChanged.connect(self._emit)
        self.cr_val.valueChanged.connect(self._emit)
        self.cr_color.pick.connect(lambda: self._pick_color_only(self.cr_color))
        self.cr_region.pick.connect(lambda: self._pick_region(self.cr_region))

    def _build_vivid(self):
        f = self._page("vivid")
        self.vv_region = RegionEdit()
        self.vv_min = spin(1, 100000, 50, 80)
        self.vv_sat = spin(0, 255, 110, 60)
        self.vv_val = spin(0, 255, 110, 60)
        self.vv_hues = QLineEdit()
        self.vv_hues.setPlaceholderText(tr("색상 범위(H 0~180), 예: 0-10, 160-180 / 비우면 전부"))
        f.addRow(tr("영역"), self.vv_region)
        f.addRow(tr("최소 픽셀 수"), self.vv_min)
        f.addRow(tr("최소 채도"), self.vv_sat)
        f.addRow(tr("최소 밝기"), self.vv_val)
        f.addRow(tr("색상 범위"), self.vv_hues)
        self.vv_region.changed.connect(self._emit)
        self.vv_region.pick.connect(lambda: self._pick_region(self.vv_region))
        for s in (self.vv_min, self.vv_sat, self.vv_val):
            s.valueChanged.connect(self._emit)
        self.vv_hues.textChanged.connect(self._emit)

    def _build_point(self):
        f = self._page("point")
        self.pt = XYEdit()
        f.addRow(tr("위치"), self.pt)
        self.pt.changed.connect(self._emit)
        self.pt.pick.connect(lambda: self._pick_point(self.pt))

    def _build_var(self):
        f = self._page("var")
        self.var_name = QLineEdit()
        f.addRow(tr("변수 이름"), self.var_name)
        self.var_name.textChanged.connect(self._emit)

    def _build_element(self):
        f = self._page("element")
        self.el_name = QLineEdit()
        self.el_name.setPlaceholderText(tr("화면에 보이는 이름, 예: 확인"))
        f.addRow(tr("이름"), self.el_name)
        self.el_type = QComboBox()
        for k, label in EL_TYPES:
            self.el_type.addItem(tr(label), k)
        f.addRow(tr("요소 종류"), self.el_type)
        self.el_contains = QCheckBox(tr("이름 일부만 맞아도 찾기"))
        f.addRow(self.el_contains)
        self.el_index = spin(0, 999, 0, 60)
        self.el_index.setToolTip(tr("같은 이름이 여러 개일 때 몇 번째인지(0 = 처음)"))
        f.addRow(tr("같은 이름 중 순서"), self.el_index)
        row = QHBoxLayout()
        b = QPushButton(tr("화면에서 버튼 고르기"))
        b.setMinimumWidth(0)
        b.clicked.connect(self._pick_element)
        row.addWidget(b)
        row.addStretch(1)
        f.addRow("", row)
        self.el_name.textChanged.connect(self._emit)
        self.el_type.currentIndexChanged.connect(self._emit)
        self.el_contains.toggled.connect(self._emit)
        self.el_index.valueChanged.connect(self._emit)

    # ------------------------------------------------------------ 값 넣고 빼기
    def set_target(self, t):
        self._loading = True
        self._pending = False
        if not isinstance(t, dict):                      # 아직 안 정함
            self._orig = {}
            self._set_unset_item(True)
            self.kind.setCurrentIndex(self.kind.findData("unset"))
            self.stack.setCurrentWidget(self.pages["unset"])
            self.offset_on.setChecked(False)
            self.offset_on.setVisible(False)
            self._loading = False
            return
        self._set_unset_item(False)
        self.offset_on.setVisible(True)
        self._orig = copy.deepcopy(t)
        t = self._orig
        k = kind_of(t)
        self.kind.setCurrentIndex(max(0, self.kind.findData(k)))
        self.stack.setCurrentWidget(self.pages[k])
        if k == "image":
            self.img_path.setText(str(t.get("image") or ""))
            has_r = isinstance(t.get("region"), (list, tuple))
            self.img_region_on.setChecked(has_r)
            if has_r:
                self.img_region.set_region(t["region"])
            self.img_conf.set_value(t.get("confidence", ABSENT))
            self.img_cc.set_value(t["color_check"] if "color_check" in t else ABSENT)
            self.img_multi.setChecked(bool(t.get("multiscale")))
            self.img_more.setChecked("confidence" in t or "color_check" in t or bool(t.get("multiscale")))
        elif k == "color_at":
            self.ca_color.set_rgb(t.get("color", [0, 0, 0]))
            self.ca_at.set_xy(t.get("at", [0, 0]))
            self.ca_tol.setValue(int(t.get("tolerance", 0)))
        elif k == "color_region":
            self.cr_color.set_rgb(t.get("color", [0, 0, 0]))
            self.cr_region.set_region(t.get("region", [0, 0, 100, 100]))
            self.cr_tol.setValue(int(t.get("tolerance", 0)))
            if "blob_depth" in t:
                self.cr_mode.setCurrentIndex(1)
                self.cr_val.setValue(int(t["blob_depth"]))
            else:
                self.cr_mode.setCurrentIndex(0)
                self.cr_val.setValue(int(t.get("min_pixels", 10)))
        elif k == "vivid":
            self.vv_region.set_region(t.get("region", [0, 0, 100, 100]))
            self.vv_min.setValue(int(t.get("min_pixels", 50)))
            self.vv_sat.setValue(int(t.get("min_saturation", 110)))
            self.vv_val.setValue(int(t.get("min_value", 110)))
            self.vv_hues.setText(hues_text(t.get("hues")))
        elif k == "point":
            self.pt.set_xy(t.get("point", [0, 0]))
        elif k == "var":
            self.var_name.setText(str(t.get("var", "")))
        elif k == "element":
            self._load_element(t.get("element") or {})
        has_off = isinstance(t.get("offset"), (list, tuple))
        self.offset_on.setChecked(has_off)
        self.offset.set_xy(t.get("offset", [0, 0]) if has_off else [0, 0])
        self._update_preview()
        self._loading = False

    def is_unset(self) -> bool:
        return self.kind.currentData() == "unset"

    def target(self) -> Optional[dict]:
        """정한 대상. 아직 안 정했으면 None."""
        k = self.kind.currentData()
        if k == "unset" or self._pending:
            return None
        same = kind_of(self._orig) == k
        t = copy.deepcopy(self._orig) if same else {}
        if k == "image":
            t["image"] = self.img_path.text().strip()
            if self.img_region_on.isChecked():
                t["region"] = self.img_region.region()
            else:
                t.pop("region", None)
            apply_opt(t, "confidence", self.img_conf.value())
            apply_opt(t, "color_check", self.img_cc.value())
            if self.img_multi.isChecked():
                t["multiscale"] = True
            else:
                t.pop("multiscale", None)
        elif k == "color_at":
            t["color"] = self.ca_color.rgb()
            t["at"] = self.ca_at.xy()
            _put(t, "tolerance", self.ca_tol.value(), 0)
            for x in ("region", "min_pixels", "blob_depth"):
                t.pop(x, None)
        elif k == "color_region":
            t["color"] = self.cr_color.rgb()
            t["region"] = self.cr_region.region()
            _put(t, "tolerance", self.cr_tol.value(), 0)
            t.pop("at", None)
            mode = self.cr_mode.currentData()
            t.pop("min_pixels" if mode == "blob_depth" else "blob_depth", None)
            if mode == "min_pixels":
                _put(t, "min_pixels", self.cr_val.value(), 10)
            else:
                t["blob_depth"] = self.cr_val.value()
        elif k == "vivid":
            t["vivid"] = True
            t["region"] = self.vv_region.region()
            _put(t, "min_pixels", self.vv_min.value(), 50)
            _put(t, "min_saturation", self.vv_sat.value(), 110)
            _put(t, "min_value", self.vv_val.value(), 110)
            try:
                h = parse_hues(self.vv_hues.text())
            except ValueError:
                h = self._orig.get("hues")
            if h:
                t["hues"] = h
            else:
                t.pop("hues", None)
        elif k == "point":
            t["point"] = self.pt.xy()
        elif k == "var":
            t["var"] = self.var_name.text().strip()
        elif k == "element":
            e = dict(t.get("element") or {}) if isinstance(t.get("element"), dict) else {}
            name = self.el_name.text().strip()
            if name:
                e["name"] = name
            else:
                e.pop("name", None)
            ty = self.el_type.currentData()
            if ty:
                e["type"] = ty
            else:
                e.pop("type", None)
            if self.el_contains.isChecked():
                e["match"] = "contains"
            else:
                e.pop("match", None)
            if self.el_index.value():
                e["index"] = self.el_index.value()
            else:
                e.pop("index", None)
            t["element"] = e
        if self.offset_on.isChecked():
            t["offset"] = self.offset.xy()
        else:
            t.pop("offset", None)
        return t

    # ------------------------------------------------------------ 이벤트
    def _emit(self, *_):
        if not self._loading:
            self._pending = False            # 값을 직접 넣었으면 정한 것으로 본다
            self.changed.emit()

    def _set_unset_item(self, on: bool):
        i = self.kind.findData("unset")
        self.kind.blockSignals(True)
        if on and i < 0:
            self.kind.insertItem(0, tr("정하기 전"), "unset")
        elif not on and i >= 0:
            self.kind.removeItem(i)
        self.kind.blockSignals(False)

    def _kind_changed(self, *_):
        k = self.kind.currentData()
        self.stack.setCurrentWidget(self.pages[k])
        self.offset_on.setVisible(k != "unset")
        if k != "unset" and not self._loading and self.kind.findData("unset") >= 0:
            # '정하기 전'에서 종류만 바꾼 것 → 값을 넣거나 화면에서 고르기 전까지는 아직 안 정한 것((0,0) 클릭 막기)
            self._pending = True
            self._set_unset_item(False)
        if not self._loading:
            self.changed.emit()

    def _go_kind(self, k: str):
        self._pending = False
        self._loading = True
        self.kind.setCurrentIndex(self.kind.findData(k))
        self.stack.setCurrentWidget(self.pages[k])
        self.offset_on.setVisible(True)
        self._set_unset_item(False)
        self._loading = False

    def _pick_from_unset(self):
        if not self._need_tools():
            return
        p = self.tools.pick_point()
        if p:
            self._go_kind("point")
            self.pt.set_xy(p)
            self._emit()

    def _cut_from_unset(self):
        if not self._need_tools():
            return
        res = self.tools.capture_template()
        if not res:
            return
        self._go_kind("image")
        self.img_path.setText(res["path"])
        if res.get("recommended_confidence"):
            self.img_conf.set_value(res["recommended_confidence"])
        if res.get("search_region"):
            self.img_region_on.setChecked(True)
            self.img_region.set_region(res["search_region"])
        self._emit()

    def _load_element(self, e: dict):
        self.el_name.setText(str(e.get("name") or ""))
        ty = e.get("type")
        i = self.el_type.findData(ty if ty and ty != "any" else "")
        if i < 0:                                        # 목록에 없는 종류도 잃지 않게
            self.el_type.addItem(str(ty), ty)
            i = self.el_type.count() - 1
        self.el_type.setCurrentIndex(i)
        self.el_contains.setChecked(e.get("match") == "contains")
        self.el_index.setValue(int(e.get("index") or 0))

    def _picked_element(self, res) -> bool:
        if res is None:
            return False
        if not res:
            QMessageBox.information(self, tr("화면에서 버튼 고르기"),
                                    tr("그 자리에서 이름 있는 버튼·입력칸을 찾지 못했어요.\n"
                                       "게임이나 그림으로 그린 화면이면 '그림으로 찾기'를 쓰세요."))
            return False
        self._loading = True
        self._load_element(res["target"]["element"])
        self._loading = False
        return True

    def _pick_element(self):
        if not self._need_tools():
            return
        if self._picked_element(self.tools.pick_element()):
            self._emit()

    def _pick_element_from_unset(self):
        if not self._need_tools():
            return
        res = self.tools.pick_element()
        if self._picked_element(res):
            self._go_kind("element")
            self._emit()

    def _on_image_path(self, *_):
        self._update_preview()
        self._emit()

    def _update_preview(self):
        from PySide6.QtGui import QPixmap
        from engine.real import IMAGE_ROOT
        p = self.img_path.text().strip()
        full = p if os.path.isabs(p) else os.path.join(IMAGE_ROOT, p)
        if p and os.path.exists(full):
            pm = QPixmap(full)
            if not pm.isNull():
                if pm.width() > 240 or pm.height() > 80:
                    pm = pm.scaled(240, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.img_preview.setPixmap(pm)
                self.img_preview.setVisible(True)
                return
        self.img_preview.setText(tr("(그림 없음)") if p else "")
        self.img_preview.setVisible(bool(p))           # 비어 있으면 빈 줄을 차지하지 않게

    def _browse_image(self):
        from engine.real import IMAGE_ROOT
        path, _ = QFileDialog.getOpenFileName(self, tr("이미지 고르기"), IMAGE_ROOT, tr("이미지 (*.png *.jpg *.bmp)"))
        if not path:
            return
        rel = os.path.relpath(path, IMAGE_ROOT)
        self.img_path.setText(path if rel.startswith("..") else rel.replace("\\", "/"))

    def _need_tools(self) -> bool:
        if self.tools is None:
            QMessageBox.information(self, tr("화면에서 고르기"), tr("이 화면에서는 쓸 수 없습니다."))
            return False
        return True

    def _capture_image(self):
        if not self._need_tools():
            return
        res = self.tools.capture_template()
        if not res:
            return
        self.img_path.setText(res["path"])
        if res.get("recommended_confidence"):
            self.img_conf.set_value(res["recommended_confidence"])
        if res.get("search_region"):
            self.img_region_on.setChecked(True)
            self.img_region.set_region(res["search_region"])
        self._emit()

    def _pick_point(self, xy: XYEdit):
        if not self._need_tools():
            return
        p = self.tools.pick_point()
        if p:
            xy.set_xy(p)
            self._emit()

    def _pick_region(self, reg: RegionEdit, enable: Optional[QCheckBox] = None):
        if not self._need_tools():
            return
        r = self.tools.pick_region()
        if r:
            reg.set_region(r)
            if enable is not None:
                enable.setChecked(True)
            self._emit()

    def _pick_color_at(self):
        if not self._need_tools():
            return
        res = self.tools.pick_color()
        if res:
            pos, rgb = res
            self.ca_at.set_xy(pos)
            self.ca_color.set_rgb(rgb)
            self._emit()

    def _pick_color_only(self, ce: ColorEdit):
        if not self._need_tools():
            return
        res = self.tools.pick_color()
        if res:
            ce.set_rgb(res[1])
            self._emit()

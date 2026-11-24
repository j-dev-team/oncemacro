"""
'환경 점검' 창(2026-11-17): 이 컴퓨터에 매크로 기능별로 필요한 것이 있는지 보여 주고, 없으면 무엇을 하면 되는지 알려 준다.
처음 켤 때 한 번(설정 'env_checked'), 그 뒤로는 설정 메뉴에서 연다.
점검은 빠른 것만(파일·등록 정보 확인). 프로그램을 실제로 켜 보지는 않는다.
"""
from __future__ import annotations

import ctypes
import os
from typing import List, Tuple

from gui.v2.i18n import tr

# (항목 이름, 됨?, 설명 또는 할 일, 꼭 필요?)
Check = Tuple[str, bool, str, bool]


def _progid_installed(progid: str) -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid + "\\CLSID"):
            return True
    except Exception:
        return False


def _can_import(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _writable(folder: str) -> bool:
    try:
        os.makedirs(folder, exist_ok=True)
        fp = os.path.join(folder, ".write_check.tmp")
        with open(fp, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(fp)
        return True
    except Exception:
        return False


def run_checks(macro_root: str = "") -> List[Check]:
    out: List[Check] = []
    if macro_root:
        ok = _writable(macro_root)
        out.append((tr("매크로 저장 폴더"), ok,
                    tr("매크로를 저장할 수 있습니다.") if ok else
                    tr("매크로 폴더에 쓸 수 없습니다. 프로그램을 쓰기 가능한 폴더(예: 문서 폴더)로 옮겨서 켜세요."), True))
    try:
        from engine.web import find_cli
        web_ok = bool(find_cli())
    except Exception:
        web_ok = False
    out.append((tr("웹 요소 스텝용 브라우저"), web_ok,
                tr("웹 페이지를 요소(버튼·입력칸)로 다룰 수 있습니다.") if web_ok else
                tr("웹 자동화 브라우저가 설치돼 있지 않습니다. 웹 요소 스텝만 못 쓰고 나머지 기능은 그대로 됩니다. "
                   "쓰려면 프로그램과 함께 받은 안내에 따라 웹 자동화 브라우저를 설치한 뒤 이 프로그램을 다시 켜세요."), False))
    com_ok = _can_import("win32com.client")
    out.append((tr("오피스 연결 부품"), com_ok,
                tr("엑셀·워드·한글 스텝을 쓸 수 있습니다(해당 프로그램이 깔려 있으면).") if com_ok else
                tr("오피스 연결 부품이 없어 엑셀·워드·한글 스텝을 못 씁니다. 프로그램을 다시 설치하세요."), False))
    for label, progid in ((tr("엑셀"), "Excel.Application"), (tr("워드"), "Word.Application"),
                          (tr("한글(한컴오피스)"), "HWPFrame.HwpObject")):
        ok = _progid_installed(progid)
        out.append((label, ok,
                    tr("설치돼 있습니다.") if ok else tr("설치돼 있지 않습니다. 이 프로그램을 다루는 스텝만 못 씁니다."), False))
    if _progid_installed("HWPFrame.HwpObject"):     # 한글이 있을 때만: 보안 승인 모듈(없으면 파일 열 때마다 확인 창)
        try:
            from engine.office import hwp_security_ready
            sec_ok = hwp_security_ready()
        except Exception:
            sec_ok = False
        out.append((tr("한글 자동 승인"), sec_ok,
                    tr("한글 파일을 확인 창 없이 열 수 있습니다.") if sec_ok else
                    tr("한글 자동화를 쓰려면 한 번 설정이 필요해요. 도움말 → '한글 자동화 설정'을 보세요. "
                       "설정 전에는 한글 단계를 돌릴 때 확인 창을 직접 눌러야 합니다."), False))
    from engine.win_background import bg_standard_available
    bg_ok = bg_standard_available()
    out.append((tr("뒤에서 실행"), bg_ok,
                tr("가려진 창에도 클릭·키 입력을 보낼 수 있습니다.") if bg_ok else
                tr("이 판에는 '뒤에서 실행' 기본 방식이 없습니다. '호환 모드'는 됩니다."), False))
    try:
        from engine.rescue import CliAI, load_ai_config
        ai_ok = CliAI(load_ai_config(macro_root) if macro_root else {}).available()
    except Exception:
        ai_ok = False
    out.append((tr("AI 도우미(막힘 해결)"), ai_ok,
                tr("이 컴퓨터의 AI 프로그램을 찾았습니다. '막히면 AI 한 번 부르기'를 켜면 쓸 수 있습니다.") if ai_ok else
                tr("이 컴퓨터에서 AI 프로그램을 찾지 못했습니다. '막히면 AI 한 번 부르기'만 못 쓰고 나머지는 그대로 됩니다."), False))
    admin = _is_admin()
    out.append((tr("관리자 권한"), True,
                tr("관리자 권한으로 켜져 있습니다.") if admin else
                tr("일반 권한으로 켜져 있습니다. 관리자 권한으로 도는 프로그램을 다루려면 이 프로그램도 관리자 권한으로 켜야 합니다."),
                False))
    return out


def summary(checks: List[Check]) -> str:
    bad = [c for c in checks if not c[1]]
    if not bad:
        return tr("모든 항목이 준비됐습니다.")
    if any(c[3] for c in bad):
        return tr("꼭 필요한 항목이 빠졌습니다. 아래 안내대로 고친 뒤 다시 켜세요.")
    return tr("기본 기능은 됩니다. 빠진 항목은 그 기능만 못 씁니다.")


def show_dialog(parent=None, macro_root: str = "", modal: bool = True):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout)
    checks = run_checks(macro_root)
    d = QDialog(parent)
    d.setWindowTitle(tr("환경 점검"))
    d.resize(720, 420)
    v = QVBoxLayout(d)
    top = QLabel("<b>" + summary(checks) + "</b>")
    top.setWordWrap(True)
    v.addWidget(top)
    tbl = QTableWidget(len(checks), 3)
    tbl.setHorizontalHeaderLabels([tr("항목"), tr("상태"), tr("설명")])
    tbl.verticalHeader().setVisible(False)
    tbl.setEditTriggers(QTableWidget.NoEditTriggers)
    tbl.setWordWrap(True)
    for r, (name, ok, text, _need) in enumerate(checks):
        tbl.setItem(r, 0, QTableWidgetItem(name))
        st = QTableWidgetItem(tr("준비됨") if ok else tr("빠짐"))
        from .design import theme as _th
        from PySide6.QtGui import QColor
        st.setForeground(QColor(_th.current().get("ok" if ok else "bad", "#2e7d32" if ok else "#c62828")))
        tbl.setItem(r, 1, st)
        tbl.setItem(r, 2, QTableWidgetItem(text))
    h = tbl.horizontalHeader()
    h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
    h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
    h.setSectionResizeMode(2, QHeaderView.Stretch)
    tbl.resizeRowsToContents()
    v.addWidget(tbl, 1)
    note = QLabel(tr("이 창은 설정 메뉴 → '환경 점검'에서 다시 열 수 있습니다."))
    from .design import theme as _th2
    note.setStyleSheet("color:%s" % _th2.current().get("muted", "#666"))
    v.addWidget(note)
    bb = QDialogButtonBox(QDialogButtonBox.Close)
    bb.rejected.connect(d.reject)
    v.addWidget(bb)
    if modal:
        d.exec()
    else:
        d.setAttribute(Qt.WA_DeleteOnClose)
        d.show()
    return d

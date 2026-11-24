"""예기치 못한 오류를 사람이 읽을 수 있게: 쉬운 말 한 줄 + '자세히'(접힘) + 기록 파일(logs/오류/날짜.log).
개발자 글(Traceback)은 처음부터 보이지 않고 '자세히'를 눌러야 보인다."""
from __future__ import annotations

import os
import sys
import time
import traceback
from typing import Optional


def log_dir() -> str:
    try:
        from engine.real import PROJECT_ROOT
        root = PROJECT_ROOT
    except Exception:
        root = os.getcwd()
    from engine.fsnames import pick
    return pick(os.path.join(root, "logs"), "오류")          # 11-24: 새로는 logs/errors(예전 logs/오류 가 있으면 그대로)


def write_log(text: str) -> Optional[str]:
    try:
        d = log_dir()
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, time.strftime("%Y%m%d") + ".log")
        with open(p, "a", encoding="utf-8") as f:
            f.write(time.strftime("=== %Y-%m-%d %H:%M:%S ===\n") + text + "\n")
        return p
    except OSError:
        return None


def plain_reason(exctype, value) -> str:
    """오류 종류 → 쉬운 말 한 줄."""
    from gui.v2.i18n import tr
    if exctype in (ModuleNotFoundError, ImportError):
        return tr("이 기능에 필요한 부품이 프로그램 안에 빠져 있어요. 프로그램을 새 판으로 바꾸면 고쳐집니다.")
    if exctype in (FileNotFoundError, PermissionError):
        return tr("파일을 열거나 저장하지 못했어요(파일이 없거나 쓸 수 없는 곳).")
    return tr("예상하지 못한 문제가 생겼어요.")


def show_unexpected(exctype, value, tb, parent=None, exec_box: bool = True):
    """sys.excepthook 용. 돌려줌: 만든 대화상자(시험에서 내용 확인용)."""
    from PySide6.QtWidgets import QMessageBox
    from gui.v2.i18n import tr
    detail = "".join(traceback.format_exception(exctype, value, tb))
    print(detail, file=sys.stderr)
    path = write_log(detail)
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(tr("문제가 생겼어요"))
    box.setText(plain_reason(exctype, value))
    box.setInformativeText(tr("하던 일은 그대로 두었어요. 계속 쓰셔도 됩니다.")
                           + ("\n" + tr("기록: {path}").format(path=path) if path else ""))
    box.setDetailedText(detail)                 # '자세히 보기'를 눌러야 펼쳐짐
    if exec_box:
        box.exec()
    return box

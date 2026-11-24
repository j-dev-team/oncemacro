"""문제·의견 보내기(11-24): 쓰는 사람이 직접 누를 때만, 보낼 묶음을 이 PC 에 만들고 보낼 곳을 열어 준다.

자동으로 아무것도 보내지 않는다. 묶음은 logs/feedback/ 에 남고, 사람이 내용을 보고 직접 올린다.
기본으로 넣는 것: 판 정보·윈도우 판, 자체 점검 결과, 최근 오류 기록 끝부분, 최근 실행 결과 요약(성공/실패/멈춘 자리),
                  스스로 고치기(헛돎) 하루 집계.  화면 사진·매크로 내용은 사람이 고를 때만 넣는다.
"""
from __future__ import annotations

import glob
import json
import os
import platform
import time
import zipfile
from typing import Optional

FEEDBACK_URL = "https://github.com/j-dev-team/oncemacro/issues/new/choose"     # 11-24 공개 저장소(이슈 양식 고르기)


def _root() -> str:
    from engine.real import PROJECT_ROOT
    return PROJECT_ROOT


def _tail(path: str, n: int = 200) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-n:])
    except OSError:
        return ""


def _run_summaries(root: str, k: int = 8) -> list:
    out = []
    for f in sorted(glob.glob(os.path.join(root, "logs", "runs", "*.jsonl")), key=os.path.getmtime)[-k:]:
        end = None
        try:
            for line in open(f, encoding="utf-8", errors="replace"):
                if '"run_end"' in line and '"depth": 0' in line:
                    end = json.loads(line)
        except (OSError, ValueError):
            continue
        r = (end or {}).get("result") or {}
        out.append({"file": os.path.basename(f), "status": r.get("status", "?"),
                    "seconds": round(float(r.get("duration") or 0), 1),
                    "error": ((r.get("error") or {}).get("reason") or "")[:200],
                    "where": (r.get("error") or {}).get("path")})
    return out


def make_report(root: Optional[str] = None, include_screens: bool = False, include_macros: bool = False,
                note: str = "") -> str:
    """묶음(zip) 경로. 사람이 고른 것만 넣는다."""
    root = root or _root()
    d = os.path.join(root, "logs", "feedback")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, time.strftime("feedback_%Y%m%d_%H%M%S.zip"))
    info = {"made": time.strftime("%Y-%m-%d %H:%M:%S"), "os": platform.platform(), "note": note}
    try:
        from . import build_info
        info["build"] = build_info.info()
    except Exception:
        pass
    try:
        from engine.selfheal import day_counts
        info["unstick_today"] = day_counts(time.strftime("%Y-%m-%d"), os.path.join(root, "logs", "selfheal"))
    except Exception:
        pass
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("info.json", json.dumps(info, ensure_ascii=False, indent=1))
        z.writestr("recent_runs.json", json.dumps(_run_summaries(root), ensure_ascii=False, indent=1))
        from engine.fsnames import both
        for d in both(os.path.join(root, "logs"), "시험")[-1:]:
            st = os.path.join(d, "selftest.txt")
            if os.path.exists(st):
                z.write(st, "selftest.txt")
        logs_ = [f for d in both(os.path.join(root, "logs"), "오류") for f in glob.glob(os.path.join(d, "*.log"))]
        for f in sorted(logs_, key=os.path.getmtime)[-5:]:
            z.writestr("errors/" + os.path.basename(f), _tail(f))
        ev = sorted(glob.glob(os.path.join(root, "logs", "selfheal", "evidence", "*")))[-3:]
        for e in ev:
            for name in ("info.json", "recent.jsonl"):
                p = os.path.join(e, name)
                if os.path.exists(p):
                    z.write(p, f"unstick/{os.path.basename(e)}/{name}")
            if include_screens and os.path.exists(os.path.join(e, "screen.png")):
                z.write(os.path.join(e, "screen.png"), f"unstick/{os.path.basename(e)}/screen.png")
        if include_macros:
            for f in glob.glob(os.path.join(root, "macros_v2", "*.json")):
                if not os.path.basename(f).startswith("_"):
                    z.write(f, "macros/" + os.path.basename(f))
    return path


def show_dialog(parent) -> None:
    """무엇이 들어가는지 보여 주고, 사람이 '묶음 만들기'를 누르면 만들고 폴더·보낼 곳을 연다."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout)
    from gui.v2.i18n import tr
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("문제·의견 보내기"))
    lay = QVBoxLayout(dlg)
    lay.addWidget(QLabel(tr("보낼 묶음을 이 PC 에 만들고, 올릴 곳을 열어 드려요. 자동으로 보내는 것은 없어요.\n"
                            "기본으로 들어가는 것: 판 정보·윈도우 판, 자체 점검 결과, 최근 오류·실행 결과 요약, 헛돎 집계.")))
    note = QPlainTextEdit()
    note.setPlaceholderText(tr("무슨 일이 있었는지 한두 줄(선택)"))
    note.setMaximumHeight(80)
    lay.addWidget(note)
    screens = QCheckBox(tr("막혔던 순간의 화면 사진도 넣기(화면에 개인 정보가 있으면 넣지 마세요)"))
    macros = QCheckBox(tr("내 매크로 파일도 넣기"))
    lay.addWidget(screens)
    lay.addWidget(macros)
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.button(QDialogButtonBox.Ok).setText(tr("묶음 만들기"))
    lay.addWidget(bb)
    bb.rejected.connect(dlg.reject)

    def ok():
        p = make_report(include_screens=screens.isChecked(), include_macros=macros.isChecked(),
                        note=note.toPlainText().strip())
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(p)))
        QDesktopServices.openUrl(QUrl(FEEDBACK_URL))
        dlg.accept()
    bb.accepted.connect(ok)
    dlg.exec()

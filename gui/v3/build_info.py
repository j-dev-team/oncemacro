"""이 프로그램의 판: 묶음을 만들 때 넣은 build_info.json(만든 시각·저장소 판 번호). 파이썬으로 돌리면 '개발 중'."""
import json
import os
import sys

from gui.v2.i18n import tr


def info() -> dict:
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        with open(os.path.join(here, "build_info.json"), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d["frozen"] = bool(getattr(sys, "frozen", False))
    d["exe"] = sys.executable if d["frozen"] else ""
    return d


def short() -> str:
    d = info()
    if not d.get("built"):
        return tr("개발 중(파이썬으로 실행)")
    return tr("{built} 만든 판 ({rev})").format(built=d["built"], rev=d.get("rev") or "-")


def text() -> str:
    d = info()
    lines = [tr("원스매크로"), tr("판: ") + short()]
    if d.get("exe"):
        lines.append(tr("실행 파일: ") + d["exe"])
    return "\n".join(lines)

"""
예약 실행(2026-11-17): 이 프로그램이 켜져 있는 동안 정해진 시각(매일)이나 간격(N분마다)으로 매크로를 실행.
윈도 작업 스케줄러·자동 시작 등록은 하지 않는다(프로그램을 꺼 두면 예약도 안 돎).
목록은 macros_v2/_예약.json 에 저장.
"""
from __future__ import annotations

import json
import os
import time
from typing import List, Optional

from .i18n import tr

FILE_NAME = "_예약.json"


def _fp(root: str) -> str:
    from engine.fsnames import pick
    return pick(root, FILE_NAME)          # 11-24: 새로는 _schedule.json(예전 _예약.json 이 있으면 그대로)


def load(root: str) -> List[dict]:
    fp = _fp(root)
    try:
        with open(fp, encoding="utf-8") as fh:
            data = json.load(fh)
        return [d for d in data if isinstance(d, dict) and d.get("macro")]
    except Exception:
        return []


def save(root: str, items: List[dict]) -> None:
    fp = _fp(root)
    tmp = fp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(items, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, fp)


def due(item: dict, now: Optional[float] = None) -> bool:
    """지금 실행할 차례인지. item: {macro, mode: 'daily'|'every', time: 'HH:MM', minutes: N, on, last}."""
    if not item.get("on", True):
        return False
    now = time.time() if now is None else now
    last = float(item.get("last") or 0)
    if item.get("mode") == "every":
        mins = max(1, int(item.get("minutes") or 60))
        return now - last >= mins * 60
    hhmm = str(item.get("time") or "09:00")
    try:
        h, m = (int(x) for x in hhmm.split(":"))
    except ValueError:
        return False
    lt = time.localtime(now)
    target = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, m, 0, 0, 0, -1))
    return target <= now < target + 600 and last < target       # 그 시각부터 10분 안에, 오늘 아직 안 돌았으면


def describe(item: dict) -> str:
    when = (tr("{n}분마다").format(n=item.get('minutes', 60)) if item.get("mode") == "every"
            else tr("매일 {t}").format(t=item.get('time', '09:00')))
    last = item.get("last")
    ls = time.strftime("%m-%d %H:%M", time.localtime(last)) if last else tr("아직 안 돎")
    return "{} · {} · {} ({})".format(tr('켜짐') if item.get('on', True) else tr('꺼짐'), when, item.get('macro'),
                                      tr("마지막 {t}").format(t=ls))

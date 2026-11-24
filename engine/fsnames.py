"""프로그램이 만드는 폴더·파일 이름(11-24).

배포판(전 세계 사용자)은 영어 이름으로 만든다. 예전 판이 만든 한국어 이름 폴더·파일이 이미 있으면
그것을 계속 쓴다(이 컴퓨터처럼 오래 쓴 곳이 깨지지 않게). 읽을 때는 두 이름을 다 본다.
"""
from __future__ import annotations

import glob
import os
from typing import List

# 한국어(예전) → 영어(새)
NAMES = {
    "_고침": "_fixes",
    "오류": "errors",
    "시험": "selftest",
    "임시": "tmp",
    "_예약.json": "_schedule.json",
    "설정.json": "settings.json",
}


def pick(parent: str, ko: str) -> str:
    """parent 안의 이름: 한국어 이름이 이미 있으면 그대로, 없으면 영어 이름. 전체 경로를 돌려준다."""
    en = NAMES.get(ko, ko)
    if os.path.exists(os.path.join(parent, ko)):
        return os.path.join(parent, ko)
    return os.path.join(parent, en)


def both(parent: str, ko: str) -> List[str]:
    """읽을 때 볼 경로들(있는 것만, 한국어 먼저)."""
    out = []
    for n in (ko, NAMES.get(ko, ko)):
        p = os.path.join(parent, n)
        if os.path.exists(p) and p not in out:
            out.append(p)
    return out


def glob_both(parent: str, ko_dir: str, patterns: List[str]) -> List[str]:
    """두 이름의 폴더에서 여러 무늬로 찾기(겹치면 한 번만)."""
    out: List[str] = []
    for d in {os.path.join(parent, ko_dir), os.path.join(parent, NAMES.get(ko_dir, ko_dir))}:
        for pat in patterns:
            for f in glob.glob(os.path.join(d, pat)):
                if f not in out:
                    out.append(f)
    return sorted(out)

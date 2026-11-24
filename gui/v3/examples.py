"""처음 쓰는 사람용 예시 매크로 넣기(Qt 없음).

- 틀: gui/v3/example_data/macros.json(경로는 '@DATA@'), 자료: gui/v3/example_data/자료/(한국어)·data/(영어)
  영어 화면이면 steps_en(영어 변수·시트·파일 이름)을 쓰고, langs 가 정해진 예시(한글 문서)는 그 언어에서만 넣는다(11-24).
- 넣기: 자료를 <자료 폴더>/예시/자료 로 복사(이미 있는 파일은 그대로), 출력 폴더를 만들고,
  '@DATA@' 를 그 컴퓨터의 실제 경로로 바꿔 '예시' 묶음에 매크로를 만든다.
- 이미 같은 이름의 매크로가 있으면 건드리지 않고 건너뛴다. 사용자가 누를 때만 한다.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
from typing import Callable, Dict, List, Optional

from gui.v2.i18n import current, tr

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "example_data")
TOKEN = "@DATA@"


def templates(lang: Optional[str] = None) -> List[dict]:
    """lang 을 주면 그 언어에서 넣을 예시만."""
    with open(os.path.join(HERE, "macros.json"), encoding="utf-8") as fh:
        out = json.load(fh)["examples"]
    return [t for t in out if not lang or lang in (t.get("langs") or [lang])]


def _names(lang: str) -> tuple:
    """(자료 원본 폴더, 넣을 자료 폴더 이름, 출력 폴더 이름)."""
    return ("자료", "자료", "출력") if lang == "ko" else ("data", "data", "output")


def _swap(o, base: str):
    if isinstance(o, dict):
        return {k: _swap(v, base) for k, v in o.items()}
    if isinstance(o, list):
        return [_swap(v, base) for v in o]
    if isinstance(o, str) and TOKEN in o:
        return o.replace(TOKEN, base)
    return o


def _pick(d, lang: str) -> str:
    return d.get(lang) or d.get("en") or next(iter(d.values()))


def group_name() -> str:
    return tr("예시")


def example_dir(root: str) -> str:
    return os.path.join(root, tr("예시") if current() == "ko" else "examples")


def build(tpl: dict, base: str, lang: Optional[str] = None) -> dict:
    lang = lang or current()
    return {"version": 2, "name": _pick(tpl["name"], lang), "description": _pick(tpl["description"], lang),
            "repeat": {"times": 1},
            "steps": _swap(copy.deepcopy(tpl.get("steps_" + lang) or tpl["steps"]), base)}


def install(store, root: str, has_program: Optional[Callable[[str], bool]] = None) -> Dict[str, list]:
    """예시를 넣는다. 돌려줌: {"made": [이름], "skipped": [이름], "missing": [(이름, 필요한 것)], "folder": 경로}."""
    lang = current()
    base = example_dir(root)
    s_name, d_name, o_name = _names(lang)
    src = os.path.join(HERE, s_name)
    dst = os.path.join(base, d_name)
    os.makedirs(dst, exist_ok=True)
    os.makedirs(os.path.join(base, o_name), exist_ok=True)
    for fn in os.listdir(src):
        to = os.path.join(dst, fn)
        if not os.path.exists(to):
            shutil.copy2(os.path.join(src, fn), to)
    names = set(store.names())
    out = {"made": [], "skipped": [], "missing": [], "folder": base}
    for tpl in templates(lang):
        m = build(tpl, base, lang)
        if m["name"] in names:
            out["skipped"].append(m["name"])
            continue
        store.add(m, group=group_name())
        out["made"].append(m["name"])
        lack = [k for k in tpl.get("needs") or [] if has_program is not None and not has_program(k)]
        if lack:
            out["missing"].append((m["name"], lack))
    return out


PROGIDS = {"excel": "Excel.Application", "hwp": "HWPFrame.HwpObject", "word": "Word.Application"}


def program_installed(kind: str) -> bool:
    """엑셀·한글이 깔려 있는지(레지스트리에 등록 이름이 있는지만 본다. 켜지 않음)."""
    progid = PROGIDS.get(kind)
    if not progid:
        return True
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid + "\\CLSID"))
        return True
    except Exception:
        return False


def program_label(kind: str) -> str:
    return {"excel": tr("엑셀"), "hwp": tr("한글(한컴오피스)"), "word": tr("워드")}.get(kind, kind)

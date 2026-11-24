"""화면 번역 검사: gui/v3 에서 tr("...") 로 쓴 글이 영어 사전에 다 있고, 자리표시가 같고, 영어 값에 한글이 없는지."""
import ast
import glob
import json
import os
import re
import string

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KO = re.compile(r"[가-힣]")


def _keys():
    out = {}
    for fp in glob.glob(os.path.join(ROOT, "gui", "v3", "**", "*.py"), recursive=True):
        tree = ast.parse(open(fp, encoding="utf-8").read())
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "tr"
                    and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)
                    and KO.search(n.args[0].value)):
                out[n.args[0].value] = f"{os.path.relpath(fp, ROOT)}:{n.lineno}"
    return out


def _dict():
    d = {}
    for fp in sorted(glob.glob(os.path.join(ROOT, "gui", "v2", "lang", "en", "*.json")) + glob.glob(os.path.join(ROOT, "gui", "v3", "lang", "en", "*.json"))):
        with open(fp, encoding="utf-8") as fh:
            d.update(json.load(fh))
    return d


def _fields(s):
    try:
        return sorted({f for _, f, _, _ in string.Formatter().parse(s) if f})
    except ValueError:
        return ["<깨진 자리표시>"]


def test_all_tr_keys_translated():
    d = _dict()
    missing = [f"{w}: {k}" for k, w in _keys().items() if k not in d]
    assert not missing, "영어 사전에 없음:\n" + "\n".join(missing)


def test_placeholders_match():
    d = _dict()
    # {변수}·B{행} 처럼 한글이 든 중괄호는 자리표시가 아니라 보여 주는 예시 글
    bad = [k for k in _keys() if k in d and not any(KO.search(f) for f in _fields(k))
           and _fields(k) != _fields(d[k])]
    assert not bad, "자리표시가 다름:\n" + "\n".join(bad)


def test_english_values_have_no_korean():
    bad = [k for k, v in _dict().items() if KO.search(v)]
    assert not bad, "영어 값에 한글:\n" + "\n".join(bad)

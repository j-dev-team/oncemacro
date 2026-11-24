"""엔진 글 번역 검사: t("...") 로 쓴 열쇠가 영어 사전에 다 있고 자리표시가 같은지, 영어 값에 한글이 없는지."""
import ast
import glob
import json
import os
import re
import string

import pytest

from engine import i18n

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KO = re.compile(r"[가-힣]")


def _keys():
    out = {}
    for fp in glob.glob(os.path.join(ROOT, "engine", "*.py")):
        tree = ast.parse(open(fp, encoding="utf-8").read())
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "t"
                    and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)):
                out[n.args[0].value] = f"{os.path.basename(fp)}:{n.lineno}"
    return out


def _fields(s):
    return sorted({f for _, f, _, _ in string.Formatter().parse(s) if f})


def _dict():
    d = {}
    for fp in sorted(glob.glob(os.path.join(ROOT, "engine", "lang", "en", "*.json"))):
        with open(fp, encoding="utf-8") as fh:
            d.update(json.load(fh))
    return d


def test_all_keys_translated():
    d = _dict()
    keys = _keys()
    assert keys, "t() 를 쓰는 곳이 없음"
    missing = [f"{where}: {k}" for k, where in keys.items() if k not in d]
    assert not missing, "영어 사전에 없음:\n" + "\n".join(missing)


def test_placeholders_match():
    d = _dict()
    bad = [k for k in _keys() if k in d and _fields(k) != _fields(d[k])]
    assert not bad, "자리표시가 다름:\n" + "\n".join(bad)


def test_english_values_have_no_korean():
    bad = [k for k, v in _dict().items() if KO.search(v)]
    assert not bad, "영어 값에 한글:\n" + "\n".join(bad)


def test_switch_language():
    try:
        i18n.set_language("en")
        assert i18n.t("변수 '{name}'가 없음 (remember 나 이미지 클릭 전에 썼는지 확인)", name="a") != \
            "변수 'a'가 없음 (remember 나 이미지 클릭 전에 썼는지 확인)"
        i18n.set_language("ko")
        assert i18n.t("변수 '{name}'가 없음 (remember 나 이미지 클릭 전에 썼는지 확인)", name="a") == \
            "변수 'a'가 없음 (remember 나 이미지 클릭 전에 썼는지 확인)"
    finally:
        i18n.set_language("ko")

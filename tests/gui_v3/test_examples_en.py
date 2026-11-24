"""영어 화면의 예시 넣기(11-24): 영어 사용자는 매크로·변수·시트·파일·폴더 이름까지 영어로만 본다."""
import json
import os
import re
import zipfile

import pytest

from engine.model import validate_macro
from gui.v2 import i18n
from gui.v2.store import MacroStore
from gui.v3 import examples as ex

KO = re.compile(r"[가-힣]")


@pytest.fixture
def english():
    before = i18n.current()
    i18n.set_language("en")
    yield
    i18n.set_language(before)


def test_english_examples_have_no_korean(english, tmp_path):
    store = MacroStore(str(tmp_path / "macros_v2"))
    res = ex.install(store, str(tmp_path), lambda k: True)
    assert len(res["made"]) == 2                                   # 한글(HWP) 예시는 한국어에서만
    assert not KO.search(res["folder"]) and res["folder"].endswith("examples")
    for name in res["made"]:
        m = store.load(name)
        assert validate_macro(m) == []
        assert not KO.search(json.dumps(m, ensure_ascii=False)), name
    assert not KO.search(ex.group_name())
    for dirpath, dirs, files in os.walk(res["folder"]):
        for n in dirs + files:
            assert not KO.search(n), n


def test_english_example_data_files_have_no_korean_or_personal_info():
    d = os.path.join(os.path.dirname(ex.HERE), "example_data", "data")
    files = os.listdir(d)
    assert len(files) == 6
    for fn in files:
        with zipfile.ZipFile(os.path.join(d, fn)) as z:
            for n in z.namelist():
                t = z.read(n).decode("utf-8", "replace")
                assert not KO.search(t), (fn, n)
                assert "absPath" not in t and "<dc:creator>" not in t.replace("<dc:creator></dc:creator>", ""), (fn, n)


def test_english_excel_example_reads_the_english_files():
    tpl = [t for t in ex.templates("en") if t["key"] == "excel"][0]
    s = json.dumps(ex.build(tpl, r"C:\x\examples", "en"))
    for fn in os.listdir(os.path.join(ex.HERE, "data")):
        assert fn in s


def test_example_data_has_no_local_user_name():
    """예시 자료(양쪽 언어)에 만든 컴퓨터의 사용자 이름·폴더 경로가 남지 않음(배포판에 딸려 감)."""
    import getpass
    user = getpass.getuser()
    for dirpath, _d, files in os.walk(ex.HERE):
        for fn in files:
            raw = open(os.path.join(dirpath, fn), "rb").read()
            blobs = [raw]
            if fn.endswith(".xlsx"):
                with zipfile.ZipFile(os.path.join(dirpath, fn)) as z:
                    blobs += [z.read(n) for n in z.namelist()]
            for b in blobs:
                for w in (user, "python\\macro"):
                    assert w.encode("utf-8") not in b and w.encode("utf-16-le") not in b, (fn, w)

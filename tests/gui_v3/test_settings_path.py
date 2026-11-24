"""폴더형 실행 묶음: 설정은 자료 폴더의 파일에 저장, 처음 한 번 기존 설정을 옮겨 옴."""
import os

from PySide6 import QtCore

from gui.v2 import settings_path as sp


def test_default_is_native(monkeypatch):
    monkeypatch.delenv("MACRO_SETTINGS_DIR", raising=False)
    assert sp.settings_dir() is None            # 파이썬으로 실행하면 예전처럼


def test_ini_in_data_folder_and_migrates(monkeypatch, tmp_path):
    app = "시험_설정_옮김"
    old = QtCore.QSettings(sp.ORG, app)              # 예전 저장소에 값 하나
    old.setValue("lang", "en")
    old.sync()
    try:
        monkeypatch.setenv("MACRO_SETTINGS_DIR", str(tmp_path / "설정 폴더"))
        s = sp.open_settings(QtCore, app)
        path = sp.ini_path(app)
        assert os.path.exists(path) and path.startswith(str(tmp_path))
        assert s.value("lang") == "en"                 # 옮겨 옴
        s.setValue("theme", "dark")
        s.sync()
        old.setValue("lang", "ko")                     # 그 뒤 예전 저장소가 바뀌어도 다시 안 덮음
        old.sync()
        s2 = sp.open_settings(QtCore, app)
        assert s2.value("lang") == "en" and s2.value("theme") == "dark"
    finally:
        old.clear()
        old.sync()


def test_frozen_folder_bundle_uses_data_root(monkeypatch, tmp_path):
    monkeypatch.delenv("MACRO_SETTINGS_DIR", raising=False)
    prog = tmp_path / "매크로" / "프로그램"
    (prog / "_internal").mkdir(parents=True)
    monkeypatch.setattr(sp.sys, "frozen", True, raising=False)
    monkeypatch.setattr(sp.sys, "executable", str(prog / "MacroManager.exe"))
    import engine.real as real
    monkeypatch.setattr(real, "PROJECT_ROOT", str(tmp_path / "매크로"))
    assert sp.settings_dir() == os.path.join(str(tmp_path / "매크로"), "settings")


def test_data_writable(tmp_path):
    assert sp.data_writable(str(tmp_path / "자료 폴더"))
    blocked = tmp_path / "막힘"
    blocked.mkdir()
    (blocked / "logs").write_text("파일이라 폴더를 못 만듦", encoding="utf-8")   # 쓰기 막힌 곳 흉내
    assert not sp.data_writable(str(blocked))

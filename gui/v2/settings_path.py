"""화면 설정(언어·테마·창 크기 등)을 어디에 저장할지 (Qt 묶음 상관없이 v2·v3 공용).
- 폴더형 실행 묶음(실행 파일 옆에 _internal)이면 자료 폴더의 settings\\MacroManager\\<이름>.ini
  → 폴더째 옮기거나 지우면 설정도 같이 따라가고, 윈도우 레지스트리에 흔적을 안 남긴다.
- 환경변수 MACRO_SETTINGS_DIR 가 있으면 그 폴더(시험용).
- 그 밖(파이썬으로 실행, 예전 한 파일 실행 파일)은 지금처럼 윈도우 기본 저장소(레지스트리)."""
from __future__ import annotations

import os
import sys
from typing import Optional

ORG = "MacroManager"


def settings_dir() -> Optional[str]:
    env = os.environ.get("MACRO_SETTINGS_DIR")
    if env:
        return os.path.abspath(env)
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        if os.path.isdir(os.path.join(exe_dir, "_internal")):
            from engine.real import PROJECT_ROOT
            return os.path.join(PROJECT_ROOT, "settings")
    return None


def data_writable(root: Optional[str] = None) -> bool:
    """자료 폴더에 쓸 수 있는지(Program Files 처럼 관리자만 쓰는 곳에 풀면 False)."""
    if root is None:
        from engine.real import PROJECT_ROOT
        root = PROJECT_ROOT
    probe = os.path.join(root, "logs", ".write_test")
    try:
        os.makedirs(os.path.dirname(probe), exist_ok=True)
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def ini_path(app: str) -> Optional[str]:
    d = settings_dir()
    return os.path.join(d, ORG, app + ".ini") if d else None


def open_settings(qt_core, app: str):
    """qt_core: PySide6.QtCore 또는 PyQt5.QtCore 모듈. 설정 파일 쪽이면 처음 한 번 기존 설정을 옮겨 온다."""
    QSettings = qt_core.QSettings
    path = ini_path(app)
    if not path:
        return QSettings(ORG, app)
    fresh = not os.path.exists(path)
    s = QSettings(path, QSettings.IniFormat)
    if fresh:
        try:
            old = QSettings(ORG, app)
            for k in old.allKeys():
                s.setValue(k, old.value(k))
            s.sync()
        except Exception:
            pass
    return s

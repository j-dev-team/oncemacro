"""
실제 백엔드를 묶어서 Runner 를 만드는 도우미 (CLI·MCP·GUI 공용).
"""
from __future__ import annotations

import os
import sys
from typing import Callable, Optional

from .library import FileLibrary
from .model import DEFAULT_SETTINGS
from .runner import Runner
from .win_input import make_input
from .win_vision import MssVision
from .win_window import set_dpi_awareness, window_factory



def _project_root() -> str:
    """macros_v2·image·logs 가 있는 폴더.
    - 환경변수 MACRO_ROOT_DIR 이 있으면 그 폴더
    - 실행 파일(PyInstaller)로 실행하면 실행 파일 옆 → 그 위 폴더 순서로 macros_v2 가 있는 곳
    - 그 밖에는 이 파일의 위 폴더(프로젝트 폴더)"""
    env = os.environ.get("MACRO_ROOT_DIR")
    if env:
        return os.path.abspath(env)
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        for cand in (exe_dir, os.path.dirname(exe_dir)):
            if os.path.isdir(os.path.join(cand, "macros_v2")):
                return cand
        if os.path.isdir(os.path.join(exe_dir, "_internal")):
            # 폴더형 묶음: 자료는 프로그램 폴더 밖(위 폴더)에 → 프로그램 폴더만 바꿔 끼워도 자료가 남는다
            return os.path.dirname(exe_dir)
        return exe_dir
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


PROJECT_ROOT = _project_root()
IMAGE_ROOT = os.path.join(PROJECT_ROOT, "image")
MACRO_ROOT = os.path.join(PROJECT_ROOT, "macros_v2")
TRACE_ROOT = os.path.join(PROJECT_ROOT, "logs", "runs")


class RealEnv:
    def __init__(self, image_root: str = IMAGE_ROOT, macro_root: str = MACRO_ROOT):
        self.dpi = set_dpi_awareness()
        self.vision = MssVision(image_root)
        self.library = FileLibrary(macro_root)
        self._inputs = {}
        from .health import HealthRecorder
        self.health = HealthRecorder(os.path.join(PROJECT_ROOT, "logs", "health"),      # 건강 기록(AI 안 씀)
                                     os.path.join(PROJECT_ROOT, "logs", "repairs"))

    def input_for(self, backend: str):
        if backend not in self._inputs:
            self._inputs[backend] = make_input(backend)
        return self._inputs[backend]

    def runner(self, macro: dict, on_event: Optional[Callable[[dict], None]] = None) -> Runner:
        backend = macro.get("settings", {}).get("input_backend", DEFAULT_SETTINGS["input_backend"])
        return Runner(macro, vision=self.vision, input=self.input_for(backend),
                      library=self.library, window_factory=window_factory, on_event=on_event,
                      snapshot_dir=os.path.join(PROJECT_ROOT, "logs", "snapshots"),
                      rescuer=self.rescuer(), health=self.health)

    def rescuer(self):
        """막히면 AI 한 번 부르기: 명령줄 AI(매크로 폴더 _ai.json 설정, 없으면 자동으로 찾음)."""
        from .rescue import CliAI, Rescuer, load_ai_config
        img_root = self.vision.image_root if hasattr(self.vision, "image_root") else IMAGE_ROOT
        return Rescuer(os.path.join(PROJECT_ROOT, "logs", "ai_rescue"),
                       ai=CliAI(load_ai_config(self.library.root)), library=self.library,
                       image_exists=lambda p: os.path.exists(p) or os.path.exists(os.path.join(img_root, p)))

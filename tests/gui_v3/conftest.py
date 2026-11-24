import os
os.environ.setdefault("MACRO_NO_GUARD", "1")    # 지킴이 상태 파일을 진짜 자료 폴더에 쓰지 않게
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["MACRO_LANG"] = "ko"          # 시험은 한국어 화면 기준(사용자 설정 언어와 상관없이)

import tempfile  # noqa: E402

from PySide6.QtCore import QSettings  # noqa: E402

# 시험이 사용자 컴퓨터의 프로그램 설정(레지스트리)을 바꾸지 않게, 설정을 임시 폴더의 파일로
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp(prefix="macro_test_settings_"))

import pytest
from PySide6.QtWidgets import QApplication

from engine import Runner
from engine.backends import FakeClock, FakeInput, FakeVision, FakeWindow
from engine.library import DictLibrary


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _flush_deferred_deletes():
    """시험에는 이벤트 루프가 없어 deleteLater 한 창·위젯이 안 지워지고 쌓인다(PySide6). 시험마다 비운다."""
    yield
    from PySide6.QtCore import QCoreApplication, QEvent
    if QCoreApplication.instance() is not None:
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


class YieldingClock(FakeClock):
    """가짜 시계인데 잠깐씩 실제로 쉬어 다른 스레드(화면)에 차례를 준다.
    PySide6 는 신호를 보낼 때 PyQt5 처럼 차례를 넘기지 않아, 가짜 시간이 한도까지 혼자 달려 버리는 것을 막는다."""

    def sleep(self, seconds, stop):
        time.sleep(0.001)
        return super().sleep(seconds, stop)


class FakeEnv:
    """가짜 화면·입력으로 Runner 를 만든다(실제 마우스를 움직이지 않음)."""

    def __init__(self):
        self.clock = YieldingClock()
        self.vision = FakeVision(self.clock)
        self.input = FakeInput(self.clock)
        self.window = FakeWindow((0, 0))
        self.library = DictLibrary()

    def runner(self, macro, on_event=None):
        return Runner(macro, vision=self.vision, input=self.input, clock=self.clock,
                      library=self.library, window_factory=lambda cfg: self.window, on_event=on_event)


@pytest.fixture
def fake_env():
    return FakeEnv()


def wait_until(app, pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.01)
    app.processEvents()
    return pred()

"""
새 화면(v3, PySide6) 실행 진입점. `python main.py --v3` 와 `python -m gui.v3` 가 이걸 부른다.
DPI 설정은 QApplication 을 만들기 전에 해야 화면 좌표가 물리 픽셀로 맞는다.
"""
from __future__ import annotations

import os
import sys
import time
import traceback


def main(argv=None) -> int:
    from engine.win_window import set_dpi_awareness
    set_dpi_awareness()
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .main_window import MainWindowV2
    from gui.v2.i18n import tr

    app = QApplication.instance() or QApplication(list(argv or sys.argv))
    from gui.v2.i18n import install_qt_translator
    install_qt_translator(app)                  # 기본 버튼(확인·취소·닫기·예·아니요)도 한국어로
    from gui.v2.settings_path import data_writable, settings_dir
    if settings_dir() and not data_writable():  # 폴더형 묶음을 쓰기 막힌 곳(Program Files 등)에 풀었을 때
        from engine.real import PROJECT_ROOT
        QMessageBox.warning(None, tr("저장할 수 없는 위치"),
                            tr("이 위치에는 매크로·기록을 저장할 수 없습니다(예: Program Files 폴더).\n"
                               "프로그램 폴더를 통째로 바탕화면이나 D 드라이브 같은 곳으로 옮긴 뒤 다시 켜 주세요.\n\n"
                               "지금 위치: {path}").format(path=PROJECT_ROOT))
        return 1
    from .design import theme
    t = theme.apply(app)                        # 디자인 값 → 글꼴·색·꾸밈(테마·촘촘함·글자 크기 설정 반영)

    def hook(exctype, value, tb):
        from .errors import show_unexpected      # 쉬운 말 한 줄 + 자세히(접힘) + logs/오류 기록
        try:
            show_unexpected(exctype, value, tb)
        except Exception:
            print("".join(traceback.format_exception(exctype, value, tb)), file=sys.stderr)

    sys.excepthook = hook
    _install_crash_traces()
    if "--selftest" in list(argv or sys.argv):  # 묶음 점검: 모든 메뉴·단추·창을 화면 밖에서 한 번씩 열어 봄
        from .selftest import run as _selftest
        return _selftest(app)
    w = MainWindowV2()
    theme.dark_title_bar(w, t["theme"] == "dark")
    if "--run" in list(argv or sys.argv):
        # 11-23: 켜자마자 실행할 때 창이 앞에 튀어나와 사람이 쓰던 창(채팅 등)을 가리면, 그 자리를 누르던 클릭이
        # 큰 실행/정지 단추에 떨어져 바로 꺼졌음 → 바로 실행 모드는 작업 표시줄에 내린 채로 켬(초점도 안 뺏음).
        w.showMinimized()
    else:
        w.show()
    from PySide6.QtCore import QTimer
    if "--run" not in list(argv or sys.argv):          # 처음 켤 때 한 번 환경 점검(바로 실행 모드는 빼고)
        QTimer.singleShot(800, w.maybe_first_run_check)
    from engine.control import start_server            # AI(MCP) 요청을 이 프로그램이 대신 처리 → 뒤에서 실행이 한 곳에서만
    control = start_server()
    if control is not None:
        app.aboutToQuit.connect(control.stop)
    args = list(argv or sys.argv)
    if "--run" in args:                      # python main.py --run 매크로이름  : 켜자마자 그 매크로 실행
        i = args.index("--run")
        if i + 1 < len(args):
            from PySide6.QtCore import QTimer
            name = args[i + 1]
            QTimer.singleShot(800, lambda: w.run_macro(name))
    return app.exec()


def _install_crash_traces():
    """프로그램이 기록 없이 사라질 때 흔적을 남긴다(11-18 21:16 사라짐 조사 뒤): 치명 오류 스택(faulthandler),
    Qt 치명·경고 메시지, 스레드 안의 처리 안 된 예외 → logs/오류/. 실패해도 프로그램은 그대로."""
    import faulthandler
    import threading
    try:
        from .errors import log_dir, write_log
        d = log_dir()
        os.makedirs(d, exist_ok=True)
        fh = open(os.path.join(d, "fatal_stack.log"), "a", encoding="utf-8")
        fh.write("\n=== " + time.strftime("%Y-%m-%d %H:%M:%S") + f" 시작 pid {os.getpid()} ===\n")
        fh.flush()
        faulthandler.enable(file=fh, all_threads=True)
        _install_crash_traces.fh = fh               # 닫히지 않게 붙잡아 둠

        def thread_hook(args):
            write_log("스레드 예외 " + str(args.thread and args.thread.name) + "\n" +
                      "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
        threading.excepthook = thread_hook
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler

        def qt_handler(kind, ctx, msg):
            if kind in (QtMsgType.QtFatalMsg, QtMsgType.QtCriticalMsg):
                write_log(f"Qt {kind.name}: {msg}")
        qInstallMessageHandler(qt_handler)
    except Exception:
        pass

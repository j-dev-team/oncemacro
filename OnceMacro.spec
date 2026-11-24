# -*- mode: python ; coding: utf-8 -*-
# 새 화면(v3, PySide6) 폴더형 실행 묶음. 설치 파일 없음 — 압축 풀어 바로 쓴다(2026-11-17 사용자 결정).
# 만들기: venv\Scripts\python.exe scripts\run_limited.py --mem-gb 3 --timeout 900 -- venv\Scripts\python.exe -m PyInstaller OnceMacro.spec --distpath dist_v3 --workpath dist_v3\_build --noconfirm
# 결과: dist_v3\MacroManager\MacroManager.exe + _internal\  (지금 쓰는 dist\MacroManager.exe 와 따로)
# 자료(macros_v2·image·logs)는 '프로그램 폴더의 위 폴더'에 둔다 → 프로그램 폴더만 바꿔 끼워도 자료가 남는다(engine/real.py).
from PyInstaller.utils.hooks import collect_all
import os as _os0

# 추가 부품: packaging/extras.txt 에 적힌 꾸러미를 통째로 넣는다(배포판 전용, 공개 저장소엔 그 파일이 없음).
#   MACRO_LITE=1 이면 추가 부품 없이(작은 판).
LITE = _os0.environ.get("MACRO_LITE") == "1"
# 11-24: 공개판(가벼운 판) 실행 파일 이름은 OnceMacro.exe. 이 PC 판은 MacroManager.exe 그대로(운영 스크립트·AI 연결 설정이 이 이름을 씀)
APP_NAME = "OnceMacro"     # 공개판: MACRO_PUBLIC=1
_x_datas, _x_bins, _x_hidden = [], [], []
_xf = _os0.path.join("packaging", "extras.txt")
for _n in ([] if LITE or not _os0.path.exists(_xf) else
           [l.strip() for l in open(_xf, encoding="utf-8") if l.strip() and not l.startswith("#")]):
    _d, _b, _h = collect_all(_n)
    _x_datas += _d
    _x_bins += _b
    _x_hidden += _h + [_n]
# PDF 글자·표 읽기(engine/pdfread.py): pdfplumber(MIT)·pdfminer.six(MIT, 글꼴 표 자료)·pypdfium2(BSD/Apache, pdfium.dll)
_pdf_datas, _pdf_bins, _pdf_hidden = [], [], []
for _m in ('pdfplumber', 'pdfminer', 'pypdfium2', 'pypdfium2_raw'):
    _d, _b, _h = collect_all(_m)
    _pdf_datas += _d
    _pdf_bins += _b
    _pdf_hidden += _h
# 창 요소 찾기(engine/win_uia.py): comtypes(MIT). 미리 만든 UI 자동화 형식(comtypes.gen)까지 같이 넣는다
_ct_datas, _ct_bins, _ct_hidden = collect_all('comtypes')

# 판 표시(도움말 → 이 프로그램 정보): 만든 시각·저장소 판 번호를 묶음 안에 넣는다(11-18 옛 판·새 판 구분)
import json as _json, os as _os, subprocess as _sp, time as _time
try:
    _rev = _sp.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
except Exception:
    _rev = ""
_os.makedirs(_os.path.join("dist_v3", "_build"), exist_ok=True)
with open(_os.path.join("dist_v3", "_build", "build_info.json"), "w", encoding="utf-8") as _f:
    _json.dump({"built": _time.strftime("%Y-%m-%d %H:%M"), "rev": _rev}, _f, ensure_ascii=False)

a = Analysis(
    ['launch_v3.py'],
    pathex=[],
    binaries=_x_bins + _pdf_bins + _ct_bins,
    datas=_x_datas + _pdf_datas + _ct_datas + [
        ('dist_v3/_build/build_info.json', 'gui/v3'),
        ('gui/v2/lang', 'gui/v2/lang'),          # 같이 쓰는 번역 사전
        ('gui/v3/lang', 'gui/v3/lang'),
        ('gui/v3/assets', 'gui/v3/assets'),      # 글꼴(Pretendard, OFL 전문 포함)·아이콘(Lucide, 사용 조건 포함)
        ('gui/v3/example_data', 'gui/v3/example_data'),  # 첫 화면 '예시 넣기'용 예시 매크로 틀·가짜 자료(엑셀·한글)
        ('engine/lang', 'engine/lang'),
        ('engine/webmail_services.json', 'engine'),   # 웹메일 서비스별 화면 묶음
    ],
    hiddenimports=_x_hidden + _pdf_hidden + _ct_hidden + [
        'engine.mcp_server', 'win32timezone', 'engine.office', 'engine.web',
        'gui.v3.app', 'gui.v3.main_window', 'gui.v3.editor.macro_editor',
        'engine.real', 'engine.win_input', 'engine.win_vision', 'engine.win_window', 'engine.win_background',
        'engine.templates', 'engine.win_uia', 'comtypes.gen.UIAutomationClient', 'pynput.keyboard._win32', 'pynput.mouse._win32',
        'PySide6.QtSvg', 'typing_extensions',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Qt 묶음은 하나만: 옛 화면(PyQt5)은 넣지 않는다
        'PyQt5', 'gui.main_window', 'gui.v2.app', 'gui.v2.main_window', 'gui.v2.editor',
        'matplotlib', 'scipy', 'pandas', 'notebook', 'IPython', 'tkinter', 'test', 'lib2to3',
        'pydoc', 'doctest', 'pdb', 'setuptools', 'distutils',
        # 안 쓰는 PySide6 모듈
        'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick', 'PySide6.QtWebChannel',
        'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets', 'PySide6.QtQuick3D', 'PySide6.QtQuickControls2',
        'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DExtras', 'PySide6.Qt3DInput', 'PySide6.Qt3DLogic',
        'PySide6.Qt3DAnimation', 'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtGraphs',
        'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets', 'PySide6.QtSpatialAudio', 'PySide6.QtPdf',
        'PySide6.QtPdfWidgets', 'PySide6.QtBluetooth', 'PySide6.QtNfc', 'PySide6.QtPositioning',
        'PySide6.QtLocation', 'PySide6.QtSensors', 'PySide6.QtSerialPort', 'PySide6.QtSerialBus',
        'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtDesigner', 'PySide6.QtHelp', 'PySide6.QtUiTools',
        'PySide6.QtRemoteObjects', 'PySide6.QtScxml', 'PySide6.QtStateMachine', 'PySide6.QtTextToSpeech',
        'PySide6.QtWebSockets', 'PySide6.QtHttpServer', 'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets',
    ],
    noarchive=False,
)

# 크기 줄이기: 화면(위젯)만 쓰므로 Qt Quick·Qml·Pdf·가상 키보드·네트워크·OpenGL 부품, 소프트웨어 그래픽(opengl32sw),
# 동영상 부품(opencv ffmpeg)은 빼도 된다. 다른 부품이 끌고 들어오므로 모은 뒤 이름으로 거른다.
_DROP = (
    'opengl32sw.dll', 'qt6pdf', 'qt6qml', 'qt6quick', 'qt6virtualkeyboard', 'qt6network', 'qt6opengl',
    'qtvirtualkeyboardplugin', 'imageformats/qpdf', 'networkinformation/', 'tls/', 'generic/qtuiotouchplugin',
    'opencv_videoio_ffmpeg',
)


def _keep(entry):
    name = entry[0].replace('\\', '/').lower()
    return not any(d in name for d in _DROP)


a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,          # 폴더형: 부품은 _internal 에 그대로(사용자가 바꿔 끼울 수 있게)
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,                    # strip 은 일부 부품(.pyd)을 망가뜨림
    upx=False,                      # 폴더형은 압축 안 함(켜는 속도·백신 오탐)
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

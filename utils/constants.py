"""
애플리케이션 상수 정의
"""
import os

# 파일 경로
MACRO_DIR = "macros"
IMAGE_DIR = "image"
ICONS_DIR = "icons"
CHAIN_DIR = "chains"  # 체인 저장 디렉토리

# 파일 확장자
MACRO_EXTENSION = ".json"
IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".bmp", ".gif"]
CHAIN_EXTENSION = ".json"

# UI 설정
RIBBON_HEIGHT = 120
BUTTON_LARGE_SIZE = (72, 66)
BUTTON_SMALL_SIZE = (60, 22)

# 색상 팔레트 (Microsoft 스타일)
COLORS = {
    'PRIMARY': '#005a9e',
    'BACKGROUND': '#fafafa',
    'SURFACE': '#f3f2f1',
    'BORDER': '#d1d1d1',
    'TEXT': '#323130',
    'TEXT_SECONDARY': '#605e5c',
    'HOVER': '#e1dfdd',
    'PRESSED': '#edebe9',
    'ACCENT': '#0078d4'
}

# 기본값
DEFAULT_CONFIDENCE = 0.8
DEFAULT_TIMEOUT = 10.0
DEFAULT_TOLERANCE = 0
DEFAULT_DELAY = 1.0
DEFAULT_REPEAT_COUNT = 1

# 단축키 매핑
HOTKEY_MAPPING = {
    'ctrl+c': ['ctrl', 'c'],
    'ctrl+v': ['ctrl', 'v'],
    'ctrl+a': ['ctrl', 'a'],
    'ctrl+z': ['ctrl', 'z'],
    'ctrl+y': ['ctrl', 'y'],
    'ctrl+x': ['ctrl', 'x'],
    'alt+tab': ['alt', 'tab'],
    'alt+f4': ['alt', 'f4']
}

# 액션 타입
ACTION_TYPES = {
    'IMAGE': 'image',
    'COLOR': 'color',
    'MOUSE': 'mouse_move',
    'KEYBOARD': 'keyboard',
    'DELAY': 'delay',
    'LOGIC_BRANCH': 'logic_branch'  # 논리 분기
}

# 마우스 버튼
MOUSE_BUTTONS = ['left', 'right', 'middle']

# 마우스 액션
MOUSE_ACTIONS = ['click', 'press', 'release', 'move']

# 매크로 리턴값 상수 (단순화)
RETURN_VALUES = {
    'FAILURE': 0,      # 실패
    'SUCCESS': 1,      # 성공
}

RETURN_VALUE_NAMES = {
    0: '실패',
    1: '성공',
}

def get_chain_path(chain_name: str) -> str:
    """체인 파일 경로 반환"""
    return os.path.join(CHAIN_DIR, f"{chain_name}{CHAIN_EXTENSION}")

def get_chain_groups_path() -> str:
    """체인 그룹 파일 경로 반환"""
    return "chain_groups.json" 
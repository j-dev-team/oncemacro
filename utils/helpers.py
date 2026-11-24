"""
공통 헬퍼 함수들
"""
import os
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from .constants import MACRO_DIR, MACRO_EXTENSION, IMAGE_EXTENSIONS, RETURN_VALUE_NAMES


def ensure_directory(path: str) -> None:
    """디렉토리가 존재하지 않으면 생성"""
    if not os.path.exists(path):
        os.makedirs(path)


def get_macro_path(macro_name: str) -> str:
    """매크로 파일 경로를 반환합니다."""
    return os.path.join(MACRO_DIR, f"{macro_name}.json")


def load_json_file(file_path: str, default: Any = None) -> Any:
    """JSON 파일 로드 (안전)"""
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"JSON 파일 로드 실패: {file_path}, 오류: {e}")
    return default if default is not None else {}


def save_json_file(file_path: str, data: Any) -> bool:
    """JSON 파일 저장 (안전)"""
    try:
        # 디렉토리 확인
        directory = os.path.dirname(file_path)
        if directory:
            ensure_directory(directory)
            
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except (IOError, TypeError) as e:
        print(f"JSON 파일 저장 실패: {file_path}, 오류: {e}")
        return False


def is_image_file(file_path: str) -> bool:
    """이미지 파일인지 확인"""
    if not file_path:
        return False
    ext = os.path.splitext(file_path)[1].lower()
    return ext in IMAGE_EXTENSIONS


def format_timestamp(timestamp: Optional[float] = None) -> str:
    """타임스탬프를 문자열로 포맷"""
    if timestamp is None:
        timestamp = datetime.now().timestamp()
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def sanitize_filename(filename: str) -> str:
    """파일명에서 불법 문자 제거"""
    illegal_chars = '<>:"/\\|?*'
    for char in illegal_chars:
        filename = filename.replace(char, '_')
    return filename.strip()


def get_file_size_str(file_path: str) -> str:
    """파일 크기를 읽기 쉬운 문자열로 반환"""
    try:
        size = os.path.getsize(file_path)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"
    except OSError:
        return "알 수 없음"


def validate_coordinates(x: Any, y: Any) -> bool:
    """좌표 유효성 검사"""
    try:
        int(x)
        int(y)
        return True
    except (ValueError, TypeError):
        return False


def parse_hotkey(hotkey_str: str) -> List[str]:
    """단축키 문자열을 키 리스트로 파싱"""
    if not hotkey_str:
        return []
    return [key.strip().lower() for key in hotkey_str.split('+')]


def format_action_description(action, indent=0):
    """액션을 설명 문자열로 변환합니다.

    Args:
        action: 액션 딕셔너리
        indent: 들여쓰기 레벨 (0: 메인 액션, 1+: 하위 액션)
    """
    action_type = action['type']
    params = action['params']
    indent_str = "  " * indent  # 2칸 들여쓰기

    if action_type == 'mouse_move':
        description_parts = []
        
        # 현재 위치 저장 기능이 있는 경우
        save_var = params.get('save_position_var')
        if save_var:
            description_parts.append(f"위치저장 → 변수:{save_var}")
        
        # 이동만 하기 기능이 체크된 경우
        if params.get('move_only', False):
            description_parts.append(f"이동: ({params.get('x', '?')}, {params.get('y', '?')})")
        else:
            # 기존 마우스 액션 처리
            button = params.get('button', 'left')
            action_name = params.get('action', 'click')
            double = params.get('double', False)
            
            btn_map = {'left': '왼쪽', 'right': '오른쪽', 'middle': '휠'}
            act_map = {'press': '누르기', 'release': '떼기', 'click': '누르고떼기'}
            
            btn_str = btn_map.get(button, button)
            act_str = act_map.get(action_name, action_name)
            double_str = '더블' if double else ''
            
            # 좌표 정보
            x_coord = params.get('x', '?')
            y_coord = params.get('y', '?')
            
            # 변수인지 확인하여 표시
            x_display = f"변수:{x_coord}" if isinstance(x_coord, str) and not str(x_coord).isdigit() else str(x_coord)
            y_display = f"변수:{y_coord}" if isinstance(y_coord, str) and not str(y_coord).isdigit() else str(y_coord)
            
            description_parts.append(f"{btn_str}{double_str}{act_str}: ({x_display}, {y_display})")
        
        # 모든 부분을 " + "로 연결
        return indent_str + "마우스 " + " + ".join(description_parts)
        
    elif action_type == 'mouse_click':
        button = params.get('button', 'left')
        btn_map = {'left': '왼쪽', 'right': '오른쪽', 'middle': '휠'}
        btn_str = btn_map.get(button, button)
        return indent_str + f"마우스 {btn_str} 클릭: ({params.get('x', '?')}, {params.get('y', '?')})"
    elif action_type == 'image':
        # 이미지 검색 액션 - 변수명과 파일명 표시
        template = params.get('template', '')
        result_var = params.get('result_var', '')
        timeout = params.get('timeout', 10.0)
        confidence = params.get('confidence', 0.8)
        wait_until_disappear = params.get('wait_until_disappear', False)
        disappear_duration = params.get('disappear_duration', 1.0)
        on_success = params.get('on_success', [])
        on_failure = params.get('on_failure', [])

        # 파일명에서 경로 제거하고 파일명만 표시
        filename = os.path.basename(template) if template else '?'

        # 타임아웃 정보 (사라질 때까지 대기 모드인 경우 별도 표시)
        if wait_until_disappear:
            timeout_str = f"{disappear_duration}초 이상 사라질때까지 대기"
        else:
            timeout_str = "무한대기" if timeout == 0 else f"{timeout}초"

        # 변수명 표시 (비어있으면 "없음"으로 표시)
        var_display = result_var if result_var else "없음"

        # 기본 설명
        desc = indent_str + f"이미지검색 → 변수:{var_display} (파일:{filename}, 대기:{timeout_str}, 정확도:{confidence})"

        return desc
    elif action_type == 'color':
        # 색상 검색 액션 - 좌표와 색상 정보 표시
        color = params.get('color', (0, 0, 0))
        x = params.get('x', 0)
        y = params.get('y', 0)
        timeout = params.get('timeout', 10.0)
        tolerance = params.get('tolerance', 0)
        wait_until_disappear = params.get('wait_until_disappear', False)
        disappear_duration = params.get('disappear_duration', 1.0)
        on_success = params.get('on_success', [])
        on_failure = params.get('on_failure', [])

        # 타임아웃 정보 (사라질 때까지 대기 모드인 경우 별도 표시)
        if wait_until_disappear:
            timeout_str = f"{disappear_duration}초 이상 사라질때까지 대기"
        else:
            timeout_str = "무한대기" if timeout == 0 else f"{timeout}초"

        # 색상을 RGB 형태로 표시
        color_str = f"RGB({color[0]},{color[1]},{color[2]})" if isinstance(color, (list, tuple)) and len(color) >= 3 else str(color)

        # 기본 설명
        desc = indent_str + f"색상검색: ({x},{y})에서 {color_str} (대기:{timeout_str}, 오차:{tolerance})"

        return desc
    elif action_type == 'delay':
        return indent_str + f"대기: {params.get('delay', 0)}초"
    elif action_type == 'comment':
        comment = params.get('comment', '')
        return indent_str + f"📝 주석: {comment}"
    elif action_type == 'keyboard':
        hotkey_type = params.get('hotkey_type', 'normal')

        if hotkey_type == 'combo':
            # 조합키 액션
            combo_key = params.get('combo_key', '')
            return indent_str + f"키보드 조합키: {combo_key}"
        else:
            # 일반 키 액션
            key = params.get('key', '')
            action_name = params.get('action', 'click')
            act_map = {'press': '누르기', 'release': '떼기', 'click': '누르고 떼기'}
            act_str = act_map.get(action_name, action_name)
            return indent_str + f"키보드 {key} {act_str}"
    elif action_type == 'set_return':
        # 리턴값 설정 액션
        return_value = params.get('return_value', 0)
        value_name = RETURN_VALUE_NAMES.get(return_value, str(return_value))
        return indent_str + f"리턴값 설정: {value_name} ({return_value})"
    elif action_type == 'logic_branch':
        # 논리 분기 액션 - 이미지 또는 색상 검색 결과로 리턴값 결정
        condition_type = params.get('condition_type', '')
        condition_data = params.get('condition_data', {})

        if condition_type == 'image':
            template = condition_data.get('image_path', '')
            filename = os.path.basename(template) if template else '?'
            confidence = condition_data.get('confidence', 0.8)
            timeout = condition_data.get('timeout', 10.0)
            timeout_str = f"{timeout}초"
            return indent_str + f"논리분기(이미지): {filename} (대기:{timeout_str}, 정확도:{confidence})"
        elif condition_type == 'color':
            color = condition_data.get('color', (0, 0, 0))
            x = condition_data.get('x', 0)
            y = condition_data.get('y', 0)
            timeout = condition_data.get('timeout', 10.0)
            tolerance = condition_data.get('tolerance', 0)
            timeout_str = f"{timeout}초"
            color_str = f"RGB({color[0]},{color[1]},{color[2]})" if isinstance(color, (list, tuple)) and len(color) >= 3 else str(color)
            return indent_str + f"논리분기(색상): ({x},{y})에서 {color_str} (대기:{timeout_str}, 오차:{tolerance})"
        else:
            return indent_str + f"논리분기: 조건 없음"
    else:
        return indent_str + f"알 수 없는 동작: {action_type}"


def get_recent_macros_path() -> str:
    """최근 매크로 목록 파일 경로를 반환합니다."""
    # 프로젝트 루트 디렉토리에 저장 (매크로 디렉토리가 아닌)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project_root, "recent_macros.json")


def get_groups_path() -> str:
    """그룹 정보 파일 경로를 반환합니다."""
    return os.path.join(MACRO_DIR, "groups.json") 
"""
핫키 관리자 - pynput 기반으로 넘버패드 키 구분 지원
"""
import os
import json
from typing import Dict, Callable, Optional
import threading
import time


class HotkeyManager:
    """핫키 관리 클래스 - pynput 기반"""
    
    def __init__(self):
        self.hotkey_callbacks: Dict[str, Callable] = {}
        self.toggle_callbacks: Dict[str, Dict[str, Callable]] = {}  # 토글용 콜백 저장
        # self.hotkey_handlers 제거 (미사용 변수)
        self.pynput_keyboard = None
        self.listener = None
        self.pressed_keys = set()
        self._lock = threading.RLock()  # 스레드 안전성
        self._enabled = True  # 핫키 활성화 상태
        self._init_keyboard()
    
    def _init_keyboard(self):
        """pynput keyboard 모듈 초기화"""
        try:
            from pynput import keyboard
            self.pynput_keyboard = keyboard
            self._start_listener()
        except ImportError:
            print("pynput 모듈이 설치되지 않았습니다. 핫키 기능을 사용할 수 없습니다.")
            self.pynput_keyboard = None
    
    def _start_listener(self):
        """키보드 리스너 시작"""
        if not self.pynput_keyboard:
            return

        # 기존 리스너 정리
        if self.listener:
            if self.listener.is_alive():  # 실제 실행 중인지 확인
                return  # 이미 실행 중
            else:
                self.listener = None  # 중지된 리스너 정리

        # 새 리스너 시작
        self.listener = self.pynput_keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release
        )
        self.listener.start()
    
    def _stop_listener(self):
        """키보드 리스너 중지"""
        if self.listener:
            self.listener.stop()
            self.listener.join(timeout=1.0)  # 스레드 종료 대기 (최대 1초)
            self.listener = None
    
    def _normalize_key(self, key):
        """키를 정규화된 문자열로 변환"""
        # 먼저 char 속성 확인 (제어 문자 제외)
        if hasattr(key, 'char') and key.char:
            # ASCII 제어 문자 제외 (0x00-0x1F)
            if ord(key.char) >= 32:
                return key.char

        # VK 코드로 매핑
        if hasattr(key, 'vk'):
            # 넘버패드 키들의 VK 코드 매핑
            numpad_mapping = {
                106: 'numpad_*',  # 넘버패드 *
                107: 'numpad_+',  # 넘버패드 +
                108: 'numpad_enter',  # 넘버패드 엔터
                109: 'numpad_-',  # 넘버패드 -
                110: 'numpad_.',  # 넘버패드 .
                111: 'numpad_/',  # 넘버패드 /
                96: 'numpad_0',   # 넘버패드 0
                97: 'numpad_1',   # 넘버패드 1
                98: 'numpad_2',   # 넘버패드 2
                99: 'numpad_3',   # 넘버패드 3
                100: 'numpad_4',  # 넘버패드 4
                101: 'numpad_5',  # 넘버패드 5
                102: 'numpad_6',  # 넘버패드 6
                103: 'numpad_7',  # 넘버패드 7
                104: 'numpad_8',  # 넘버패드 8
                105: 'numpad_9',  # 넘버패드 9
            }

            # 일반 숫자 키 VK 코드 (상단 숫자 키)
            number_mapping = {
                48: '0', 49: '1', 50: '2', 51: '3', 52: '4',
                53: '5', 54: '6', 55: '7', 56: '8', 57: '9'
            }

            # 알파벳 키 VK 코드 (A-Z: 65-90)
            alpha_mapping = {
                65: 'a', 66: 'b', 67: 'c', 68: 'd', 69: 'e', 70: 'f',
                71: 'g', 72: 'h', 73: 'i', 74: 'j', 75: 'k', 76: 'l',
                77: 'm', 78: 'n', 79: 'o', 80: 'p', 81: 'q', 82: 'r',
                83: 's', 84: 't', 85: 'u', 86: 'v', 87: 'w', 88: 'x',
                89: 'y', 90: 'z'
            }

            # 펑션 키 VK 코드 (F1-F12: 112-123)
            function_mapping = {
                112: 'f1', 113: 'f2', 114: 'f3', 115: 'f4',
                116: 'f5', 117: 'f6', 118: 'f7', 119: 'f8',
                120: 'f9', 121: 'f10', 122: 'f11', 123: 'f12'
            }

            # 특수 키 VK 코드
            special_mapping = {
                8: 'backspace', 9: 'tab', 13: 'enter', 19: 'pause',
                20: 'caps_lock', 27: 'esc', 32: 'space', 33: 'page_up',
                34: 'page_down', 35: 'end', 36: 'home', 37: 'left',
                38: 'up', 39: 'right', 40: 'down', 45: 'insert',
                46: 'delete', 144: 'num_lock', 145: 'scroll_lock',
                186: ';', 187: '=', 188: ',', 189: '-', 190: '.',
                191: '/', 192: '`', 219: '[', 220: '\\', 221: ']',
                222: "'"
            }

            if key.vk in numpad_mapping:
                return numpad_mapping[key.vk]
            elif key.vk in number_mapping:
                return number_mapping[key.vk]
            elif key.vk in alpha_mapping:
                return alpha_mapping[key.vk]
            elif key.vk in function_mapping:
                return function_mapping[key.vk]
            elif key.vk in special_mapping:
                return special_mapping[key.vk]

        # name 속성으로 처리
        if hasattr(key, 'name'):
            name = key.name
            # 좌우 구분 키 통합
            if name in ['ctrl_l', 'ctrl_r']:
                return 'ctrl'
            elif name in ['shift_l', 'shift_r']:
                return 'shift'
            elif name in ['alt_l', 'alt_r', 'alt_gr']:
                return 'alt'
            else:
                return name

        # 마지막 수단
        return str(key)
    
    def _on_key_press(self, key):
        """키 눌림 이벤트 처리"""
        key_str = self._normalize_key(key)
        # (11-17) 누른 키를 하나하나 찍던 디버그 출력 제거: 사용자 입력을 남기지 않는다

        # 핫키가 비활성화 상태면 무시
        if not self._enabled:
            return

        # 중복 방지
        if key_str in self.pressed_keys:
            return

        self.pressed_keys.add(key_str)

        # 현재 조합 생성
        key_combination = self._get_key_combination()

        # 등록된 핫키와 매칭 (긴 조합 우선, 스레드 안전)
        with self._lock:
            for hotkey in sorted(self.hotkey_callbacks.keys(), key=lambda x: -len(x)):
                if self._match_hotkey(hotkey, key_combination):
                    print(f"[DEBUG] 핫키 매치: {hotkey}")
                    callback = self.hotkey_callbacks[hotkey]
                    threading.Thread(
                        target=self._safe_callback,
                        args=(callback, hotkey),
                        daemon=True
                    ).start()
                    break
    
    def _safe_callback(self, callback, hotkey):
        """안전한 콜백 실행 (예외 처리 포함)"""
        try:
            print(f"[핫키] {hotkey} 감지됨 → 콜백 실행")
            callback()
        except Exception as e:
            print(f"[에러] 핫키 콜백 실행 실패 ({hotkey}): {e}")
            import traceback
            traceback.print_exc()

    def _on_key_release(self, key):
        """키 뗌 이벤트 처리"""
        key_str = self._normalize_key(key)
        self.pressed_keys.discard(key_str)
    
    def _get_key_combination(self):
        """현재 눌린 키들을 조합 문자열로 변환"""
        if not self.pressed_keys:
            return ""
        
        # 수식어 키와 일반 키 분리
        modifiers = []
        normal_keys = []
        
        for key in self.pressed_keys:
            if key in ['ctrl', 'shift', 'alt', 'cmd']:
                modifiers.append(key)
            else:
                normal_keys.append(key)
        
        # 조합 생성 (수식어+일반키 순서)
        if modifiers and normal_keys:
            return '+'.join(sorted(modifiers) + sorted(normal_keys))
        elif normal_keys:
            return '+'.join(sorted(normal_keys))
        else:
            return '+'.join(sorted(modifiers))
    
    def _normalize_hotkey_string(self, hotkey_str: str) -> str:
        """핫키 문자열을 정규화합니다 (소문자 변환 + 정렬)"""
        if not hotkey_str:
            return ""

        # + 기호로 분리
        keys = [k.strip().lower() for k in hotkey_str.split('+')]

        # 수식어 키와 일반 키 분리
        modifiers = []
        normal_keys = []

        for key in keys:
            if key in ['ctrl', 'shift', 'alt', 'cmd']:
                modifiers.append(key)
            else:
                normal_keys.append(key)

        # 정렬 후 결합 (수식어+일반키 순서)
        if modifiers and normal_keys:
            return '+'.join(sorted(modifiers) + sorted(normal_keys))
        elif normal_keys:
            return '+'.join(sorted(normal_keys))
        else:
            return '+'.join(sorted(modifiers))

    def _match_hotkey(self, registered_hotkey, current_combination):
        """핫키 매칭 확인"""
        # 단순 문자열 비교 (이미 정규화되어 있음)
        if registered_hotkey == current_combination:
            return True

        # 별칭 처리 (backward compatibility)
        if registered_hotkey == '*' and current_combination == 'numpad_*':
            return True

        return False

    def register_hotkey(self, hotkey: str, callback: Callable) -> bool:
        """핫키를 등록합니다."""
        if not self.pynput_keyboard or not hotkey:
            return False

        try:
            # 핫키 문자열 정규화 (소문자 변환 + 정렬)
            hotkey_normalized = self._normalize_hotkey_string(hotkey)

            # 기존 핫키가 있다면 제거
            if hotkey_normalized in self.hotkey_callbacks:
                self.unregister_hotkey(hotkey_normalized)

            # 핫키 등록 (스레드 안전)
            with self._lock:
                self.hotkey_callbacks[hotkey_normalized] = callback

            # 넘버패드 * 키 별칭도 함께 등록
            if hotkey == '*':
                with self._lock:
                    self.hotkey_callbacks['numpad_*'] = callback
                print(f"핫키 등록됨: {hotkey} (별칭: numpad_* 포함) → 정규화: {hotkey_normalized}")
            else:
                print(f"핫키 등록됨: {hotkey} → 정규화: {hotkey_normalized}")

            return True
        except Exception as e:
            print(f"핫키 등록 실패 ({hotkey}): {e}")
            return False
    
    def register_toggle_hotkey(self, hotkey: str, start_callback: Callable, stop_callback: Callable, is_running_func: Callable) -> bool:
        """토글 핫키를 등록합니다 (시작/종료가 같은 핫키인 경우)."""
        if not self.pynput_keyboard or not hotkey:
            return False

        try:
            # 핫키 문자열 정규화
            hotkey_normalized = self._normalize_hotkey_string(hotkey)

            # 기존 핫키가 있다면 제거
            if hotkey_normalized in self.hotkey_callbacks:
                self.unregister_hotkey(hotkey_normalized)

            # 토글 콜백 생성 (디버그 메시지 포함)
            def toggle_callback():
                if is_running_func():
                    print(f"[핫키] {hotkey} 눌림 - 매크로 중지")
                    stop_callback()
                else:
                    print(f"[핫키] {hotkey} 눌림 - 매크로 시작")
                    start_callback()

            # 핫키 등록 (스레드 안전)
            with self._lock:
                self.hotkey_callbacks[hotkey_normalized] = toggle_callback
                self.toggle_callbacks[hotkey_normalized] = {
                    'start': start_callback,
                    'stop': stop_callback,
                    'is_running': is_running_func
                }

            # 넘버패드 * 키 별칭도 함께 등록
            if hotkey == '*':
                with self._lock:
                    self.hotkey_callbacks['numpad_*'] = toggle_callback
                    self.toggle_callbacks['numpad_*'] = {
                        'start': start_callback,
                        'stop': stop_callback,
                        'is_running': is_running_func
                    }
                print(f"토글 핫키 등록됨: {hotkey} (별칭: numpad_* 포함) → 정규화: {hotkey_normalized}")
            else:
                print(f"토글 핫키 등록됨: {hotkey} → 정규화: {hotkey_normalized}")

            return True
        except Exception as e:
            print(f"토글 핫키 등록 실패 ({hotkey}): {e}")
            return False
    
    def unregister_hotkey(self, hotkey: str) -> bool:
        """핫키를 해제합니다."""
        if not self.pynput_keyboard or hotkey not in self.hotkey_callbacks:
            return False
        
        try:
            # 넘버패드 * 키 별칭 처리
            if hotkey == '*':
                hotkey = 'numpad_*'
            
            # 사전에 저장한 정보 정리
            self.hotkey_callbacks.pop(hotkey, None)
            self.toggle_callbacks.pop(hotkey, None)
            print(f"핫키 해제됨: {hotkey}")
            return True
        except Exception as e:
            print(f"핫키 해제 실패 ({hotkey}): {e}")
            return False
    
    def clear_all_hotkeys(self):
        """모든 핫키를 해제합니다."""
        if not self.pynput_keyboard:
            return
        
        self.hotkey_callbacks.clear()
        self.toggle_callbacks.clear()
        print("모든 핫키 해제됨")
    
    def is_available(self) -> bool:
        """핫키 기능 사용 가능 여부를 반환합니다."""
        return self.pynput_keyboard is not None
    
    def __del__(self):
        """소멸자 - 리스너 정리"""
        try:
            self._stop_listener()
        except Exception:
            pass  # 소멸자에서 예외 발생 방지
    
    def get_registered_hotkeys(self) -> list:
        """등록된 핫키 목록을 반환합니다."""
        return list(self.hotkey_callbacks.keys())

    def disable_hotkeys(self):
        """핫키를 일시적으로 비활성화합니다."""
        self._enabled = False
        print("[핫키] 핫키 비활성화")

    def enable_hotkeys(self):
        """핫키를 다시 활성화합니다."""
        self._enabled = True
        print("[핫키] 핫키 활성화")


def load_macro_hotkeys(macro_dir: str) -> Dict[str, Dict[str, str]]:
    """매크로 디렉토리에서 모든 매크로의 핫키 정보를 로드합니다."""
    hotkeys = {}
    
    if not os.path.exists(macro_dir):
        return hotkeys
    
    for filename in os.listdir(macro_dir):
        if filename.endswith('.json') and filename not in ['groups.json', 'recent_macros.json']:
            macro_name = filename[:-5]
            macro_path = os.path.join(macro_dir, filename)
            
            try:
                with open(macro_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                run_hotkey = data.get('run_hotkey', '')
                stop_hotkey = data.get('stop_hotkey', '')
                
                if run_hotkey or stop_hotkey:
                    hotkeys[macro_name] = {
                        'run_hotkey': run_hotkey,
                        'stop_hotkey': stop_hotkey
                    }
            except Exception as e:
                print(f"매크로 핫키 로드 실패 ({macro_name}): {e}")
    
    return hotkeys 
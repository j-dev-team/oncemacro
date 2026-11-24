"""'숨겨서 실행'(win_hide): 이 시험 프로세스가 만든 화면 밖 작은 창으로만 시험한다(사람 화면엔 안 보임).

- 숨기면 모양이 바뀌고, 되돌리면 원래 모양(창 스타일 그대로)
- 최소화된 창은 앞으로 안 가져오고 되살려 숨기고, 되돌리면 다시 최소화
- 숨긴 프로세스가 강제로 죽어도 지킴이가 되돌림
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="윈도우 전용")

win_hide = pytest.importorskip("engine.win_hide")
if not win_hide.supported():
    pytest.skip("이 판에는 숨겨서 실행이 없음", allow_module_level=True)

user32 = ctypes.WinDLL("user32")
user32.GetWindowLongW.restype = ctypes.c_long
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsWindow.argtypes = [wintypes.HWND]
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 화면 밖(-32000)에 보이는 창 하나를 띄우고 hwnd 를 출력한 뒤 stdin 이 닫힐 때까지 메시지를 돌린다
WINDOW_PY = r'''
import ctypes, sys, threading
from ctypes import wintypes
u = ctypes.WinDLL("user32"); k = ctypes.WinDLL("kernel32")
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u.DefWindowProcW.restype = ctypes.c_ssize_t
proc = WNDPROC(lambda h, m, w, l: u.DefWindowProcW(h, m, w, l))
class WC(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("proc", WNDPROC), ("a", ctypes.c_int), ("b", ctypes.c_int),
                ("inst", wintypes.HINSTANCE), ("icon", wintypes.HICON), ("cur", wintypes.HANDLE),
                ("bg", wintypes.HBRUSH), ("menu", wintypes.LPCWSTR), ("name", wintypes.LPCWSTR)]
wc = WC(0, proc, 0, 0, k.GetModuleHandleW(None), None, None, None, None, "HideTestWnd")
u.RegisterClassW(ctypes.byref(wc))
u.CreateWindowExW.restype = wintypes.HWND
u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
h = u.CreateWindowExW(0x80, "HideTestWnd", "hide test", 0x00CF0000 | 0x10000000, -32000, -32000, 200, 150,
                      None, None, wc.inst, None)            # WS_EX_TOOLWINDOW, 보이는 창(화면 밖)
if "min" in sys.argv:
    u.ShowWindow(h, 7)
print(int(h), flush=True)
def quit_on_eof():
    sys.stdin.read(); u.PostQuitMessage(0); u.PostThreadMessageW(tid, 0x12, 0, 0)
tid = k.GetCurrentThreadId()
threading.Thread(target=quit_on_eof, daemon=True).start()
msg = wintypes.MSG()
while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
    u.TranslateMessage(ctypes.byref(msg)); u.DispatchMessageW(ctypes.byref(msg))
'''


@pytest.fixture
def window(tmp_path):
    procs = []

    def make(minimized=False):
        p = subprocess.Popen([sys.executable, "-c", WINDOW_PY] + (["min"] if minimized else []),
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        procs.append(p)
        return int(p.stdout.readline())
    yield make
    for p in procs:
        try:
            p.stdin.close()
            p.wait(5)
        except Exception:
            p.kill()


def ex(h):
    return user32.GetWindowLongW(h, -20) & 0xFFFFFFFF


def test_hide_and_restore(window, tmp_path):
    h = window()
    before = ex(h)
    hw = win_hide.HiddenWindow(h, root=str(tmp_path), watch=False)
    hw.apply()
    assert win_hide.is_hidden(h)
    assert os.listdir(os.path.join(tmp_path, "logs", "hidden"))
    hw.show_for_now()
    assert ex(h) == before
    hw.hide_again()
    assert win_hide.is_hidden(h)
    hw.restore()
    hw.restore()                                               # 두 번 불러도 됨
    assert ex(h) == before
    assert not [f for f in os.listdir(os.path.join(tmp_path, "logs", "hidden")) if f.endswith(".json")]


def test_minimized_comes_back_minimized(window, tmp_path):
    h = window(minimized=True)
    assert user32.IsIconic(h)
    hw = win_hide.HiddenWindow(h, root=str(tmp_path), watch=False)
    hw.apply()
    assert not user32.IsIconic(h)                              # 숨긴 채 되살림(그림·위치 가능)
    hw.restore()
    assert user32.IsIconic(h) and not win_hide.is_hidden(h)


def test_recover_stale_restores_dead_owner(window, tmp_path):
    import json
    h = window()
    before = ex(h)
    hw = win_hide.HiddenWindow(h, root=str(tmp_path), watch=False)
    hw.apply()
    p = hw.path
    rec = json.load(open(p, encoding="utf-8"))
    rec["owner"], rec["owner_start"] = 999999, 1                # 없는 주인
    json.dump(rec, open(p, "w", encoding="utf-8"))
    assert win_hide.recover_stale(str(tmp_path)) == 1
    assert ex(h) == before and not os.path.exists(p)


def test_watcher_restores_after_owner_killed(window, tmp_path):
    """숨긴 프로세스를 강제로 죽여도(정리 코드가 못 돎) 지킴이가 몇 초 안에 되돌린다."""
    h = window()
    before = ex(h)
    code = ("import sys,time; sys.path.insert(0, r'%s'); from engine import win_hide; "
            "w = win_hide.HiddenWindow(%d, root=r'%s'); w.apply(); print('hidden', flush=True); time.sleep(60)"
            % (ROOT, h, str(tmp_path)))
    owner = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, cwd=ROOT)
    assert owner.stdout.readline().strip() == "hidden"
    assert win_hide.is_hidden(h)
    owner.kill()                                               # 강제 종료
    owner.wait(5)
    end = time.time() + 10
    while time.time() < end and ex(h) != before:
        time.sleep(0.2)
    assert ex(h) == before


def test_leftover_record_is_replaced(window, tmp_path):
    """같은 프로세스가 놓친 기록이 남아 있어도 그냥 넘어가지 않고 다시 숨긴다(숨긴 척 금지)."""
    h = window()
    before = ex(h)
    a = win_hide.HiddenWindow(h, root=str(tmp_path), watch=False)
    a.apply()
    a.path = None                                              # 기록을 놓친 상황
    b = win_hide.HiddenWindow(h, root=str(tmp_path), watch=False)
    b.apply()
    assert b.path and win_hide.is_hidden(h)
    b.restore()
    assert ex(h) == before


def test_hidden_by_other_live_program_is_not_stacked(window, tmp_path):
    """살아 있는 다른 프로그램이 숨겨 둔 창은 겹쳐 숨기지 않고, 그쪽이 끝나면 원래대로."""
    h = window()
    before = ex(h)
    code = ("import sys,time; sys.path.insert(0, r'%s'); from engine import win_hide; "
            "w = win_hide.HiddenWindow(%d, root=r'%s', watch=False); w.apply(); print('hidden', flush=True); "
            "sys.stdin.readline(); w.restore(); print('done', flush=True)" % (ROOT, h, str(tmp_path)))
    other = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, cwd=ROOT)
    assert other.stdout.readline().strip() == "hidden"
    mine = win_hide.HiddenWindow(h, root=str(tmp_path), watch=False)
    mine.apply()
    assert mine.nested and not mine.path
    mine.restore()
    assert win_hide.is_hidden(h)                               # 내 쪽이 끝나도 그쪽 것은 그대로
    other.stdin.write("go\n")
    other.stdin.flush()
    assert other.stdout.readline().strip() == "done"
    other.wait(5)
    assert ex(h) == before

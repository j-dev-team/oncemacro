"""명령을 메모리 상한·시간 제한을 걸고 돌린다(윈도우 작업 개체). 넘으면 그 명령과 자식 프로세스까지 바로 끝낸다.

사용: venv\\Scripts\\python.exe scripts/run_limited.py [--mem-gb 3] [--timeout 120] -- 명령 ...
예:   venv\\Scripts\\python.exe scripts/run_limited.py --mem-gb 3 --timeout 120 -- venv\\Scripts\\python.exe -m pytest tests/gui_v3 -q

끝 코드: 명령의 끝 코드 그대로. 시간 초과는 124, 메모리 초과로 끝나면 137 을 돌려주고 이유를 한 줄 찍는다.
"""
import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import time
from ctypes import wintypes

JobObjectExtendedLimitInformation = 9
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
PROCESS_ALL_ACCESS = 0x1F0FFF


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class BASIC(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD)]


class EXTENDED(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mem-gb", type=float, default=3.0)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd
    if not cmd:
        ap.error("돌릴 명령이 없다")
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.OpenProcess.restype = wintypes.HANDLE
    job = k32.CreateJobObjectW(None, None)
    info = EXTENDED()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_JOB_MEMORY | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    limit = int(a.mem_gb * 1024 ** 3)
    info.JobMemoryLimit = limit
    if not k32.SetInformationJobObject(wintypes.HANDLE(job), JobObjectExtendedLimitInformation,
                                       ctypes.byref(info), ctypes.sizeof(info)):
        sys.exit("작업 개체 설정 실패: %d" % ctypes.get_last_error())
    cmd[0] = os.path.abspath(shutil.which(cmd[0]) or cmd[0])   # 'venv/Scripts/python.exe' 같은 상대 경로도 되게
    p = subprocess.Popen(cmd)
    h = k32.OpenProcess(PROCESS_ALL_ACCESS, False, p.pid)
    if not h or not k32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(h)):
        p.kill()
        sys.exit("작업 개체에 넣기 실패: %d" % ctypes.get_last_error())
    end = time.time() + a.timeout
    code = None
    while code is None:
        code = p.poll()
        if code is None and time.time() > end:
            k32.TerminateJobObject(wintypes.HANDLE(job), 124)
            p.wait()
            print(f"[제한] 시간 초과 {a.timeout:.0f}초 → 끝냄", flush=True)
            code = 124
            break
        if code is None:
            time.sleep(0.2)
    q = EXTENDED()
    k32.QueryInformationJobObject(wintypes.HANDLE(job), JobObjectExtendedLimitInformation,
                                  ctypes.byref(q), ctypes.sizeof(q), None)
    peak = q.PeakJobMemoryUsed / 1024 ** 3
    if code != 124 and q.PeakJobMemoryUsed >= limit * 0.98 and code != 0:
        print(f"[제한] 메모리 상한 {a.mem_gb:g}GB 에 닿아 끝남", flush=True)
        code = 137
    print(f"[제한] 최고 메모리 {peak:.2f}GB, 끝 코드 {code}", flush=True)
    k32.CloseHandle(wintypes.HANDLE(job))
    sys.exit(code)


if __name__ == "__main__":
    main()

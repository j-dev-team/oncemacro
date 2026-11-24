"""메모리 매크로 시험용 작은 프로그램: 값을 들고 있다가 정해진 대로 바꾼다(화면 없음).

첫 줄에 JSON 으로 {pid, int, double, text, text16, ptr} 주소를 찍는다.
- int: 100 에서 시작, 'step' 초마다 +7 (step=0 이면 표준 입력 한 줄마다 +7)
- double: 3.5, text: "가게 열림"(UTF-8), text16: "hello 세계"(UTF-16)
- ptr: int 를 가리키는 포인터를 담은 구조체의 주소 (pointers [0] 으로 따라가면 int)
"""
import ctypes
import json
import sys
import time

step = float(sys.argv[1]) if len(sys.argv) > 1 else 0.3
iv = ctypes.c_int32(100)
dv = ctypes.c_double(3.5)
tv = ctypes.create_string_buffer("가게 열림".encode("utf-8"), 64)
wv = ctypes.create_unicode_buffer("hello 세계", 64)


class Holder(ctypes.Structure):
    _fields_ = [("pad", ctypes.c_uint64), ("p", ctypes.c_void_p)]


holder = Holder(0, ctypes.addressof(iv))
print(json.dumps({"pid": __import__("os").getpid(), "int": ctypes.addressof(iv), "double": ctypes.addressof(dv),
                  "text": ctypes.addressof(tv), "text16": ctypes.addressof(wv), "ptr": ctypes.addressof(holder)}),
      flush=True)
end = time.time() + 120
while time.time() < end:
    if step > 0:
        time.sleep(step)
    else:
        if not sys.stdin.readline():
            break
    iv.value += 7

"""메모리 매크로: 저장 파일에서 숫자 칸 찾기·고치기(혼자 하는 게임용). Qt 없음.

되는 형식:
- 언리얼 저장(GVAS): IntProperty·Int64Property·FloatProperty·DoubleProperty 를 이름으로 찾아 바꾼다.
  (2026-11-18 '여름의 아지트' Money 로 확인. 게임을 다시 불러와야 반영됨)
- JSON 저장(유니티 등에서 흔함): 숫자 값을 '경로.이름'으로 찾아 바꾼다.
- 글자 설정 파일(이름=숫자): 줄 단위로 찾아 바꾼다.
렌파이 저장(.save = 압축 + 파이썬 피클)은 고치지 않는다(조사 메모: docs/메모리_매크로_설계.md).
바꾸기 전 원본은 같은 폴더의 '_백업_날짜시각' 폴더로 복사하고, 바꾼 것은 logs/memory/writes.jsonl 에 남긴다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import struct
import time
from typing import List, Optional

from .i18n import t
from .memory import MemoryError_

GVAS_TYPES = {"IntProperty": ("<i", 4), "Int64Property": ("<q", 8), "FloatProperty": ("<f", 4),
              "DoubleProperty": ("<d", 8), "UInt32Property": ("<I", 4), "ByteProperty": None}


def kind_of(path: str) -> str:
    with open(path, "rb") as f:
        head = f.read(64)
    if head[:4] == b"GVAS":
        return "gvas"
    if path.lower().endswith((".ini", ".cfg", ".txt", ".conf")):
        return "text"
    s = head.lstrip()
    if s[:1] in (b"{", b"["):
        return "json"
    if path.lower().endswith(".save") and head[:2] == b"PK":
        return "renpy"
    return "unknown"


# ------------------------------------------------------------ 언리얼
def _gvas_fields(b: bytes) -> List[dict]:
    out = []
    for tname, spec in GVAS_TYPES.items():
        if spec is None:
            continue
        fmt, size = spec
        tb = tname.encode() + b"\x00"
        tag = struct.pack("<i", len(tb)) + tb
        i = 0
        while True:
            i = b.find(tag, i)
            if i < 0:
                break
            j = i + len(tag)
            a, c = struct.unpack_from("<ii", b, j) if j + 9 + size <= len(b) else (None, None)
            ok = (a, c) in ((size, 0), (0, size)) and b[j + 8] == 0
            # 이름: 바로 앞의 [길이][이름\0]
            name = None
            for back in range(2, 80):
                k = i - back
                if k < 4:
                    break
                ln = struct.unpack_from("<i", b, k - 4)[0]
                if ln == back and b[i - 1] == 0:
                    try:
                        name = b[k:i - 1].decode("ascii")
                    except UnicodeDecodeError:
                        name = None
                    break
            if ok and name and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
                v = struct.unpack_from(fmt, b, j + 9)[0]
                out.append({"name": name, "type": tname, "offset": j + 9, "fmt": fmt,
                            "value": round(v, 6) if isinstance(v, float) else v})
            i = j
    out.sort(key=lambda f: f["offset"])
    seen = {}
    for f in out:                                           # 같은 이름이 여러 번이면 '이름#2'
        seen[f["name"]] = seen.get(f["name"], 0) + 1
        if seen[f["name"]] > 1:
            f["name"] = f"{f['name']}#{seen[f['name']]}"
    return out


# ------------------------------------------------------------ JSON·글자
def _json_fields(d, prefix="") -> List[dict]:
    out = []
    if isinstance(d, dict):
        for k, v in d.items():
            out += _json_fields(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(d, list):
        for i, v in enumerate(d):
            out += _json_fields(v, f"{prefix}[{i}]")
    elif isinstance(d, (int, float)) and not isinstance(d, bool):
        out.append({"name": prefix, "type": "json", "value": d})
    return out


_TEXT_RE = re.compile(r"^(\s*)([A-Za-z0-9_.\[\]]+)(\s*[=:]\s*)(-?\d+(?:\.\d+)?)(\s*)$")


def fields(path: str) -> List[dict]:
    """[{name, type, value, ...}] — 바꿀 수 있는 숫자 칸들."""
    k = kind_of(path)
    if k == "gvas":
        with open(path, "rb") as f:
            return _gvas_fields(f.read())
    if k == "json":
        with open(path, encoding="utf-8-sig") as f:
            return _json_fields(json.load(f))
    if k == "text":
        out = []
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            for n, line in enumerate(f.read().splitlines()):
                m = _TEXT_RE.match(line)
                if m:
                    v = m.group(4)
                    out.append({"name": m.group(2), "type": "text", "line": n, "value": float(v) if "." in v else int(v)})
        return out
    if k == "renpy":
        raise MemoryError_(t("렌파이 저장 파일은 고칠 수 없어요(압축된 파이썬 자료). 게임 안 개발자 기능을 쓰는 길을 찾아보세요"))
    raise MemoryError_(t("모르는 저장 형식이에요"))


def find(path: str, text: str) -> List[dict]:
    q = (text or "").lower().replace(" ", "")
    return [f for f in fields(path) if not q or q in f["name"].lower()]


def backup(path: str) -> str:
    folder = os.path.dirname(os.path.abspath(path))
    dst = folder + "_백업_" + time.strftime("%Y%m%d_%H%M%S")
    if not os.path.exists(dst):
        shutil.copytree(folder, dst)
    return dst


def set_value(path: str, name: str, value, root: Optional[str] = None) -> dict:
    """name 칸을 value 로. 돌려줌: {old, new, backup}. 원본 폴더는 먼저 백업."""
    fs = {f["name"]: f for f in fields(path)}
    f = fs.get(name)
    if f is None:
        raise MemoryError_(t("저장 파일에 '{name}' 칸이 없어요", name=name))
    bk = backup(path)
    k = kind_of(path)
    if k == "gvas":
        with open(path, "rb") as fh:
            b = bytearray(fh.read())
        v = float(value) if f["fmt"] in ("<f", "<d") else int(float(value))
        struct.pack_into(f["fmt"], b, f["offset"], v)
        with open(path, "wb") as fh:
            fh.write(bytes(b))
    elif k == "json":
        with open(path, encoding="utf-8-sig") as fh:
            d = json.load(fh)
        parts = re.findall(r"[^.\[\]]+|\[\d+\]", name)
        cur = d
        for p in parts[:-1]:
            cur = cur[int(p[1:-1])] if p.startswith("[") else cur[p]
        last = parts[-1]
        nv = value if isinstance(f["value"], float) else int(float(value))
        if last.startswith("["):
            cur[int(last[1:-1])] = nv
        else:
            cur[last] = nv
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False)
    else:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            lines = fh.read().splitlines()
        m = _TEXT_RE.match(lines[f["line"]])
        lines[f["line"]] = m.group(1) + m.group(2) + m.group(3) + str(value) + m.group(5)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    from .memwrite import _log
    _log({"save_file": path, "field": name, "old": f["value"], "value": value, "backup": bk}, root)
    return {"old": f["value"], "new": value, "backup": bk}

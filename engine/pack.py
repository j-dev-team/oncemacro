"""매크로 묶음 주고받기: 매크로 하나(+ 그 매크로가 부르는 매크로들 + 쓰는 그림)를 파일 하나(.macropack, zip)로.

내보내기: pack.json(매크로 이름들·만든 화면 크기·배율·만든 날) + macros/<이름>.json + image/<상대경로>
가져오기: 같은 이름이 있으면 '이름 (2)'로 바꿔 넣고(부르는 쪽 이름도 함께 바꿈), 그림은 같은 자리에 같은 내용이면 그대로,
         다르면 다른 이름으로. 만든 화면의 배율·크기가 지금과 다르면 '그림이 안 맞을 수 있음'을 알려 준다.
Qt 없음.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import time
import zipfile
from typing import Dict, List, Optional

from .i18n import t

EXT = ".macropack"


def screen_info() -> dict:
    try:
        u = ctypes.windll.user32
        w, h = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
        dpi = 96
        try:
            dpi = u.GetDpiForSystem()
        except Exception:
            pass
        return {"width": int(w), "height": int(h), "scale": round(dpi / 96, 2)}
    except Exception:
        return {}


def _all_steps(macro: dict):
    out = []

    def go(lst):
        for s in lst or []:
            if not isinstance(s, dict):
                continue
            out.append(s)
            for k in ("steps", "then", "else"):
                if isinstance(s.get(k), list):
                    go(s[k])
    go(macro.get("steps"))
    return out


def _images_in(obj, found: set):
    """매크로 안 모든 'image' 칸(대상·조건 안 포함)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "image" and isinstance(v, str) and v:
                found.add(v)
            else:
                _images_in(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _images_in(v, found)


def collect(store, name: str) -> Dict[str, dict]:
    """name 과 그것이 부르는 매크로들(재귀)."""
    out: Dict[str, dict] = {}
    todo = [name]
    while todo:
        n = todo.pop()
        if n in out or not store.exists(n):
            continue
        m = store.load(n)
        out[n] = m
        for s in _all_steps(m):
            if s.get("type") == "call" and s.get("macro"):
                todo.append(s["macro"])
    return out


def export(store, name: str, path: str, image_root: str) -> dict:
    macros = collect(store, name)
    imgs: set = set()
    for m in macros.values():
        _images_in(m, imgs)
    missing = []
    if not path.lower().endswith(EXT):
        path += EXT
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("pack.json", json.dumps({"main": name, "macros": sorted(macros), "screen": screen_info(),
                                            "made": time.strftime("%Y-%m-%d %H:%M"), "format": 1},
                                           ensure_ascii=False, indent=1))
        for n, m in macros.items():
            z.writestr(f"macros/{n}.json", json.dumps(m, ensure_ascii=False, indent=1))
        for rel in sorted(imgs):
            src = os.path.join(image_root, *rel.replace("\\", "/").split("/"))
            if os.path.exists(src):
                z.write(src, "image/" + rel.replace("\\", "/"))
            else:
                missing.append(rel)
    return {"path": path, "macros": sorted(macros), "images": len(imgs) - len(missing), "missing": missing}


def peek(path: str) -> dict:
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read("pack.json").decode("utf-8"))


def _rename_calls(m: dict, ren: Dict[str, str]):
    for s in _all_steps(m):
        if s.get("type") == "call" and s.get("macro") in ren:
            s["macro"] = ren[s["macro"]]


def _replace_images(obj, ren: Dict[str, str]):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "image" and isinstance(v, str) and v in ren:
                obj[k] = ren[v]
            else:
                _replace_images(v, ren)
    elif isinstance(obj, list):
        for v in obj:
            _replace_images(v, ren)


def import_pack(store, path: str, image_root: str, group: Optional[str] = None) -> dict:
    """돌려줌: {added: [이름…], renamed: {원래: 새}, images, warnings: [...]}"""
    info = peek(path)
    warnings: List[str] = []
    here, there = screen_info(), info.get("screen") or {}
    if there and here and (there.get("scale") != here.get("scale")):
        warnings.append(t("만든 컴퓨터의 화면 배율({a}배)과 지금({b}배)이 달라 그림 찾기가 안 맞을 수 있어요 — 디스플레이 배율을 같게 하거나 그림을 다시 잘라 주세요",
                          a=there.get("scale"), b=here.get("scale")))
    elif there and here and (there.get("width"), there.get("height")) != (here.get("width"), here.get("height")):
        warnings.append(t("만든 컴퓨터의 화면 크기({a})와 지금({b})이 달라요 — 창 크기가 같으면 대개 괜찮아요",
                          a=f"{there.get('width')}x{there.get('height')}", b=f"{here.get('width')}x{here.get('height')}"))
    with zipfile.ZipFile(path) as z:
        names = [n[len("macros/"):-len(".json")] for n in z.namelist() if n.startswith("macros/") and n.endswith(".json")]
        ren = {}
        for n in names:
            if store.exists(n):
                ren[n] = store.unique_name(n)
        img_ren: Dict[str, str] = {}
        n_img = 0
        for zi in z.namelist():
            if not zi.startswith("image/") or zi.endswith("/"):
                continue
            rel = zi[len("image/"):]
            data = z.read(zi)
            dst = os.path.join(image_root, *rel.split("/"))
            if os.path.exists(dst):
                with open(dst, "rb") as f:
                    if hashlib.sha1(f.read()).digest() == hashlib.sha1(data).digest():
                        continue                         # 같은 그림이 이미 있음
                stem, ext = os.path.splitext(rel)
                k = 2
                while os.path.exists(os.path.join(image_root, *(f"{stem}_{k}{ext}").split("/"))):
                    k += 1
                img_ren[rel] = f"{stem}_{k}{ext}"
                dst = os.path.join(image_root, *img_ren[rel].split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(data)
            n_img += 1
        added = []
        for n in names:
            m = json.loads(z.read(f"macros/{n}.json").decode("utf-8"))
            _rename_calls(m, ren)
            _replace_images(m, img_ren)
            m["name"] = ren.get(n, n)
            store.save(m, draft=True)
            if group:
                try:
                    store.move_to_group(m["name"], group)
                except Exception:
                    pass
            added.append(m["name"])
    return {"added": added, "renamed": ren, "images": n_img, "image_renamed": img_ren, "warnings": warnings,
            "main": ren.get(info.get("main"), info.get("main"))}

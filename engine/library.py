"""
매크로 저장소. call 스텝이 이름으로 다른 매크로를 불러올 때 쓴다.
"""
from __future__ import annotations

import os
import re
from typing import Dict, List
from .i18n import t

from .model import ensure_valid, load_macro, save_macro

_BAD_CHARS = re.compile(r'[\\/:*?"<>|]')


class MacroNotFound(KeyError):
    pass


class Library:
    def load(self, name: str) -> dict:
        raise NotImplementedError

    def names(self) -> List[str]:
        raise NotImplementedError


class DictLibrary(Library):
    """메모리 저장소 (테스트용)."""

    def __init__(self, macros: Dict[str, dict] = None):
        self.macros = dict(macros or {})

    def add(self, macro: dict) -> None:
        self.macros[macro["name"]] = ensure_valid(macro)

    def load(self, name):
        if name not in self.macros:
            raise MacroNotFound(name)
        return self.macros[name]

    def names(self):
        return sorted(self.macros)


class FileLibrary(Library):
    """macros_v2/<이름>.json"""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)

    def path_for(self, name: str) -> str:
        if not name or _BAD_CHARS.search(name) or name.strip(". ") != name.strip():
            raise ValueError(t("매크로 이름에 쓸 수 없는 문자가 있음: {name}", name=repr(name)))
        return os.path.join(self.root, f"{name}.json")

    def load(self, name):
        p = self.path_for(name)
        if not os.path.exists(p):
            raise MacroNotFound(name)
        return load_macro(p)

    def save(self, macro: dict) -> str:
        p = self.path_for(macro["name"])
        save_macro(macro, p)
        return p

    def names(self):
        if not os.path.isdir(self.root):
            return []
        # '_' 로 시작하는 파일(_groups.json 등)은 매크로가 아님
        return sorted(f[:-5] for f in os.listdir(self.root)
                      if f.endswith(".json") and not f.startswith("_"))

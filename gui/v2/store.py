"""
macros_v2/ 매크로 저장소 (Qt 없음). 목록·그룹·만들기·복사·이름 바꾸기·삭제·핫키.

- 그룹: macros_v2/_groups.json = {"그룹이름": ["매크로", ...], ...}. 그룹에 없는 매크로는 맨 위(루트)에 보인다.
- 이름 바꾸기는 그 매크로를 call 하는 다른 매크로도 같이 고친다.
- 삭제 전에 callers_of() 로 호출하는 매크로가 있는지 확인한다(화면에서 경고).
- 검사 실패한 파일도 목록에는 보여야 하므로 load() 는 검사하지 않고 읽는다. 저장은 반드시 검사를 통과해야 한다.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Dict, List, Optional, Tuple

from engine.library import FileLibrary
from engine.model import MacroError, new_macro, save_macro, validate_macro
from .i18n import tr
from .model import walk_dict

GROUPS_FILE = "_groups.json"


class StoreError(Exception):
    pass


class MacroStore:
    def __init__(self, root: Optional[str] = None):
        if root is None:
            from engine.real import MACRO_ROOT
            root = MACRO_ROOT
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        self.lib = FileLibrary(self.root)

    # ------------------------------------------------------------ 매크로
    def names(self) -> List[str]:
        return self.lib.names()

    def path(self, name: str) -> str:
        return self.lib.path_for(name)

    def exists(self, name: str) -> bool:
        try:
            return os.path.exists(self.path(name))
        except ValueError:
            return False

    def load(self, name: str) -> dict:
        """검사 없이 읽는다(형식 오류 파일도 목록·편집에 보이도록)."""
        with open(self.path(name), "r", encoding="utf-8") as f:
            return json.load(f)

    def check(self, macro: dict) -> List[str]:
        return validate_macro(macro)

    def save(self, macro: dict, old_name: Optional[str] = None, draft: bool = False) -> List[str]:
        """검사 후 저장. old_name 이 있고 이름이 바뀌었으면 이름 바꾸기 처리.
        draft=True 면 검사 오류가 있어도 저장한다(편집 중간 저장). 그런 파일은 엔진이 불러올 때 검사에서 걸려
        실행·시험·핫키·예약·호출이 모두 막힌다.
        돌려주는 값: 이름 바꾸기로 함께 고친 호출 매크로 목록."""
        errors = validate_macro(macro)
        if errors and not draft:
            raise MacroError(errors)
        write = _write_draft if errors else save_macro
        name = macro["name"]
        self.lib.path_for(name)       # 이름 검사
        updated: List[str] = []
        if old_name and old_name != name:
            if self.exists(name):
                raise StoreError(tr("'{name}' 매크로가 이미 있음").format(name=name))
            write(macro, self.path(name))
            if self.exists(old_name):
                os.remove(self.path(old_name))
            self._rename_in_groups(old_name, name)
            updated = self._rename_callers(old_name, name)
        else:
            write(macro, self.path(name))
        return updated

    def unique_name(self, base: str) -> str:
        if not self.exists(base):
            return base
        n = 2
        while self.exists(f"{base} ({n})"):
            n += 1
        return f"{base} ({n})"

    def create(self, name: str, window_title: Optional[str] = None, group: Optional[str] = None) -> dict:
        if self.exists(name):
            raise StoreError(tr("'{name}' 매크로가 이미 있음").format(name=name))
        m = new_macro(name)
        if window_title:
            m = {"version": m["version"], "name": name, "window": {"title": window_title},
                 "repeat": m["repeat"], "steps": []}
        self.save(m)
        if group:
            self.move_to_group(name, group)
        return m

    def add(self, macro: dict, group: Optional[str] = None) -> str:
        """붙여넣기: 같은 이름이 있으면 '(2)' 를 붙여 저장. 저장된 이름을 돌려준다."""
        m = copy.deepcopy(macro)
        m["name"] = self.unique_name(m.get("name") or tr("새 매크로"))
        self.save(m)
        if group:
            self.move_to_group(m["name"], group)
        return m["name"]

    def copy(self, name: str) -> str:
        m = self.load(name)
        new = self.unique_name(f"{name} {tr('복사')}")
        m["name"] = new
        self.save(m)
        g = self.group_of(name)
        if g:
            self.move_to_group(new, g, after=name)
        return new

    def rename(self, old: str, new: str) -> List[str]:
        new = new.strip()
        if not new or new == old:
            return []
        m = self.load(old)
        m["name"] = new
        return self.save(m, old_name=old)

    def delete(self, name: str) -> None:
        if self.exists(name):
            os.remove(self.path(name))
        groups = self.groups()
        changed = False
        for g, items in groups.items():
            if name in items:
                items.remove(name)
                changed = True
        if changed:
            self.save_groups(groups)

    def callers_of(self, name: str) -> List[str]:
        """name 을 call 하는 매크로들."""
        out = []
        for other in self.names():
            if other == name:
                continue
            try:
                m = self.load(other)
            except Exception:
                continue
            if any(isinstance(s, dict) and s.get("type") == "call" and s.get("macro") == name
                   for _, s in walk_dict(m.get("steps", []))):
                out.append(other)
        return out

    def _rename_callers(self, old: str, new: str) -> List[str]:
        updated = []
        for other in self.callers_of(old):
            m = self.load(other)
            for _, s in walk_dict(m.get("steps", [])):
                if isinstance(s, dict) and s.get("type") == "call" and s.get("macro") == old:
                    s["macro"] = new
            if not validate_macro(m):
                save_macro(m, self.path(other))
                updated.append(other)
        return updated

    # ------------------------------------------------------------ 핫키
    def hotkeys(self) -> Dict[str, Tuple[str, str]]:
        """{매크로: (실행 핫키, 정지 핫키)} — 핫키가 있는 매크로만."""
        out = {}
        for name in self.names():
            try:
                m = self.load(name)
            except Exception:
                continue
            run, stop = (m.get("run_hotkey") or "").strip(), (m.get("stop_hotkey") or "").strip()
            if run or stop:
                out[name] = (run, stop)
        return out

    def set_hotkeys(self, name: str, run: str, stop: str) -> None:
        m = self.load(name)
        for key, val in (("run_hotkey", run), ("stop_hotkey", stop)):
            if val:
                m[key] = val
            else:
                m.pop(key, None)
        self.save(m)

    # ------------------------------------------------------------ 그룹
    @property
    def groups_path(self) -> str:
        return os.path.join(self.root, GROUPS_FILE)

    def groups(self) -> Dict[str, List[str]]:
        try:
            with open(self.groups_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {str(k): [str(x) for x in (v or [])] for k, v in data.items()}
        except FileNotFoundError:
            pass
        except Exception:
            pass
        return {}

    def save_groups(self, groups: Dict[str, List[str]]) -> None:
        tmp = self.groups_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(groups, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.groups_path)

    def group_of(self, name: str) -> Optional[str]:
        for g, items in self.groups().items():
            if name in items:
                return g
        return None

    def move_to_group(self, name: str, group: Optional[str], after: Optional[str] = None) -> None:
        groups = self.groups()
        for items in groups.values():
            while name in items:
                items.remove(name)
        if group:
            items = groups.setdefault(group, [])
            if after and after in items:
                items.insert(items.index(after) + 1, name)
            else:
                items.append(name)
        self.save_groups(groups)

    def create_group(self, group: str) -> None:
        group = group.strip()
        if not group:
            raise StoreError(tr("그룹 이름이 비어 있음"))
        groups = self.groups()
        if group in groups:
            raise StoreError(tr("'{name}' 그룹이 이미 있음").format(name=group))
        groups[group] = []
        self.save_groups(groups)

    def rename_group(self, old: str, new: str) -> None:
        new = new.strip()
        groups = self.groups()
        if old not in groups or not new or new == old:
            return
        if new in groups:
            raise StoreError(tr("'{name}' 그룹이 이미 있음").format(name=new))
        groups = {(new if k == old else k): v for k, v in groups.items()}
        self.save_groups(groups)

    def delete_group(self, group: str) -> None:
        """그룹만 지운다. 안의 매크로는 맨 위(루트)로."""
        groups = self.groups()
        if group in groups:
            del groups[group]
            self.save_groups(groups)

    def tree(self) -> Tuple[List[Tuple[str, List[str]]], List[str]]:
        """화면용: ([(그룹, [매크로...]), ...], 그룹 없는 매크로들). 없는 파일은 뺀다."""
        names = set(self.names())
        seen = set()
        out = []
        for g, items in self.groups().items():
            present = [n for n in items if n in names and n not in seen]
            seen.update(present)
            out.append((g, present))
        loose = sorted(n for n in names if n not in seen)
        return out, loose

    def _rename_in_groups(self, old: str, new: str) -> None:
        groups = self.groups()
        changed = False
        for items in groups.values():
            for i, n in enumerate(items):
                if n == old:
                    items[i] = new
                    changed = True
        if changed:
            self.save_groups(groups)


def _write_draft(macro: dict, path: str) -> None:
    """검사 없이 저장(편집 중간 저장용). save_macro 와 같은 방식(임시 파일 → 바꿔치기)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(macro, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

"""
값 조정 '시험 반영'(2026-11-17, 스스로 고치기 3단계). AI를 쓰지 않는다.

고치는 것(한 매크로에 한 번에 하나만 시험):
- recapture : 인식 점수가 아슬아슬한 그림을, '찾은 그 순간·그 자리'에서 같은 크기로 다시 딴다.
              새 그림을 먼저 찾고, 못 찾으면 옛 그림(예비)으로도 찾는다. 옛 그림은 지우지 않는다.
- confidence: 기준보다 살짝 모자라 못 찾는 일이 잦을 때 기준을 낮춘다(바닥 confidence_floor).
              낮추기 전, 최근 대상 창 사진들에서 '다른 자리'가 새 기준 이상으로 맞으면 거절(잘못 맞힘 검사).
- timeout   : 같은 스텝이 '시간 초과'로 자주 실패할 때 기다리는 시간을 1.5배(최대 2배, 120초).

시험 반영은 매크로 파일을 바꾸지 않고 <매크로 폴더>/_fixes/<매크로>.json(예전 _고침 이 있으면 그것) 에 둔다.
바꾸기 전 기준(최근 회차들)을 시험 시작 때 저장하고, 바꾼 뒤 회차들과 비교:
  성공률·시간이 같거나 낫고 새 종류의 실패·경고가 없으면 확정(매크로 파일에 반영, 원본 _backup),
  뚜렷이 나빠지면 바로 되돌림, 회차가 모자라면 시험 반영 상태로 더 지켜봄.
매크로 파일이 시험 중에 바뀌면 시험을 취소(되돌림)한다.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import statistics
import time
from typing import Any, Dict, List, Optional, Tuple

from .i18n import t

tr_ = t

TUNE_DEFAULTS = {"trial_min_seconds": 600, "max_conf_drop": 0.05, "confidence_cooldown_s": 86400,
                 "trial_iterations": 10, "baseline_min": 8, "baseline_window": 20, "confidence_floor": 0.7,
                 "recapture_cooldown_s": 3600, "near_miss_gap": 0.08, "near_miss_count": 3,
                 "timeout_fail_count": 3, "timeout_factor": 1.5, "timeout_max_factor": 2.0, "timeout_cap": 120.0}


def reason_kind(reason: str) -> str:
    """실패 이유를 '종류'로(숫자를 지움) — 새 종류의 실패인지 비교용."""
    return re.sub(r"[\d.]+", "#", reason or "").strip()[:80]


def _file_hash(path: str) -> str:
    """매크로 파일 지문. 막힘 해결 규칙(rescues)이 더해지는 건 '사람이 매크로를 고친 것'이 아니라 빼고 계산."""
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        if isinstance(d, dict):
            d.pop("rescues", None)
        return hashlib.sha1(json.dumps(d, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    except Exception:
        try:
            with open(path, "rb") as fh:
                return hashlib.sha1(fh.read()).hexdigest()
        except Exception:
            return ""


def metrics(its: List[dict]) -> dict:
    n = len(its)
    ok = [i for i in its if i.get("ok")]
    fails = sorted({f"{i.get('fail_path', '')}|{reason_kind(i.get('reason', ''))}" for i in its if not i.get("ok")})
    return {"n": n, "ok_rate": round(len(ok) / n, 3) if n else 0.0,
            "median": round(statistics.median(i["seconds"] for i in ok), 2) if ok else None,
            "fail_kinds": fails, "warn_kinds": sorted({w for i in its for w in i.get("warnings", [])})}


class Tuner:
    """매크로 하나의 시험 반영 상태."""

    def __init__(self, macro_root: str, name: str, macro_path: Optional[str] = None):
        from .fsnames import pick
        self.dir = pick(macro_root, "_고침")              # 11-24: 새로는 _fixes(예전 _고침 이 있으면 그대로)
        self.name = name
        self.path = os.path.join(self.dir, "".join(ch for ch in name if ch not in '\\/:*?"<>|') + ".json")
        self.macro_path = macro_path
        self.state = {"trial": None, "history": [], "cooldown": {}}
        try:
            with open(self.path, encoding="utf-8") as fh:
                self.state.update(json.load(fh))
        except Exception:
            pass

    def save(self):
        os.makedirs(self.dir, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.state, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    # ---- 실행 중 쓰는 값
    @property
    def trial(self) -> Optional[dict]:
        return self.state.get("trial")

    def images_for(self, image: str) -> List[str]:
        t = self.trial
        if t and t["kind"] == "recapture" and t["target"] == image:
            return [t["new"], image]                       # 새 그림 먼저, 못 찾으면 옛 그림(예비)
        return [image]

    def confidence_for(self, image: str, default: float) -> float:
        t = self.trial
        if t and t["kind"] == "confidence" and t["target"] == image:
            return float(t["new"])
        return default

    def timeout_for(self, step_key: str, default):
        t = self.trial
        if t and t["kind"] == "timeout" and t["target"] == step_key:
            return float(t["new"])
        return default

    def can_try(self, key: str, cfg: dict, now: float) -> bool:
        if self.trial:
            return False                                   # 한 번에 하나만
        last = float(self.state.get("cooldown", {}).get(key, 0))
        return now - last >= float(cfg["recapture_cooldown_s"])

    # ---- 시험 시작·평가
    def start(self, kind: str, target: str, new: Any, old: Any, baseline_its: List[dict], cfg: dict,
              why: str, now: float) -> Optional[dict]:
        base = baseline_its[-int(cfg["baseline_window"]):]
        if len(base) < int(cfg["baseline_min"]) or self.trial:
            return None                                    # 기준 회차가 모자라면 시작 안 함
        t = {"id": f"{int(now)}", "kind": kind, "target": target, "new": new, "old": old, "why": why,
             "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
             "started_ts": now, "baseline": metrics(base), "post": [], "macro_hash": _file_hash(self.macro_path) if self.macro_path else ""}
        self.state["trial"] = t
        self.state.setdefault("cooldown", {})[f"{kind}:{target}"] = now
        self.save()
        return t

    def on_iteration(self, it: dict, cfg: dict) -> Optional[Tuple[str, dict]]:
        """회차 하나를 시험에 더하고 판단. 돌려줌: ('applied'|'reverted', trial) 또는 None(계속 지켜봄)."""
        t = self.trial
        if not t:
            return None
        if self.macro_path and t.get("macro_hash") and _file_hash(self.macro_path) != t["macro_hash"]:
            return self._finish("reverted", t, tr_("매크로 파일이 시험 중에 바뀜"))
        t["post"].append({k: it.get(k) for k in ("ok", "seconds", "reason", "fail_path", "warnings")})
        post = t["post"]
        base = t["baseline"]
        # 뚜렷한 퇴보: 기준에는 없던 실패가 연속 2번
        if len(post) >= 2 and not post[-1]["ok"] and not post[-2]["ok"] and base["ok_rate"] >= 0.95:
            return self._finish("reverted", t, tr_("기준에 없던 연속 실패"))
        started = t.get("started_ts") or 0
        watched = time.time() - float(started) if started else 1e9
        if len(post) < int(cfg["trial_iterations"]) or watched < float(cfg.get("trial_min_seconds", 600)):
            self.save()
            return None                                    # 회차 수와 지켜본 시간을 둘 다 채워야 판단
        m = metrics(post)
        new_fails = [k for k in m["fail_kinds"] if k not in base["fail_kinds"]]
        new_warns = [k for k in m["warn_kinds"] if k not in base["warn_kinds"]
                     and not (t["kind"] == "confidence" and k == "score_low:" + str(t["target"]))]   # 기준을 낮추면 생기는 '아슬아슬' 알림은 자기 탓이라 뺌
        slower = (m["median"] is not None and base["median"] is not None and m["median"] > base["median"] * 1.2)
        if m["ok_rate"] >= base["ok_rate"] and not slower and not new_fails and not new_warns:
            return self._finish("applied", t, tr_("성공률·시간이 같거나 나음, 새 실패 없음"), m)
        return self._finish("reverted", t, tr_("나빠짐") + (tr_(" (새 실패 {n}종)", n=len(new_fails)) if new_fails else ""), m)

    def revert(self, why: str = "") -> Optional[dict]:
        t = self.trial
        return self._finish("reverted", t, why or tr_("사람이 되돌림"))[1] if t else None

    def _finish(self, status: str, t: dict, why: str, post_metrics: Optional[dict] = None):
        t = dict(t, status=status, result_why=why, finished=time.strftime("%Y-%m-%d %H:%M:%S"),
                 post_metrics=post_metrics or metrics(t.get("post", [])))
        self.state["trial"] = None
        self.state.setdefault("history", []).append({k: v for k, v in t.items() if k != "post"})
        self.save()
        return status, t


# ---------------------------------------------------------------- 확정: 매크로 파일에 반영(원본 백업)

def apply_to_macro(macro: dict, trial: dict) -> dict:
    """확정된 시험을 매크로 JSON 에 반영한 새 사본."""
    m = copy.deepcopy(macro)
    kind, target, new = trial["kind"], trial["target"], trial["new"]

    def walk(steps):
        for s in steps or []:
            if not isinstance(s, dict):
                continue
            for key in ("target", "from", "to", "what"):
                tg = s.get(key)
                if isinstance(tg, dict) and tg.get("image") == target:
                    if kind == "recapture":
                        tg["image"] = new
                        fb = [x for x in tg.get("fallback_images", []) if x != target]
                        tg["fallback_images"] = [target] + fb          # 옛 그림은 예비로 남김
                    elif kind == "confidence":
                        tg["confidence"] = float(new)
            for key in ("until", "while", "cond"):
                c = s.get(key)
                if isinstance(c, dict):
                    _walk_cond(c)
            if kind == "timeout" and (s.get("id") == target):
                s["timeout"] = float(new)
            for key in ("steps", "then", "else"):
                walk(s.get(key))

    def _walk_cond(c):
        for k in ("exists", "gone"):
            tg = c.get(k)
            if isinstance(tg, dict) and tg.get("image") == target:
                if kind == "recapture":
                    tg["image"] = new
                    tg["fallback_images"] = [target] + [x for x in tg.get("fallback_images", []) if x != target]
                elif kind == "confidence":
                    tg["confidence"] = float(new)
        if "not" in c and isinstance(c["not"], dict):
            _walk_cond(c["not"])
        for k in ("all", "any"):
            for x in c.get(k) or []:
                if isinstance(x, dict):
                    _walk_cond(x)

    walk(m.get("steps"))
    if kind == "timeout" and "/" in str(target):          # id 가 없는 스텝은 '경로|해시' 키 — 경로로 찾아 반영
        path, _, h = str(target).partition("|")
        s = _step_at(m, path)
        if s is not None and step_hash(s) == h:
            s["timeout"] = float(new)
    return m


def step_hash(step: dict) -> str:
    s = {k: v for k, v in step.items() if k not in ("timeout",)}
    return hashlib.sha1(json.dumps(s, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:10]


def step_key(step: dict, path: str) -> str:
    return str(step.get("id") or f"{path.replace('[', '/').replace(']', '').replace('.', '/')}|{step_hash(step)}")


def _step_at(macro: dict, path: str) -> Optional[dict]:
    """'steps/0/then/1' 꼴 경로의 스텝."""
    cur: Any = macro
    parts = [p for p in path.split("/") if p]
    try:
        i = 0
        while i < len(parts):
            key = parts[i]
            cur = cur[key]
            if i + 1 < len(parts) and parts[i + 1].isdigit():
                cur = cur[int(parts[i + 1])]
                i += 2
            else:
                i += 1
        return cur if isinstance(cur, dict) else None
    except Exception:
        return None


def backup_and_save(library, macro: dict) -> Optional[str]:
    path_for = getattr(library, "path_for", None)
    backup = None
    if path_for:
        src = path_for(macro["name"])
        if os.path.exists(src):
            bdir = os.path.join(os.path.dirname(src), "_backup")
            os.makedirs(bdir, exist_ok=True)
            safe = "".join(ch for ch in macro["name"] if ch not in '\\/:*?"<>|')
            backup = os.path.join(bdir, f"{safe}_{time.strftime('%Y%m%d_%H%M%S')}_before_tuning.json")
            shutil.copy2(src, backup)
    library.save(macro)
    return backup


# ---------------------------------------------------------------- 잘못 맞힘 검사(기준 낮추기 전)

def false_match_check(template_path: str, screens: List[Tuple[str, Tuple[int, int]]], new_conf: float,
                      old_conf: float, known_pos: Optional[Tuple[int, int]] = None, tol: int = 12) -> Tuple[bool, str]:
    """screens: [(사진 경로, 사진 왼쪽 위의 화면 좌표)]. 새 기준~옛 기준 사이 점수로 '알던 자리가 아닌 곳'이 맞으면 거절.
    사진이 하나도 없으면 검사할 수 없으므로 거절."""
    import cv2
    import numpy as np
    if not screens:
        return False, t("검사할 화면 사진이 없음")
    tpl = cv2.imdecode(np.fromfile(template_path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if tpl is None:
        return False, t("그림을 못 읽음")
    th, tw = tpl.shape[:2]
    checked = 0
    for fp, origin in screens:
        img = cv2.imdecode(np.fromfile(fp, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is None or img.shape[0] < th or img.shape[1] < tw:
            continue
        res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
        res = np.nan_to_num(res)
        checked += 1
        ys, xs = np.where((res >= new_conf) & (res < old_conf))
        for y, x in zip(ys, xs):
            cx, cy = origin[0] + x + tw // 2, origin[1] + y + th // 2
            if known_pos is None or abs(cx - known_pos[0]) > tol or abs(cy - known_pos[1]) > tol:
                return False, t("다른 자리에서도 맞음({file}, 점수 {score})", file=os.path.basename(fp), score=f"{float(res[y, x]):.2f}")
    if not checked:
        return False, t("검사할 화면 사진이 없음")
    return True, t("사진 {n}장에서 잘못 맞는 곳 없음", n=checked)

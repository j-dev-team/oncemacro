"""
매크로 건강 기록(2026-11-17, 스스로 고치기 1단계). AI를 쓰지 않는다.

회차마다: 성공/실패, 걸린 시간, 지나간 스텝 경로 지문, (지정했으면) 목표 변수 값.
그림마다: 찾았을 때의 점수(최근 N번)와 그때의 기준, 마지막으로 찾은 자리.
매크로마다 logs/health/<매크로>.json 에 쌓고, 화면(매크로 정보)에 요약을 보여 준다.
2단계부터 이 기록으로 '진전 없음·점수 하락·처음 보는 창·느려짐'을 알아챈다.

매크로 JSON(선택):
  "self_heal": {"mode": "off"|"notify"|"tune"|"propose",   # 기본 off. notify=알림만, tune=값 조정까지, propose=제안까지
                "watch_vars": ["목표값"],                      # 진전 판단에 쓸 변수(없으면 스텝 경로만)
                "stall_repeats": 5, "score_window": 50, "score_margin": 0.05,
                "slow_window": 20, "slow_factor": 2.0, "slow_min_seconds": 10, "slow_count": 3}
"""
from __future__ import annotations

import hashlib
import json
import os
import statistics
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional

DEFAULTS = {"mode": "off", "propose_after_uses": 3, "watch_vars": [], "stall_repeats": 5, "score_window": 50, "score_margin": 0.05,
            "slow_window": 20, "slow_factor": 2.0, "slow_min_seconds": 10.0, "slow_count": 3}
MODES = ("off", "notify", "tune", "propose")
KEEP_ITERATIONS = 200


def config(macro: dict) -> dict:
    return {**DEFAULTS, **(macro.get("self_heal") or {})}


def _safe(name: str) -> str:
    return "".join(ch for ch in name if ch not in '\\/:*?"<>|')


class MacroHealth:
    """매크로 하나의 건강 기록(메모리 + 파일)."""

    def __init__(self, name: str, path: str, score_window: int = 50):
        self.name = name
        self.path = path
        self.iterations: List[dict] = []
        self.images: Dict[str, dict] = {}
        self.windows: List[str] = []
        self.score_window = score_window
        self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                d = json.load(fh)
            self.iterations = list(d.get("iterations", []))[-KEEP_ITERATIONS:]
            self.images = {k: dict(v) for k, v in (d.get("images") or {}).items()}
            self.windows = list(d.get("windows", []))
            self.flags = dict(d.get("flags", {}))
        except Exception:
            pass

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"name": self.name, "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "iterations": self.iterations[-KEEP_ITERATIONS:], "images": self.images,
                       "windows": self.windows[-200:], "flags": getattr(self, "flags", {})}, fh, ensure_ascii=False)
        os.replace(tmp, self.path)

    def note_image(self, image: str, score: float, found: bool, confidence: float, pos=None, gap: float = 0.08):
        if not found:
            # 기준보다 살짝 모자라 못 찾은 것(아깝게 놓침)만 따로 센다 — 기준 낮추기 판단용
            if confidence - gap <= score < confidence:
                rec = self.images.setdefault(image, {"scores": [], "confidence": confidence})
                it = len(self.iterations)                # 한 회차에 여러 번 놓쳐도 1번으로(회차 단위로 셈)
                nm = [x for x in rec.get("near_miss", []) if isinstance(x, list)]
                if nm and nm[-1][0] == it:
                    nm[-1][1] = min(nm[-1][1], round(float(score), 3))
                else:
                    nm.append([it, round(float(score), 3)])
                rec["near_miss"] = nm[-20:]
            return                      # 점수 하락은 '찾았을 때'의 점수로만 본다(안 보일 때는 원래 낮음)
        rec = self.images.setdefault(image, {"scores": [], "confidence": confidence})
        rec["confidence"] = confidence
        rec["scores"] = (rec.get("scores", []) + [round(float(score), 3)])[-self.score_window:]
        rec["last_pos"] = list(pos) if pos else rec.get("last_pos")
        rec["last_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    def note_windows(self, titles: List[str]) -> List[str]:
        """대상 프로그램의 창 제목들을 기록. 처음 보는 제목 목록을 돌려줌(맨 처음 기록 때는 기준만 잡고 빈 목록)."""
        titles = [x for x in titles if x]
        flags = self.__dict__.setdefault("flags", {})
        first = not flags.get("windows_seeded")          # 기준을 한 번 잡은 뒤로는(다른 창이 없었어도) 새 창을 알림
        flags["windows_seeded"] = True
        new = [x for x in titles if x not in self.windows]
        self.windows.extend(new)
        return [] if first else new

    def add_iteration(self, ok: bool, seconds: float, path_sig: str, watch: Dict[str, Any], reason: str = "",
                      fail_path: str = "") -> dict:
        rec = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "ok": bool(ok), "seconds": round(float(seconds), 2),
               "sig": path_sig, "watch": watch, "reason": (reason or "")[:200], "fail_path": fail_path or "",
               "warnings": []}
        self.iterations.append(rec)
        self.iterations = self.iterations[-KEEP_ITERATIONS:]
        return rec

    # ---- 알아채기(2단계). 신호가 계속되는 동안 같은 신호를 매 회차 되풀이하지 않게 flags 로 한 번만
    def check(self, cfg: dict, new_windows: Optional[List[str]] = None) -> List[dict]:
        out: List[dict] = []
        flags = self.__dict__.setdefault("flags", {})
        its = self.iterations

        # 1) 진전 없음: 목표 변수(watch_vars)를 정한 매크로만. 최근 N회 동안 경로 지문·목표 값이 그대로
        n = int(cfg["stall_repeats"])
        if cfg.get("watch_vars") and len(its) >= n:
            last = its[-n:]
            same = len({i["sig"] for i in last}) == 1 and all(i.get("watch") == last[0].get("watch") for i in last)
            if same and not flags.get("stall"):
                out.append({"kind": "stall", "detail": {"repeats": n, "watch": last[-1].get("watch")}})
            flags["stall"] = same

        # 2) 인식 점수 하락: 그림별 최근 점수 평균이 '기준 + 여유' 아래(점수 10개 이상 모였을 때)
        margin = float(cfg["score_margin"])
        for img, rec in self.images.items():
            sc = (rec.get("scores") or [])[-int(cfg["score_window"]):]
            if len(sc) < min(10, int(cfg["score_window"])):
                continue
            avg = sum(sc) / len(sc)
            low = avg < float(rec.get("confidence", 0.8)) + margin
            key = "score:" + img
            if low and not flags.get(key):
                out.append({"kind": "score_low", "detail": {"image": img, "avg": round(avg, 3),
                                                           "confidence": rec.get("confidence"),
                                                           "last_pos": rec.get("last_pos")}})
            flags[key] = low

        # 3) 처음 보는 창·팝업(대상 프로그램 것만)
        for title in new_windows or []:
            out.append({"kind": "new_window", "detail": {"title": title}})

        # 4) 느려짐: 성공한 회차의 최근 중앙값보다 factor 배 넘게(그리고 최소 초 이상) 걸린 회차가 연속 count 번
        win = int(cfg["slow_window"])
        oks = [i for i in its if i.get("ok")]
        if len(oks) >= 5 and its and its[-1].get("ok"):
            base = statistics.median(i["seconds"] for i in oks[-win - 1:-1]) if len(oks) > 1 else oks[-1]["seconds"]
            cur = its[-1]["seconds"]
            slow = cur > base * float(cfg["slow_factor"]) and cur >= float(cfg["slow_min_seconds"])
            flags["slow_count"] = flags.get("slow_count", 0) + 1 if slow else 0
            hit = flags["slow_count"] >= int(cfg["slow_count"])
            if hit and not flags.get("slow"):
                out.append({"kind": "slow", "detail": {"seconds": cur, "usual": round(base, 2),
                                                      "times": flags["slow_count"]}})
            flags["slow"] = hit
        return out

    # ---- 요약(화면용)
    def summary(self, recent: int = 20) -> dict:
        its = self.iterations[-recent:]
        ok = sum(1 for i in its if i.get("ok"))
        secs = [i["seconds"] for i in its if i.get("ok")]
        low = []
        for img, rec in self.images.items():
            sc = rec.get("scores") or []
            if len(sc) >= 3:
                avg = sum(sc) / len(sc)
                low.append((round(avg - float(rec.get("confidence", 0.8)), 3), img, round(avg, 3)))
        low.sort()
        return {"iterations": len(its), "ok": ok, "median_seconds": round(statistics.median(secs), 1) if secs else None,
                "low_images": [{"image": i, "avg": a, "margin": m} for m, i, a in low[:3]]}


class HealthRecorder:
    """실행 중 Runner 가 알려 주는 것을 매크로별 건강 기록에 모은다. 하위 매크로도 같은 기록기를 같이 쓴다."""

    def __init__(self, root: str, repairs_root: Optional[str] = None):
        self.root = root
        self.repairs_root = repairs_root        # 고침 기록 폴더(알아챈 신호를 남김)
        self._lock = threading.Lock()
        self._macros: Dict[str, MacroHealth] = {}

    def of(self, name: str, score_window: int = 50) -> MacroHealth:
        with self._lock:
            h = self._macros.get(name)
            if h is None:
                h = self._macros[name] = MacroHealth(name, os.path.join(self.root, _safe(name) + ".json"),
                                                     score_window)
            return h

    # 대상 창 사진 고리(최근 20장): 인식 기준을 낮추기 전 '다른 자리를 잘못 맞히는지' 검사에 씀
    def add_screen(self, name: str, img, origin, keep: int = 20):
        import cv2
        d = os.path.join(self.root, _safe(name) + "_screens")
        os.makedirs(d, exist_ok=True)
        idx_p = os.path.join(d, "index.json")
        try:
            with open(idx_p, encoding="utf-8") as fh:
                idx = json.load(fh)
        except Exception:
            idx = {"next": 0, "items": {}}
        n = int(idx.get("next", 0)) % keep
        fp = os.path.join(d, f"{n:02d}.png")
        ok, buf = cv2.imencode(".png", img)
        if ok:
            buf.tofile(fp)
            idx["items"][f"{n:02d}.png"] = list(origin)
            idx["next"] = n + 1
            with open(idx_p, "w", encoding="utf-8") as fh:
                json.dump(idx, fh)

    def screens_of(self, name: str):
        d = os.path.join(self.root, _safe(name) + "_screens")
        try:
            with open(os.path.join(d, "index.json"), encoding="utf-8") as fh:
                idx = json.load(fh)
        except Exception:
            return []
        return [(os.path.join(d, k), tuple(v)) for k, v in idx.get("items", {}).items() if os.path.exists(os.path.join(d, k))]

    @staticmethod
    def signature(paths: List[str]) -> str:
        return hashlib.sha1("|".join(paths).encode("utf-8")).hexdigest()[:16]


def load_summary(root: str, name: str, recent: int = 20) -> Optional[dict]:
    """화면에서 쓰는 요약(파일만 읽음). 기록이 없으면 None."""
    p = os.path.join(root, _safe(name) + ".json")
    if not os.path.exists(p):
        return None
    return MacroHealth(name, p).summary(recent)

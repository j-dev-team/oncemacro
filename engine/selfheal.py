"""헛돎 알아채기 + 스스로 고치기(11-23, Qt 없음).

'막히면 AI 한 번'(rescue.py)은 스텝이 끝내 '실패'할 때만 걸린다. 실제 오래 도는 매크로는 실패 대신 헛돈다
(같은 스텝이 같은 화면에서 계속 눌림 — 예: 처음 보는 팝업 앞에서 닫기만 136번). 그래서:

1) 알아채기: 같은 스텝(매크로:경로)이 window_s 초 안에 repeat_n 번 넘게 입력을 보내고, 그때마다 화면 지문이
   거의 같으면 '막힘'. 증거 묶음(화면·직전 기록·찾던 대상)을 남긴다.
2) AI 없는 대처(차례대로, 한 번에 하나): 저장된 해결 → 닫기류 대상 누르기 → 복구 매크로 → 그 일 잠깐 쉬기.
   대처 뒤 verify_s 동안 같은 막힘이 다시 안 나면 '통함' → 저장된 해결로 남겨 다음엔 그것부터 씀.
3) 그래도 안 되면 AI 한 번(rescue 의 명령줄 AI): 답은 규칙 후보 → 실제로 통해야 저장.

매크로 JSON 최상위:
  "unstick": {"on": true, "repeat_n": 25, "window_s": 600, "verify_s": 600, "rest_min": 20,
                "close_targets": [대상, ...], "recover_macro": "이름", "ai": true}
"""
from __future__ import annotations

import json
import os
import time
from collections import deque
from typing import Callable, Dict, List, Optional

DEFAULTS = {"on": False, "repeat_n": 25, "window_s": 600.0, "verify_s": 600.0, "rest_min": 20.0,
            "same_screen": 20, "max_distinct": 6, "ai": True, "close_targets": [], "recover_macro": ""}
ACTIONS = ("close", "recover", "rest", "ai")
GENERIC_CLOSE_NAMES = ("닫기", "확인", "계속", "취소", "OK", "Close", "Continue", "Cancel")


def _dist(a: str, b: str) -> int:
    from .rescue import distance
    return distance(a, b)


def state_root() -> str:
    d = os.environ.get("MACRO_SELFHEAL_DIR")
    if d:
        return d
    from .real import PROJECT_ROOT
    return os.path.join(PROJECT_ROOT, "logs", "selfheal")


class SelfHeal:
    """한 번의 실행(맨 위 매크로와 그 하위 매크로들)이 같이 쓰는 헛돎 판단기."""

    def __init__(self, macro_name: str, cfg: dict, root: Optional[str] = None,
                 now: Callable[[], float] = time.time):
        self.name = macro_name
        self.cfg = {**DEFAULTS, **(cfg or {})}
        self.root = root or state_root()
        self.now = now
        self.hits: Dict[str, deque] = {}          # 스텝 → 최근 입력 시각
        self.all: deque = deque()                  # (시각, 스텝) 모든 입력 — 그 사이 몇 가지 스텝을 눌렀나
        self.last_stuck = -1e18
        self.screens: Dict[str, deque] = {}       # 스텝 → 최근 화면 지문
        self.cooldown: Dict[str, float] = {}      # 매크로 이름 → 쉬기 끝 시각
        self.pending: Optional[dict] = None       # 방금 해 본 대처(통했는지 보는 중)
        self.tried: Dict[str, List[str]] = {}     # (스텝|지문 앞부분) → 이번 막힘에서 해 본 대처
        self.saved = self._load()

    # ---------------------------------------------------------------- 저장된 해결
    def _path(self) -> str:
        safe = "".join(ch for ch in self.name if ch not in '\\/:*?"<>|')
        return os.path.join(self.root, f"{safe}.json")

    def _load(self) -> List[dict]:
        try:
            with open(self._path(), encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, list) else []
        except Exception:
            return []

    def _save(self) -> None:
        try:
            os.makedirs(self.root, exist_ok=True)
            tmp = self._path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.saved, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self._path())
        except Exception:
            pass

    def log(self, **rec) -> None:
        try:
            os.makedirs(self.root, exist_ok=True)
            rec = {"시각": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.now())), "매크로": self.name, **rec}
            with open(os.path.join(self.root, "events.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass

    # ---------------------------------------------------------------- 알아채기
    def note(self, key: str, is_input: bool = True) -> bool:
        """입력 한 번(또는 확인이 통한 분기 한 번) 기록. 화면 지문을 볼 때가 됐으면 True(같은 일이 너무 자주 되풀이됨).
        is_input=False: 누름 없이 '찾았다'(then) 분기만 되풀이되는 헛돎용(11-20 실제 기록: 창 제목은 찾는데 받기 단추를 못 찾아
        5분간 120번 같은 확인만 함). 이건 '그 사이 눌린 스텝 종류'에는 안 셈."""
        t = self.now()
        dq = self.hits.setdefault(key, deque())
        dq.append(t)
        w = float(self.cfg["window_s"])
        if is_input:
            self.all.append((t, key))
        while self.all and t - self.all[0][0] > w:
            self.all.popleft()
        while dq and t - dq[0] > w:
            dq.popleft()
        self._settle_pending(t)
        return len(dq) >= int(self.cfg["repeat_n"]) * 0.3         # 지문은 기준의 30%부터 모으기 시작(60% 같은 화면을 보려면)

    def note_screen(self, key: str, fp: str) -> bool:
        """화면 지문 기록. 같은 화면에서 기준 횟수만큼 눌렸으면 True(막힘)."""
        n = int(self.cfg["repeat_n"])
        dq = self.screens.setdefault(key, deque(maxlen=n))
        dq.append(fp)
        same = sum(1 for x in dq if _dist(x, fp) <= int(self.cfg["same_screen"]))
        hits = len(self.hits.get(key, ()))
        # 정상으로 바쁘게 도는 중에도 한 단추가 자주 눌릴 수 있음(같은 화면을 자주 오가는 흐름 등) → 그 사이 눌린 스텝 종류가 적을 때만
        # (실측: 오래 도는 실제 운영 매크로가 정상일 때 10분 동안 입력 스텝 종류 최소 26가지)
        # 종류는 '이번 반복이 이어진 동안'(최근 n번째 반복부터, 최소 2분)만 센다 — 막히기 직전의 정상 입력이 섞이면
        # 5분짜리 헛돎(11-20 실제 기록)을 못 잡았음
        hq = self.hits.get(key) or deque()
        since = min(hq[-n] if len(hq) >= n else (hq[0] if hq else self.now()), self.now() - 120.0)
        distinct = len({k for t0, k in self.all if t0 >= since})
        # 같은 화면 비율 60%: 정상 흐름에서도 같은 창 지문의 약 27%가 '비슷'으로 나옴(실측) → 40%면 잘못 잡힐 수 있음
        if hits >= n and same >= int(n * 0.6) and distinct <= int(self.cfg["max_distinct"]):
            self.hits[key].clear()                                # 다음 막힘은 처음부터 다시 셈
            dq.clear()
            if self.now() - self.last_stuck < 120.0:              # 막 하나 잡은 뒤 2분은 쉼(한꺼번에 여러 개 잡힘 방지)
                return False
            self.last_stuck = self.now()
            return True
        return False

    # ---------------------------------------------------------------- 대처 고르기
    def _tkey(self, key: str, fp: str) -> str:
        return f"{key}|{fp[:16]}"

    def plan(self, key: str, fp: str) -> Optional[dict]:
        """이번에 해 볼 대처 하나. {'action': ..., 'saved': 해결 또는 None}. 다 해 봤으면 None."""
        tk = self._tkey(key, fp)
        if self.pending and self.pending["key"] == key and _dist(self.pending["fp"], fp) <= int(self.cfg["same_screen"]):
            self._mark(self.pending, False)                      # 방금 대처가 안 통함(같은 막힘이 또 남)
            self.pending = None
        done = self.tried.setdefault(tk, [])
        for s in self.saved:                                      # 1) 같은 스텝·비슷한 화면에서 통했던 해결
            if s.get("off") or s.get("key") != key or _dist(s.get("screen", ""), fp) > int(self.cfg["same_screen"]):
                continue
            tag = "saved:" + str(s.get("added"))
            if tag in done:
                continue
            done.append(tag)
            return {"action": s.get("action"), "saved": s}
        for a in ACTIONS:
            if a in done:
                continue
            if a == "close" and not self.cfg.get("close_targets") and not self.cfg.get("generic_close", True):
                continue
            if a == "recover" and not self.cfg.get("recover_macro"):
                continue
            if a == "ai" and not self.cfg.get("ai"):
                continue
            done.append(a)
            return {"action": a, "saved": None}
        return None

    def started(self, key: str, fp: str, action: str, saved: Optional[dict] = None, steps: Optional[list] = None):
        self.pending = {"key": key, "fp": fp, "action": action, "t": self.now(), "saved": saved, "steps": steps}

    def _settle_pending(self, t: float) -> None:
        p = self.pending
        if p and t - p["t"] >= float(self.cfg["verify_s"]):
            self._mark(p, True)
            self.pending = None
            self.tried.pop(self._tkey(p["key"], p["fp"]), None)

    def _mark(self, p: dict, ok: bool) -> None:
        self.log(위치=p["key"], 단계=("저장된해결" if p.get("saved") else p["action"]), 결과=("통함" if ok else "안 통함"))
        s = p.get("saved")
        if s is not None:
            if ok:
                s["uses"] = int(s.get("uses") or 0) + 1
                s.pop("fails", None)
            else:
                s["fails"] = int(s.get("fails") or 0) + 1
                if s["fails"] >= 3:
                    s["off"] = True
            self._save()
        elif ok and p["action"] != "rest":                        # 쉬기는 해결이 아니라 피하기 → 저장 안 함
            self.saved.append({"key": p["key"], "screen": p["fp"], "action": p["action"], "steps": p.get("steps"),
                               "added": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.now())), "uses": 1})
            self._save()

    # ---------------------------------------------------------------- 쉬기
    def rest(self, macro_name: str) -> None:
        self.cooldown[macro_name] = self.now() + float(self.cfg["rest_min"]) * 60.0

    def resting(self, macro_name: str) -> bool:
        until = self.cooldown.get(macro_name)
        if until is None:
            return False
        if self.now() >= until:
            self.cooldown.pop(macro_name, None)
            return False
        return True

    def evidence(self, key: str, img, recent: list, detail: str = "") -> Optional[str]:
        """증거 묶음: 화면 사진 + 직전 기록 + 막힌 스텝·찾던 대상. 폴더 경로."""
        try:
            stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(self.now()))
            safe = "".join(ch for ch in self.name if ch not in '\\/:*?"<>|')
            d = os.path.join(self.root, "evidence", f"{stamp}_{safe}")
            os.makedirs(d, exist_ok=True)
            if img is not None:
                import cv2
                cv2.imencode(".png", img)[1].tofile(os.path.join(d, "screen.png"))
            with open(os.path.join(d, "recent.jsonl"), "w", encoding="utf-8") as f:
                for ev in recent:
                    f.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
            with open(os.path.join(d, "info.json"), "w", encoding="utf-8") as f:
                json.dump({"key": key, "detail": detail}, f, ensure_ascii=False, indent=1)
            return d
        except Exception:
            return None


def day_counts(day: str, root: Optional[str] = None) -> dict:
    """그날 막힘·처리 단계 집계: {'막힘': n, '저장된해결': n, 'close': n, 'recover': n, 'rest': n, 'ai': n, '통함': n}."""
    out = {"막힘": 0, "통함": 0, "안 통함": 0}
    p = os.path.join(root or state_root(), "events.jsonl")
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if not str(r.get("시각", "")).startswith(day):
                    continue
                if r.get("사건") == "막힘":
                    out["막힘"] += 1
                if "결과" in r:
                    out[r["결과"]] = out.get(r["결과"], 0) + 1
                    k = r.get("단계")
                    if r["결과"] == "통함" and k:
                        out[k] = out.get(k, 0) + 1
    except OSError:
        pass
    return out

"""
템플릿 저장 뒤 검사 (MCP 서버·GUI 공용).

잘라 낸 템플릿이 실제로 쓸 만한지 본다:
- 자기 자리에서 바로 찾아지는지(self_match)
- 화면의 다른 곳과 모양·색이 둘 다 비슷한지(헷갈림 → warning)
- 1초 동안 점수가 흔들리는지(반짝임·크기 변화 → animated, recommended_confidence)
좌표는 모두 화면 절대좌표. 화면에 보여줄 때 창 기준으로 바꾸는 건 부르는 쪽 일.
"""
from __future__ import annotations

import time
from typing import Optional, Tuple
from .i18n import t


def check_template(vision, rel_path: str, search_region: Optional[Tuple[int, int, int, int]],
                   samples: int = 6, interval: float = 0.17) -> dict:
    vision.new_frame()
    m = vision.match(rel_path, search_region, {"confidence": 0.8, "color_check": 0.85})
    second, spos, second_color = vision.runner_up(rel_path, search_region)
    result = {"self_match": m.found, "self_score": round(m.score, 3),
              "found_at": list(m.pos) if m.pos else None,
              "second_score": round(second, 3), "second_pos": list(spos) if spos else None,
              "second_color": round(second_color, 3)}
    scores = []
    for _ in range(max(1, samples)):
        if interval:
            time.sleep(interval)
        vision.new_frame()
        scores.append(vision.match(rel_path, search_region, {"confidence": 0.0, "color_check": None}).score)
    lo, hi = min(scores), max(scores)
    result["score_range_1s"] = [round(lo, 3), round(hi, 3)]
    if lo < 0.9:
        rec = round(max(0.6, lo - 0.05), 2)
        result["animated"] = True
        result["recommended_confidence"] = rec
        result["note"] = t("1초 동안 점수가 {lo:.2f}~{hi:.2f} 로 흔들림(반짝임·움직임). 이 대상은 confidence 를 "
                           "{rec} 정도로 낮추고 region 을 좁게 주는 게 안전함", lo=lo, hi=hi, rec=rec)
    if second >= 0.8 and second_color >= 0.85:
        result["warning"] = t("화면의 다른 곳과도 모양·색이 비슷함. 같은 버튼이 여러 개라 아무거나 눌러도 되는 게 "
                              "아니라면, 스텝에 region 을 좁게 주거나 더 특징적인 부분을 다시 잘라야 함")
    return result

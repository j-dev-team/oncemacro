"""영어로만 매크로 만들기·돌리기 확인(11-24).

AI(Claude Code)에게 영어로 부탁하고, 이 프로그램의 AI 연결 도구를 영어 모드(--lang en)로만 준다.
1) AI가 메모장에 글을 넣고 저장하는 매크로를 만들어 저장(macro_save)
2) 그 매크로를 AI 없이 새 메모장에서 다시 돌려 파일 내용으로 성공 판정
3) AI가 받은 도구 응답·저장된 매크로에 한글이 섞였는지 센다(대상 프로그램 자체의 글 — 창 제목·단추 이름 — 은 따로 셈)

사용: venv\\Scripts\\python.exe scripts\\english_build_check.py   (사람이 PC 를 안 쓸 때. 비용 약 0.1~0.3달러)
결과: logs/bench/<날짜>_english_check.json
"""
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import bench_ai_vs_macro as b  # noqa: E402

NAME = "_en_check_notepad"
TEXT = "hello from an english macro"
KO = re.compile(r"[가-힣]+")


def open_notepad():
    os.makedirs(b.WORK, exist_ok=True)
    f = os.path.join(b.WORK, "en_check.txt")
    open(f, "w").close()
    p, h = b.launch(["notepad.exe", f], "en_check.txt")
    import win32gui
    return f, h, win32gui.GetWindowText(h) if h else ""


def mcp_config():
    p = os.path.join(b.WORK, "mcp_en.json")
    json.dump({"mcpServers": {"macro": {"type": "stdio", "command": b.PY, "args": ["-m", "engine.mcp_server", "--lang", "en"],
                                        "env": {"PYTHONPATH": ROOT, "PYTHONIOENCODING": "utf-8", "MACRO_LANG": "en"}}}},
              open(p, "w", encoding="utf-8"))
    return p


def tool_texts(stream: str):
    out = []
    for line in stream.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") != "user":
            continue
        for c in (ev.get("message") or {}).get("content") or []:
            if isinstance(c, dict) and c.get("type") == "tool_result":
                cc = c.get("content")
                if isinstance(cc, list):
                    out += [x.get("text", "") for x in cc if isinstance(x, dict)]
                elif isinstance(cc, str):
                    out.append(cc)
    return out


def main():
    subprocess.run([b.PY, os.path.join(ROOT, "scripts", "human_idle.py"), "wait", "180", "28800"], capture_output=True)
    f, h, title = open_notepad()
    prompt = (f"Using only the macro tools, build a macro that types exactly '{TEXT}' into the body of the Notepad "
              f"window titled '{title}' and saves the file (File > Save). Test the steps, then save the macro with "
              f"macro_save under the name '{NAME}', with \"window\": {{\"title\": \"{title}\", \"background\": true}}. "
              f"Do not rename the window. When done, answer with the single word 'done'.")
    args = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose", "--mcp-config", mcp_config(),
            "--strict-mcp-config", "--allowedTools", "mcp__macro", "--permission-mode", "default"]
    t0 = time.time()
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
                       cwd=b.WORK, shell=(os.name == "nt"))
    build_s = time.time() - t0
    last = {}
    for line in r.stdout.splitlines()[::-1]:
        try:
            last = json.loads(line)
            if last.get("type") == "result":
                break
        except ValueError:
            pass
    texts = tool_texts(r.stdout)
    b.close_all(h)

    mp = os.path.join(ROOT, "macros_v2", NAME + ".json")
    saved = json.load(open(mp, encoding="utf-8")) if os.path.exists(mp) else None
    replay = None
    if saved:
        f, h, title2 = open_notepad()
        saved.setdefault("window", {})["title"] = title2
        from engine.real import RealEnv
        res = RealEnv().runner(saved).run().to_dict()
        time.sleep(0.5)
        ok = TEXT in open(f, encoding="utf-8", errors="replace").read()
        replay = {"status": res["status"], "file_ok": ok, "reason": (res.get("error") or {}).get("reason", "")}
        b.close_all(h)

    app_words = set(KO.findall(title)) | {"텍스트", "편집", "파일", "저장", "메모장", "편집기", "서식", "보기", "도움말",
                                          "새", "창", "열기", "다른", "이름으로", "페이지", "설정", "인쇄", "끝내기",
                                          "탭", "닫기", "최소화", "최대화", "복원", "시스템", "메뉴", "표시줄", "상태"}
    ko_lines = [ln.strip()[:160] for t in texts for ln in t.splitlines() if KO.search(ln)]
    ours = [ln for ln in ko_lines if not set(KO.findall(ln)) <= app_words]
    saved_ko = sorted(set(KO.findall(json.dumps(saved, ensure_ascii=False)))) if saved else []
    report = {"built": bool(saved), "build_seconds": round(build_s, 1), "cost_usd": last.get("total_cost_usd"),
              "turns": last.get("num_turns"), "answer": str(last.get("result"))[:80], "replay_without_ai": replay,
              "tool_results": len(texts), "korean_lines_total": len(ko_lines),
              "korean_lines_from_target_app_only": len(ko_lines) - len(ours), "korean_lines_from_us": ours[:40],
              "korean_words_in_saved_macro": saved_ko}
    os.makedirs(b.OUT, exist_ok=True)
    out = os.path.join(b.OUT, time.strftime("%Y%m%d_%H%M") + "_english_check.json")
    json.dump(report, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if saved:
        os.remove(mp)                                   # 시험용 매크로는 지움


if __name__ == "__main__":
    main()

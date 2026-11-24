"""비교 측정: 같은 일을 '매번 AI가 화면을 보고 조작' vs '한 번 만든 매크로를 반복'(11-23).

누구나 따라 할 수 있게:
  venv\\Scripts\\python.exe scripts\\bench_ai_vs_macro.py macro notepad 100
  venv\\Scripts\\python.exe scripts\\bench_ai_vs_macro.py ai notepad 5
  venv\\Scripts\\python.exe scripts\\bench_ai_vs_macro.py build notepad 1      # AI가 매크로를 한 번 만드는 비용
  (calc 도 같음) 결과: logs/bench/<날짜>_<방식>_<과제>.jsonl, 끝에 요약 한 줄

- AI 방식: 이 컴퓨터의 Claude Code(`claude -p`, JSON 출력)에 이 프로그램의 MCP 도구만 주고 과제를 시킨다.
  비용은 Claude Code 가 돌려주는 total_cost_usd(정가 기준), 시간은 시작~끝, 성공은 결과 파일·화면 값으로 판정.
- 매크로 방식: 같은 과제를 창 요소 이름으로 만든 매크로(뒤에서 실행)로 돌린다. AI 비용 0.
- 과제마다 창은 시험이 직접 띄우고 끝나면 닫는다. 사람이 PC 를 쓰는 중에는 돌리지 않는다(AI 방식은 창을 앞으로 가져올 수 있음).
"""
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import win32con  # noqa: E402
import win32gui  # noqa: E402
import win32process  # noqa: E402

WORK = os.path.join(tempfile.gettempdir(), "macro_bench")
OUT = os.path.join(ROOT, "logs", "bench")
PY = os.path.join(ROOT, "venv", "Scripts", "python.exe")


def E(name, ty=None, match="exact"):
    e = {"name": name, "match": match}
    if ty:
        e["type"] = ty
    return {"element": e}


def launch(cmd, title_part, wait=10.0):
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 4
    p = subprocess.Popen(cmd, startupinfo=si)
    end = time.time() + wait
    while time.time() < end:
        hs = []
        win32gui.EnumWindows(lambda h, _: hs.append(h) if win32gui.IsWindowVisible(h)
                             and title_part in win32gui.GetWindowText(h) else None, None)
        if hs:
            return p, hs[0]
        time.sleep(0.2)
    return p, None


def close_all(h):
    from engine import win_uia
    try:
        pid = win32process.GetWindowThreadProcessId(h)[1]
    except Exception:
        return
    for _ in range(4):
        hs = []
        win32gui.EnumWindows(lambda x, _: hs.append(x) if win32gui.IsWindowVisible(x)
                             and win32process.GetWindowThreadProcessId(x)[1] == pid else None, None)
        if not hs:
            return
        for x in hs:
            if x != h:
                win_uia.invoke(x, {"name": "저장 안 함", "type": "button", "match": "contains"}) or \
                    win_uia.invoke(x, {"name": "취소", "type": "button"})
        if win32gui.IsWindow(h):
            win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
        time.sleep(0.8)
        for x in hs:
            win_uia.invoke(x, {"name": "저장 안 함", "type": "button", "match": "contains"})
        time.sleep(0.4)


# ---------------------------------------------------------------- 과제
def task_notepad(i):
    """메모장: 정해진 글을 넣고 저장. 성공 = 파일에 그 글이 있음."""
    os.makedirs(WORK, exist_ok=True)
    f = os.path.join(WORK, f"벤치_{i}.txt")
    open(f, "w").close()
    text = f"벤치 {i} 확인"
    p, h = launch(["notepad.exe", f], f"벤치_{i}.txt")
    title = f"벤치_{i}.txt - Windows 메모장"

    def check():
        try:
            return text in open(f, encoding="utf-8", errors="replace").read()
        except OSError:
            return False

    macro = {"version": 2, "name": "벤치_메모장", "window": {"title": title, "background": True}, "repeat": {"times": 1},
             "steps": [{"type": "wait", "until": {"exists": E("텍스트 편집", "edit")}, "timeout": 6},
                       {"type": "type_text", "target": E("텍스트 편집", "edit"), "text": text},
                       {"type": "menu", "path": "파일 > 저장"}, {"type": "delay", "seconds": 0.5}]}
    prompt = (f"윈도우 메모장 창 '{title}' 의 본문에 정확히 '{text}' 를 입력하고 저장해(파일 > 저장). "
              f"이 프로그램의 macro 도구(macro_elements, macro_test_step 등)로 조작해. 창 제목은 바꾸지 말고, "
              f"끝나면 '완료' 한 단어만 답해.")
    return {"h": h, "macro": macro, "prompt": prompt, "check": check,
            "cleanup": lambda: (close_all(h), os.path.exists(f) and os.remove(f))}


def task_calc(i):
    """계산기: a × b 를 계산. 성공 = 표시가 정답."""
    a, b = 12 + i % 7, 34 + i % 11
    old = win32gui.FindWindow(None, "계산기")
    if not old:
        subprocess.Popen(["calc.exe"])
        for _ in range(40):
            old = win32gui.FindWindow(None, "계산기")
            if old:
                break
            time.sleep(0.25)
    from engine import win_uia
    words = {0: "공"}

    def keys(n):
        return [{"type": "click", "target": E(words.get(int(c), c), "button")} for c in str(n)]

    def check():
        return bool(win_uia.find(old, {"name": f"표시는 {a * b}", "type": "text"}))

    macro = {"version": 2, "name": "벤치_계산기", "window": {"title": "계산기", "background": True}, "repeat": {"times": 1},
             "steps": [{"type": "click", "target": E("지우기", "button")}, *keys(a),
                       {"type": "click", "target": E("곱", "button")}, *keys(b),
                       {"type": "click", "target": E("일치", "button")},
                       {"type": "wait", "until": {"exists": E(f"표시는 {a * b}", "text")}, "timeout": 3}]}
    prompt = (f"윈도우 계산기 창 '계산기' 로 {a} × {b} 를 계산해서 화면에 결과가 나오게 해. "
              f"이 프로그램의 macro 도구(macro_elements, macro_test_step 등)로 조작해. 끝나면 결과 숫자만 답해.")
    return {"h": old, "macro": macro, "prompt": prompt, "check": check, "cleanup": lambda: None}


TASKS = {"notepad": task_notepad, "calc": task_calc}


# ---------------------------------------------------------------- 방식
def run_macro(t):
    from engine.real import RealEnv
    t0 = time.time()
    res = RealEnv().runner(t["macro"]).run().to_dict()
    dt = time.time() - t0
    time.sleep(0.3)
    return {"ok": res["status"] == "ok" and t["check"](), "seconds": round(dt, 2), "cost_usd": 0.0,
            "reason": (res.get("error") or {}).get("reason", "")}


def mcp_config():
    p = os.path.join(WORK, "mcp.json")
    os.makedirs(WORK, exist_ok=True)
    json.dump({"mcpServers": {"macro": {"type": "stdio", "command": PY, "args": ["-m", "engine.mcp_server"],
                                        "env": {"PYTHONPATH": ROOT, "PYTHONIOENCODING": "utf-8"}}}},
              open(p, "w", encoding="utf-8"))
    return p


def run_ai(t, prompt=None, timeout=600):
    args = ["claude", "-p", prompt or t["prompt"], "--output-format", "json", "--mcp-config", mcp_config(),
            "--strict-mcp-config", "--allowedTools", "mcp__macro", "--permission-mode", "default"]
    t0 = time.time()
    try:
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, cwd=WORK, shell=(os.name == "nt"))
        out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    except Exception as e:
        out = {"error": repr(e)}
    dt = time.time() - t0
    time.sleep(0.5)
    return {"ok": bool(t["check"]()), "seconds": round(dt, 2), "cost_usd": float(out.get("total_cost_usd") or 0),
            "turns": out.get("num_turns"), "reason": str(out.get("error") or out.get("result") or "")[:120]}


def main():
    mode, task, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
    os.makedirs(OUT, exist_ok=True)
    log = os.path.join(OUT, f"{time.strftime('%Y%m%d_%H%M')}_{mode}_{task}.jsonl")
    rows = []
    for i in range(n):
        if mode != "macro" or (task == "calc" and i == 0):   # 창을 앞으로 가져올 수 있는 측정(AI·계산기 처음 띄우기)은 사람 입력이 3분 없을 때만
            subprocess.run([PY, os.path.join(ROOT, "scripts", "human_idle.py"), "wait", "180", "28800"],
                           capture_output=True)
        t = TASKS[task](i)
        try:
            if mode == "macro":
                r = run_macro(t)
            elif mode == "ai":
                r = run_ai(t)
            else:   # build: AI가 같은 일을 하는 매크로를 만들어 저장하고 한 번 돌려 봄
                r = run_ai(t, prompt=t["prompt"].replace("조작해.", "조작해. 그리고 같은 일을 다음부터 AI 없이 반복할 수 있게 "
                                                        "macro_save 로 '벤치_만든매크로' 이름의 매크로를 저장해.")
                           .replace("결과 숫자만 답해", "'완료'만 답해"))
        finally:
            t["cleanup"]()
        r["i"] = i
        rows.append(r)
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(json.dumps(r, ensure_ascii=False), flush=True)
    ok = sum(1 for r in rows if r["ok"])
    secs = sorted(r["seconds"] for r in rows)
    print(f"== {mode} {task}: 성공 {ok}/{n}, 걸린 시간 중앙값 {secs[len(secs) // 2]}초, "
          f"AI 비용 합계 {sum(r['cost_usd'] for r in rows):.3f}달러(1번 평균 {sum(r['cost_usd'] for r in rows) / n:.4f})")


if __name__ == "__main__":
    main()

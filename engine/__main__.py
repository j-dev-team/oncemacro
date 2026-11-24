"""
엔진 CLI.

  python -m engine windows                     보이는 창 목록 (window.title / process 정할 때)
  python -m engine validate <이름|파일.json>    매크로 형식 검사
  python -m engine run <이름|파일.json>         실행 (비상 정지: ctrl+shift+f12)
  python -m engine find <이미지> [--region x,y,w,h] [--compare-v1]
  python -m engine step '<스텝 JSON>' [--window 제목]
  python -m engine convert [이름 ...] [--dry-run] [--force] [--window 제목]   v1 → v2 변환
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading

from .i18n import t
from .model import MacroError, ensure_valid, load_macro, new_macro, validate_macro


def _utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _load(arg: str, env=None) -> dict:
    if arg.lower().endswith(".json") and os.path.exists(arg):
        return load_macro(arg)
    from .library import FileLibrary
    from .real import MACRO_ROOT
    lib = env.library if env else FileLibrary(MACRO_ROOT)
    return lib.load(arg)


def _region(s):
    if not s:
        return None
    v = [int(x) for x in s.split(",")]
    if len(v) != 4:
        raise SystemExit(t("--region 은 x,y,w,h"))
    return tuple(v)


def cmd_windows(a):
    from .win_window import is_process_elevated, list_windows, self_elevated, set_dpi_awareness
    print(t("DPI: {dpi}  이 프로세스 관리자 권한: {elevated}", dpi=set_dpi_awareness(), elevated=self_elevated()))
    for w in list_windows():
        if w.minimized and not a.all:
            continue
        el = is_process_elevated(w.pid)
        el = "?" if el is None else (t("관리자") if el else t("일반"))
        print(f"{w.process:28} {el:4} {str(w.client):26} {w.title}")


def cmd_validate(a):
    path = a.macro
    if path.lower().endswith(".json") and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = _load(path)
    errs = validate_macro(data)
    if errs:
        print(t("형식 오류:"))
        for e in errs:
            print(" -", e)
        return 1
    print(t("정상: {name} (스텝 {n}개)", name=data["name"], n=len(data["steps"])))
    return 0


def cmd_run(a):
    from .real import TRACE_ROOT, RealEnv
    from .trace import ConsoleTrace, JsonlTrace, fanout, trace_path
    from .win_input import EmergencyStop
    env = RealEnv()
    macro = _load(a.macro, env)
    jt = JsonlTrace(trace_path(TRACE_ROOT, macro["name"]))
    stop = threading.Event()
    timer = None
    if a.max_seconds:
        timer = threading.Timer(a.max_seconds, stop.set)
        timer.daemon = True
        timer.start()
    print(t("실행: {name}  |  비상 정지: {hotkey}  |  기록: {path}", name=macro["name"], hotkey=a.emergency_hotkey, path=jt.path))
    runner = env.runner(macro, on_event=fanout(jt, ConsoleTrace(verbose=a.verbose)))
    box = {}

    def work():
        box["res"] = runner.run(stop)

    # 실행은 작업 스레드에서. 메인 스레드는 Ctrl+C 를 받아 '정지'로 바꿔준다(에러로 끊기지 않게).
    worker = threading.Thread(target=work, name="macro-runner", daemon=True)
    with EmergencyStop(stop, a.emergency_hotkey, on_fire=lambda: print(t("[정지] 비상 정지 핫키"), flush=True)):
        worker.start()
        while worker.is_alive():
            try:
                worker.join(0.2)
            except KeyboardInterrupt:
                print(t("[정지] Ctrl+C — 정지 중"), flush=True)
                stop.set()
    if timer:
        timer.cancel()
    jt.close()
    res = box.get("res")
    return 0 if res and res.status == "ok" else 1


def cmd_find(a):
    import time
    from .real import RealEnv
    env = RealEnv()
    region = _region(a.region)
    opts = {"confidence": a.confidence, "multiscale": a.multiscale, "color_check": a.color_check}
    env.vision.new_frame()
    t0 = time.perf_counter()
    m = env.vision.match(a.image, region, opts)
    ms = (time.perf_counter() - t0) * 1000
    print(f"v2: found={m.found} pos={m.pos} score={m.score:.3f} ({ms:.0f}ms)")
    if a.compare_v1:
        import contextlib
        import io
        from core.image import ImageRecognizer
        buf = io.StringIO()
        t0 = time.perf_counter()
        with contextlib.redirect_stdout(buf):
            pos = ImageRecognizer.find_image(env.vision.resolve(a.image), a.confidence, region)
        ms = (time.perf_counter() - t0) * 1000
        print(f"v1: pos={pos} ({ms:.0f}ms)")
        if pos and m.pos:
            print(t("차이: dx={dx} dy={dy}", dx=m.pos[0] - pos[0], dy=m.pos[1] - pos[1]))
    return 0 if m.found else 1


def cmd_step(a):
    from .real import RealEnv
    from .trace import ConsoleTrace
    from .win_input import EmergencyStop
    env = RealEnv()
    step = json.loads(a.step)
    fields = {"window": {"title": a.window}} if a.window else {}
    runner = env.runner(new_macro("step", [], **fields), on_event=ConsoleTrace(verbose=True))
    stop = threading.Event()
    with EmergencyStop(stop):
        out = runner.run_step(step, runner.new_context(), stop)
    print(json.dumps(out, ensure_ascii=False, default=str))
    return 0 if out["status"] == "ok" else 1


def cmd_convert(a):
    from .convert_v1 import convert_folder, render_report
    from .real import IMAGE_ROOT, MACRO_ROOT, PROJECT_ROOT
    src = a.src or os.path.join(PROJECT_ROOT, "macros")
    dst = a.dst or MACRO_ROOT
    window, origin = None, (0, 0)
    if a.window:
        from .win_window import find_window, set_dpi_awareness
        set_dpi_awareness()
        w = find_window({"title": a.window})
        window = {"title": a.window, "size": [w.client[2], w.client[3]]}
        origin = (w.client[0], w.client[1])
        print(t("창 기준 변환: '{title}' 원점 {origin} — 녹화 때와 창 위치가 같다고 가정함", title=w.title, origin=origin))
    reports = convert_folder(src, dst, IMAGE_ROOT, a.names or None, window, origin,
                             force=a.force, dry_run=a.dry_run)
    text = render_report(reports, a.dry_run)
    if not a.dry_run:
        os.makedirs(dst, exist_ok=True)
        rp = os.path.join(dst, "_conversion_report.md")
        with open(rp, "w", encoding="utf-8") as f:
            f.write(text)
        print(t("보고서: {path}", path=rp))
    print(text)
    return 1 if any(r.errors for r in reports) else 0


def _pick_lang(argv) -> None:
    """--lang en|ko, 아니면 환경변수 MACRO_LANG, 아니면 윈도우 표시 언어."""
    from . import i18n
    lang = ""
    argv = list(argv if argv is not None else sys.argv[1:])
    for i, a in enumerate(argv):
        if a == "--lang" and i + 1 < len(argv):
            lang = argv[i + 1]
        elif a.startswith("--lang="):
            lang = a.split("=", 1)[1]
    lang = lang or os.environ.get("MACRO_LANG", "") or i18n.system_language()
    i18n.set_language(lang)


def main(argv=None):
    _utf8()
    _pick_lang(argv)
    p = argparse.ArgumentParser(prog="python -m engine", description=t("매크로 엔진 v2 명령줄 도구"))
    p.add_argument("--lang", choices=["en", "ko"], help=t("글 언어(기본: MACRO_LANG, 없으면 윈도우 표시 언어)"))
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("windows", help=t("보이는 창 목록"))
    s.add_argument("--all", action="store_true", help=t("최소화된 창도 표시"))
    s = sub.add_parser("validate", help=t("매크로 형식 검사"))
    s.add_argument("macro", help=t("매크로 이름 또는 .json 파일 경로"))
    s = sub.add_parser("run", help=t("매크로 실행"))
    s.add_argument("macro", help=t("매크로 이름 또는 .json 파일 경로"))
    s.add_argument("--max-seconds", type=float, help=t("이 시간(초)이 지나면 정지"))
    s.add_argument("--emergency-hotkey", default="ctrl+shift+f12", help=t("비상 정지 핫키"))
    s.add_argument("-v", "--verbose", action="store_true", help=t("자세히 출력"))
    s = sub.add_parser("find", help=t("이미지가 화면에서 찾아지는지 시험"))
    s.add_argument("image", help=t("image/ 폴더 기준 이미지 경로"))
    s.add_argument("--region", help=t("찾을 범위 x,y,w,h"))
    s.add_argument("--confidence", type=float, default=0.8, help=t("일치 기준(0~1)"))
    s.add_argument("--multiscale", action="store_true", help=t("크기를 바꿔 가며 찾기"))
    s.add_argument("--color-check", type=float, help=t("색 검사 기준"))
    s.add_argument("--compare-v1", action="store_true", help=t("v1 이미지 찾기와 결과 비교"))
    s = sub.add_parser("step", help=t("스텝 하나 실행"))
    s.add_argument("step", help=t("스텝 JSON"))
    s.add_argument("--window", help=t("좌표 기준 창 제목"))
    s = sub.add_parser("convert", help=t("v1 매크로를 v2 로 변환"))
    s.add_argument("names", nargs="*", help=t("v1 매크로 이름 (생략하면 전부)"))
    s.add_argument("--src", help=t("v1 매크로 폴더"))
    s.add_argument("--dst", help=t("v2 매크로를 저장할 폴더"))
    s.add_argument("--window", help=t("창 제목. 주면 지금 그 창 위치를 기준으로 좌표를 바꿈"))
    s.add_argument("--force", action="store_true", help=t("이미 있는 v2 파일 덮어쓰기"))
    s.add_argument("--dry-run", action="store_true", help=t("파일을 쓰지 않고 미리보기만"))
    a = p.parse_args(argv)
    try:
        return {"windows": cmd_windows, "validate": cmd_validate, "run": cmd_run,
                "find": cmd_find, "step": cmd_step, "convert": cmd_convert}[a.cmd](a) or 0
    except MacroError as e:
        print(e)
        return 2


if __name__ == "__main__":
    sys.exit(main())

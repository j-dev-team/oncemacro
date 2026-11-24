"""새 화면 폴더형 실행 묶음을 내보낼 압축 파일로 만든다(설치 파일 없음, 2026-11-17 사용자 결정).
먼저 실행 파일을 만든다: venv\\Scripts\\python.exe scripts\\run_limited.py --mem-gb 3 --timeout 900 -- venv\\Scripts\\python.exe -m PyInstaller OnceMacro.spec (공개판) 또는 MacroManager_v3.spec --distpath dist_v3 --workpath dist_v3\\_build --noconfirm
그다음: venv\\Scripts\\python.exe scripts\\make_zip_v3.py [버전]
결과: dist_v3\\매크로관리자_<버전>.zip
  매크로관리자\\
    처음_읽어주세요.txt
    프로그램\\MacroManager.exe, _internal\\
    macros_v2\\  image\\        ← 빈 자료 폴더(사용자 매크로는 넣지 않음)

공개용(영어·가벼운 판, 11-23): make_zip_v3.py <버전> --global
  공개판(dist_public, 초점 도우미 포함)을 OnceMacro\\app\\ 로, 안내는 packaging\\README_FIRST.txt
  결과: dist_public\\OnceMacro-<버전>-win64.zip (한 줄 설치 install.ps1 이 이 파일을 받는다)"""
import os
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist_v3", "MacroManager")
TOP = "매크로관리자"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    glob_ = "--global" in sys.argv
    ver = args[0] if args else time.strftime("%Y%m%d")
    dist = os.path.join(ROOT, "dist_public", "OnceMacro") if glob_ else DIST       # 11-24: 공개판 이름 OnceMacro
    top, app = ("OnceMacro", "app") if glob_ else (TOP, "프로그램")
    if not os.path.exists(os.path.join(dist, "OnceMacro.exe" if glob_ else "MacroManager.exe")):
        print("실행 파일이 없습니다. 먼저 OnceMacro.spec (공개판) 또는 MacroManager_v3.spec 으로 만드세요.")
        return 1
    out = (os.path.join(ROOT, "dist_public", f"OnceMacro-{ver}-win64.zip") if glob_
           else os.path.join(ROOT, "dist_v3", f"{TOP}_{ver}.zip"))
    readme = os.path.join(ROOT, "packaging", "README_FIRST.txt" if glob_ else "처음_읽어주세요.txt")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.write(readme, f"{top}/{os.path.basename(readme)}")
        if glob_:                                   # 공개판: 라이선스·외부 부품 안내도 같이
            for f in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
                src = next(p for p in (os.path.join(ROOT, "packaging", "public", f), os.path.join(ROOT, f))
                           if os.path.exists(p))                  # 이 저장소: packaging/public, 공개 저장소: 맨 위
                z.write(src, f"{top}/{f}")
        for d in ("macros_v2", "image"):
            z.writestr(f"{top}/{d}/", "")
        n = 0
        for base, _dirs, files in os.walk(dist):
            if "_build" in base.replace("\\", "/").split("/"):
                continue
            for f in files:
                p = os.path.join(base, f)
                rel = os.path.relpath(p, dist).replace("\\", "/")
                z.write(p, f"{top}/{app}/{rel}")
                n += 1
    print(f"{out}  (파일 {n}개, {os.path.getsize(out) / 1048576:.0f}MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

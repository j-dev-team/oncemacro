"""새 화면(v3) 폴더형 실행 묶음의 시작 파일. `--mcp`·`--run 이름` 은 그대로 받는다.
(기본 화면이 v3 로 바뀌면 main.py 하나로 합친다.)"""
import sys

if __name__ == "__main__":
    if "--mcp" not in sys.argv[1:] and "--guard" not in sys.argv[1:] and "--v3" not in sys.argv[1:]:
        sys.argv.insert(1, "--v3")
    from main import main
    main()

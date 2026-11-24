"""OnceMacro — start the program.

    python main.py            open the program
    python main.py --run NAME open the program and run that macro
    python main.py --mcp      no window: MCP server for AI agents (stdio)
    python main.py --guard    no window: watchdog for long-running macros
    (--restore-windows PID is started by the program itself)
"""
import sys


def main():
    if "--mcp" in sys.argv[1:]:
        from engine.mcp_server import main as mcp_main
        mcp_main()
        return
    if "--guard" in sys.argv[1:]:
        from engine.guard import main_guard
        main_guard()
        return
    if "--restore-windows" in sys.argv[1:]:
        from engine.win_hide import watch_main
        watch_main()
        return
    from gui.v3.app import main as main_v3
    sys.exit(main_v3([a for a in sys.argv if a != "--v3"]))


if __name__ == "__main__":
    main()

OnceMacro — read me first
============================

1. No installation needed
   - Keep this folder anywhere you like and run "app\OnceMacro.exe".
   - No administrator rights needed. Do not put it under "Program Files" (saving is blocked there).

2. "Windows protected your PC"
   - Windows shows this for unsigned programs downloaded from the internet.
   - If you trust where you got it, click "More info" -> "Run anyway". It will not ask again.

3. Where your data lives (all inside this folder)
   - macros_v2 : your macros       - image : pictures your macros look for
   - logs      : run history       - settings : window/theme/language settings
   Move the whole folder and your data moves with it.

4. Connect your AI agent (Claude Code, Codex, Gemini CLI, Cursor ...)
   - In the program: the "Connect AI" button on the toolbar, or run once in a terminal:
       claude mcp add --scope user macro -- "<this folder>\app\OnceMacro.exe" --mcp
   - Then ask your agent: "Make a macro that ..." — it builds and tests the macro once,
     and from then on the macro runs without any AI.

5. Update: replace only the "app" folder.   Uninstall: delete this folder.

6. Emergency stop: Ctrl + Shift + F12 at any time.

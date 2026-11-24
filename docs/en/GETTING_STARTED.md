# Getting started

## 1. Install
Run in PowerShell (no admin rights):

```powershell
irm https://raw.githubusercontent.com/j-dev-team/oncemacro/main/install.ps1 | iex
```

Or download `OnceMacro-<version>-win64.zip` from Releases, unpack it anywhere (not under Program Files)
and run `app\OnceMacro.exe`. Windows may show "Windows protected your PC" for unsigned programs:
click **More info → Run anyway**.

Some antivirus products may flag the program because of its background mode. If that happens, add the OnceMacro
folder to your antivirus exceptions, or run the affected macro in **Compatibility mode**. See "Background mode" in the README.

Your data stays in the folder next to `app\`: `macros_v2\` (macros), `image\` (pictures), `logs\` (history),
`settings\`. To update, replace only `app\`. To uninstall, delete the folder.

## 2. Make your first macro
Three ways, shown on the first screen:
- **Start from an example** — adds a few example macros you can run right away (a screenshot timer and an Excel report; Korean users also get an HWP form example).
- **Record one** — do the task once with mouse and keyboard; press F9 to finish.
- **Ask an AI** — connect Claude Code / Codex / Gemini CLI / Cursor (see [AI_CONNECT.md](AI_CONNECT.md))
  and describe the task in words.

## 3. Run it
Select the macro and press **Run** (F5), or give it a hotkey so it runs while you use other windows.
Use **Schedule** to run it at set times. Press **Ctrl+Shift+F12** to stop anything, anywhere.

## 4. Let it run in the background
In the macro editor, turn on **Run in background** for the target window. The macro then works on that
window without taking your screen, focus or mouse, even when it is behind other windows — dialogs and key
combos included, and also by pictures and positions for apps without UI element information. Tick **Run hidden**
as well to keep the window off your screen while the macro runs. A minimized window keeps working; in a few apps
typing into a minimized window needs a click on the field first (see the README table). If a program does not start in background mode,
turn on **Compatibility mode** for that macro.

## 5. Long-running macros
Turn on **unstick** (`"unstick": {"on": true}` in the macro JSON). The program watches for loops, keeps
evidence in `logs\selfheal\`, tries fixes on its own and keeps a daily count you can include in a feedback report.

# Benchmark: AI every time vs. a macro built once

Measured on 2026-11-23/24 on one PC (Windows 10, Korean UI), with the tools in this repository.
Anyone can rerun it:

```powershell
venv\Scripts\python.exe scripts\bench_ai_vs_macro.py macro notepad 100
venv\Scripts\python.exe scripts\bench_ai_vs_macro.py ai notepad 5
venv\Scripts\python.exe scripts\bench_ai_vs_macro.py build notepad 1
```
(`calc` works the same way.) Raw results go to `logs\bench\*.jsonl`, one line per run.

## Tasks
- **notepad** — type a given line into a Notepad window and save the file (File > Save). Success = the file
  contains the line.
- **calc** — compute a × b in Windows Calculator. Success = the display shows the right result.

## Methods
- **AI every time** — Claude Code (`claude -p`, its default model) gets only this program's MCP tools and does
  the task by looking at the window. Cost = `total_cost_usd` reported by Claude Code (list price).
- **Build once** — the same AI is asked to do the task *and* save it as a macro (`macro_save`).
- **Macro** — the saved kind of macro (buttons and fields by name, background mode) runs with no AI at all.
- Each run opens its own window and closes it afterwards. AI runs only start after 3 minutes without
  human input, so a person using the PC does not disturb them.

## Results

| Task | Method | Runs | Success | Median time | Cost per run |
|---|---|---|---|---|---|
| notepad | AI every time | 5 | 5/5 | 15.1 s | $0.137 |
| notepad | build once (AI) | 1 | 1/1 | 18.5 s | $0.165 (once) |
| notepad | macro | 100 | 100/100 | 1.08 s | $0 |
| calc | AI every time | 5 | 5/5 | 20.0 s | $0.159 |
| calc | build once (AI) | 1 | 1/1 | 26.6 s | $0.199 (once) |
| calc | macro | 100 | 100/100 | 3.68 s | $0 |

What 100 repetitions of the notepad task cost:

| | Time | AI cost |
|---|---|---|
| AI every time | about 25 min | about $13.70 |
| Build once, then macro | about 2 min (18.5 s + 100 × 1.08 s) | $0.17 |

## Notes and limits
- One PC, small samples for the AI runs (5 each). AI timing varies with the network and the model.
- The slowest calc macro run took 22.3 s (the first run, while Calculator was starting).
- Building a macro costs a little more than doing the task once, so it pays off from the second run.
- These are simple tasks. On harder screens the AI may need more turns, and a macro may need fixes when the
  app changes; OnceMacro's unstick feature handles part of that, and asks the AI only if allowed.
- The PC runs a Korean Windows UI, so the macros use Korean element names (for example the Notepad edit box).

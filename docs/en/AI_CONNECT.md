# Connect your AI agent

OnceMacro includes an MCP server. The program itself is the server: `OnceMacro.exe --mcp`.
The easiest way is the **Connect AI** button in the program, which writes the settings for you.
Manual setup (tested with Claude Code; the Codex, Gemini CLI and Cursor entries follow each tool's documented
MCP format but have not been tested yet):

## Claude Code
```powershell
claude mcp add --scope user macro -- "C:\path\to\OnceMacro\app\OnceMacro.exe" --mcp
```

## Codex (CLI and desktop app) — `~/.codex/config.toml`
```toml
[mcp_servers.macro]
command = 'C:\path\to\OnceMacro\app\OnceMacro.exe'
args = ["--mcp"]
```

## Gemini CLI — `~/.gemini/settings.json`
```json
{"mcpServers": {"macro": {"command": "C:\\path\\to\\OnceMacro\\app\\OnceMacro.exe", "args": ["--mcp"]}}}
```

## Cursor — `~/.cursor/mcp.json`
```json
{"mcpServers": {"macro": {"type": "stdio", "command": "C:\\path\\to\\OnceMacro\\app\\OnceMacro.exe", "args": ["--mcp"]}}}
```

## Agent skill (optional)
Copy `skills/windows-macro/` into your agent's skills folder (for Claude Code: `~/.claude/skills/`).
It teaches the agent the build-once workflow.

## What the agent sees
The tools are read in steps so they stay small:
- `macro_reference()` gives the core format and a category list (about 3 KB). The agent opens only what
  it needs, e.g. `macro_reference(category="web")`.
- `macro_list()` gives macro names by group. `macro_list(query=...)` or `macro_get(name)` give details.
- `macro_test_step(steps=[...])` tests several steps in one call.

Typical session: `macro_list_windows` → `macro_elements` → `macro_test_step` → `macro_save` → `macro_run`.
Once saved, the macro runs from the program, a hotkey or a schedule without any AI.

When the program's window is open, AI tool calls are handled by the running program, so its background
mode and safety checks apply to AI tests too.

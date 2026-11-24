# OnceMacro one-line installer (Windows 10/11, no admin rights needed)
#
#   irm https://raw.githubusercontent.com/j-dev-team/oncemacro/main/install.ps1 | iex
#
# What it does
#   1. Downloads the latest release zip (OnceMacro-<version>-win64.zip) from GitHub Releases
#   2. Unpacks it to %LOCALAPPDATA%\OnceMacro (keeps your macros if you already have them)
#   3. Registers the MCP server with Claude Code / Codex if they are installed (skips what is already there)
# Nothing else on your PC is changed. Uninstall = delete %LOCALAPPDATA%\OnceMacro.
#
# Options (when saved and run as a file):  .\install.ps1 -Dir D:\OnceMacro -NoMcp
param(
    [string]$Repo = "j-dev-team/oncemacro",                         
    [string]$Dir = (Join-Path $env:LOCALAPPDATA "OnceMacro"),
    [switch]$NoMcp
)
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

Write-Host "OnceMacro installer" -ForegroundColor Cyan
$hdr = @{ "User-Agent" = "OnceMacro-installer" }
if ($env:ONCEMACRO_GITHUB_TOKEN) { $hdr["Authorization"] = "Bearer $env:ONCEMACRO_GITHUB_TOKEN" }   # only for testing a private copy
$rel = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest" -Headers $hdr
$asset = $rel.assets | Where-Object { $_.name -like "OnceMacro-*-win64.zip" } | Select-Object -First 1
if (-not $asset) { throw "No OnceMacro-*-win64.zip in the latest release of $Repo" }
$zip = Join-Path $env:TEMP $asset.name
Write-Host "Downloading $($asset.name) ($([math]::Round($asset.size / 1MB)) MB)..."
if ($env:ONCEMACRO_GITHUB_TOKEN) {
    $h2 = $hdr.Clone(); $h2["Accept"] = "application/octet-stream"
    Invoke-WebRequest $asset.url -Headers $h2 -OutFile $zip -UseBasicParsing
} else {
    Invoke-WebRequest $asset.browser_download_url -OutFile $zip -UseBasicParsing
}
Unblock-File $zip

$tmp = Join-Path $env:TEMP ("om_" + [guid]::NewGuid().ToString("N"))
Expand-Archive $zip -DestinationPath $tmp -Force
$src = Join-Path $tmp "OnceMacro"
New-Item -ItemType Directory -Force $Dir | Out-Null
# Replace only the program; keep user data folders (macros_v2, image, logs, settings)
if (Test-Path (Join-Path $Dir "app")) { Remove-Item (Join-Path $Dir "app") -Recurse -Force }
Copy-Item (Join-Path $src "app") (Join-Path $Dir "app") -Recurse -Force
foreach ($d in "macros_v2", "image") { New-Item -ItemType Directory -Force (Join-Path $Dir $d) | Out-Null }
foreach ($f in "README_FIRST.txt", "LICENSE", "THIRD_PARTY_NOTICES.md") {
    if (Test-Path (Join-Path $src $f)) { Copy-Item (Join-Path $src $f) $Dir -Force }
}
Remove-Item $tmp -Recurse -Force; Remove-Item $zip -Force
$exe = Join-Path $Dir "app\OnceMacro.exe"
Write-Host "Installed to $Dir" -ForegroundColor Green

if (-not $NoMcp) {
    if (Get-Command claude -ErrorAction SilentlyContinue) {
        $have = (& claude mcp list 2>$null) -match "^macro:"
        if (-not $have) { & claude mcp add --scope user macro -- "$exe" --mcp; Write-Host "Claude Code: MCP server 'macro' added" }
        else { Write-Host "Claude Code: 'macro' already registered (left as is)" }
    }
    $codexCfg = Join-Path $HOME ".codex\config.toml"
    if (Test-Path (Split-Path $codexCfg)) {
        $txt = if (Test-Path $codexCfg) { Get-Content $codexCfg -Raw } else { "" }
        if ($txt -notmatch "\[mcp_servers\.macro\]") {
            Add-Content $codexCfg ("`n[mcp_servers.macro]`ncommand = '" + $exe + "'`nargs = [`"--mcp`"]`n")
            Write-Host "Codex: MCP server 'macro' added to $codexCfg"
        }
    }
}
Write-Host ""
Write-Host "Done. Start the program:  & '$exe'"
Write-Host "Or ask your AI agent:     'Using the macro tools, make a macro that ...'"

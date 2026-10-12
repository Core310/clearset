# ClearSet (cs) Updater for Windows PowerShell
# https://github.com/Core310/clearset

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "Updating ClearSet (cs) in $ScriptDir..." -ForegroundColor Cyan

# 1. Pull latest Git commits
if (Test-Path "$ScriptDir\.git") {
    try {
        $LocalHash = git rev-parse --short HEAD
        Write-Host "Current commit: $LocalHash"
        Write-Host "Fetching latest changes..."
        git pull --ff-only origin main
        $NewHash = git rev-parse --short HEAD
        Write-Host "Updated successfully to commit: $NewHash" -ForegroundColor Green
    } catch {
        Write-Warning "Fast-forward git pull failed. Inspect with 'git status'."
    }
}

# 2. Refresh Python package
Write-Host "Refreshing Python package..."
try {
    python -m pip install -e . --no-deps --quiet
} catch {
    Write-Warning "pip install failed. Verify Python is installed and available in PATH."
}

# 3. Create/refresh Windows CLI wrappers
$UserBin = Join-Path $HOME ".local\bin"
if (!(Test-Path $UserBin)) {
    New-Item -ItemType Directory -Path $UserBin -Force | Out-Null
}

$Commands = @{
    "cs"         = "bin\cs_engine.py"
    "cs-fetch"   = "bin\cs_fetch.py"
    "cs-sync"    = "bin\cs_sync.py"
    "cs-gate"    = "bin\cs_gate.py"
    "cs-cleanup" = "bin\cs_cleanup.py"
    "cs-mcp"     = "bin\cs_mcp.py"
    "cs-hook"    = "bin\cs_hook.py"
}

foreach ($entry in $Commands.GetEnumerator()) {
    $cmd = $entry.Key
    $targetPy = Join-Path $ScriptDir $entry.Value
    $cmdFile = Join-Path $UserBin "$cmd.cmd"
    $wrapperContent = "@echo off`r`nset PYTHONPATH=$ScriptDir;%PYTHONPATH%`r`npython `"$targetPy`" %*"
    Set-Content -Path $cmdFile -Value $wrapperContent -Encoding ASCII
}

# Legacy aliases
Copy-Item (Join-Path $UserBin "cs.cmd") (Join-Path $UserBin "cta.cmd") -Force
Copy-Item (Join-Path $UserBin "cs-fetch.cmd") (Join-Path $UserBin "cta-fetch.cmd") -Force
Copy-Item (Join-Path $UserBin "cs-cleanup.cmd") (Join-Path $UserBin "cta-cleanup.cmd") -Force
Copy-Item (Join-Path $UserBin "cs-hook.cmd") (Join-Path $UserBin "cta-hook.cmd") -Force

# 4. Link skills to Gemini and AGY configurations (directory junctions)
$SkillTargets = @(
    (Join-Path $HOME ".gemini\config\skills"),
    (Join-Path $HOME ".agy\skills")
)

foreach ($targetDir in $SkillTargets) {
    if (!(Test-Path $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }

    Get-ChildItem -Path (Join-Path $ScriptDir "skills\cs-*") -Directory | ForEach-Object {
        $dest = Join-Path $targetDir $_.Name
        if (Test-Path $dest) {
            cmd /c rmdir "$dest" 2>$null | Out-Null
        }
        cmd /c mklink /J "$dest" "$($_.FullName)" | Out-Null
    }
}

Write-Host "ClearSet update completed successfully!" -ForegroundColor Green

# Updating ClearSet (`cs`)

Instructions for updating an existing ClearSet installation across Linux, macOS, and Windows.

---

## Quick Update

### Linux & macOS
From any terminal, run the native update script:

```bash
# If running from inside the cloned repository
./update.sh

# Or from anywhere via the CLI
cs update
```

### Windows (PowerShell)
From PowerShell, run the native update script:

```powershell
.\update.ps1
```

---

## What the Updater Executes

Running the update script performs the following sequence deterministically:

1. **Git Synchronization**: Pulls the latest commits from the `main` branch using `git pull --ff-only origin main`.
2. **CLI Binary Refresh**: Re-installs wrapper executables in `~/.local/bin/` (or Windows cmd shims in `%USERPROFILE%\.local\bin`):
   - `cs` (engine)
   - `cs-fetch` (code and symbol retriever)
   - `cs-sync` (git diff AST auto-sync)
   - `cs-gate` (test runner gate)
   - `cs-hook` (post-edit syntax linter and auto-sync hook)
   - `cs-cleanup` (codebase hygiene)
   - `cs-mcp` (Model Context Protocol stdio server)
3. **Skill Link Refresh**: Refreshes symlinks and Windows junctions in `~/.gemini/config/skills` and `~/.agy/skills`.
4. **Python Package Refresh**: Runs `pip install -e . --no-deps` to ensure the local Python environment has current entry points.

---

## Troubleshooting

### Diverged Local Git Branches
If local edits prevent a fast-forward pull, inspect modified files and reset if desired:

```bash
git status
git reset --hard origin/main
./update.sh
```

### PATH Verification
Ensure `~/.local/bin` (Linux/macOS) or `%USERPROFILE%\.local\bin` (Windows) is exported in your environment PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

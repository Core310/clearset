# ClearSet (`cs`)

Lightweight CLI and Python package for AI coding agents to index codebases into SQLite and maintain execution state across context resets.

---

## Overview

AI agents working in large repositories burn context tokens reading entire files and lose continuity when clearing context windows. ClearSet offloads codebase structure and session state into local SQLite databases:

1. **Token-Budgeted Retrieval**: Read function signatures, class outlines, or specific line ranges instead of loading full source files.
2. **Persistent Turn Ledger (`cs_turns.db`)**: Every command, code change, architectural decision, and test result is recorded locally.
3. **Context Resumption (`RESUME HERE.md`)**: Agents can run `/clear` at any time; `cs resume` rehydrates the active milestone, phase, task, and pending issues from disk.
4. **Subagent Task Blackboard**: Subagents claim tasks from SQLite. Each agent runs its verification gate locally and reports back with exit codes, avoiding transcript bloat.

ClearSet has **zero third-party dependencies** and runs on Python standard library modules (`sqlite3`, `ast`, `subprocess`, `argparse`, `pathlib`).

---

## Architecture

```
                       +-------------------------+
                       |     AI Coding Agent     |
                       | (AGY / Hermes / Claude) |
                       +------------+------------+
                                    | CLI / MCP / Python
                                    v
       +--------------------------------------------------------+
       |                    ClearSet Core (`cs`)                |
       +-------+--------------------+-------------------+-------+
               |                    |                   |
               v                    v                   v
    +----------------------+ +---------------+ +----------------------+
    |  .cs/cs_codebase.db  | | RESUME HERE.md| |   .cs/cs_turns.db    |
    |  - AST Symbols       | | - Active M/P/T| | - Turn Actions Log   |
    |  - Call Graph / Deps | | - Next Todo   | | - Architectural Decs |
    |  - Full-Text Search  | | - Checkpoint  | | - Swarm Task Ledger  |
    +----------------------+ +---------------+ +----------------------+
```

---

## Installation

Clone the repository and run the local installer:

```bash
git clone https://github.com/Core310/clearset.git ~/.local/share/clearset
~/.local/share/clearset/install.sh
```

This installs six CLI wrappers into `~/.local/bin/`:
- `cs` — Core lifecycle engine (init, map, query, plan, swarm, checkpoint, resume)
- `cs-fetch` — Token-budgeted code, symbol, and outline retriever
- `cs-sync` — Git-diff AST auto-synchronizer
- `cs-gate` — Deterministic test runner and SQLite turn audit gate
- `cs-cleanup` — AST bloat, dead code, and cache cleaner
- `cs-mcp` — Model Context Protocol (MCP) JSON-RPC stdio server

Legacy symlinks (`cta`, `cta-fetch`, `cta-cleanup`) are also created for backward compatibility.

---

## Command Line Reference

### 1. Workspace Initialization
In any repository root:

```bash
cs init
```
Parses the repository with Python's AST parser, writes symbols into `.cs/cs_codebase.db`, and generates `cs_codebase_index.yml`. Add `--json` for machine-readable output.

### 2. Token-Budgeted Fetch (`cs-fetch`)
Retrieve specific code snippets without dumping entire files into the prompt:

```bash
# Get exact signature, line range, and docstring
cs-fetch symbol authenticate_user

# Get file outline (classes and functions with line numbers)
cs-fetch outline src/auth/service.py

# Read a specific slice of lines
cs-fetch slice src/auth/service.py 45 60

# Search symbols and docstrings via SQLite FTS
cs-fetch context "jwt validation"
```
Pass `--json` to any fetch command to get structured JSON payloads.

### 3. State Synchronization (`cs-sync`)
Keeps `.cs/cs_codebase.db` synchronized after code changes:

```bash
cs-sync --json
```
Uses `git diff` against the last mapped commit to re-parse only modified files, prune deleted symbols, and update index files.

### 4. Verification Gate (`cs-gate`)
Runs compiler, linter, or test commands, captures return codes, and records the run in `cs_turns.db`:

```bash
cs-gate --milestone "M001" --phase "01" --task "1.1" -- "pytest tests/"
```

### 5. Checkpoint & Resume
Before clearing the context window:

```bash
cs checkpoint --milestone "M001" --phase "01" --task "1.2" --next "Implement token refresh route"
```

After clearing context (`/clear`):

```bash
cs resume
```
Restores the active milestone, phase, task, recent actions, and open issues in milliseconds.

---

## Python API

ClearSet can be imported directly in Python scripts:

```python
import clearset as cs

workspace = cs.find_workspace(Path.cwd())

# Fetch code slices and symbols
symbols = cs.fetch_symbol_data(workspace, "handle_request")
outline = cs.fetch_outline_data(workspace, "src/server.py")

# Synchronize database after edits
stats = cs.sync_codebase_state(workspace)

# Run verification gate
gate_res = cs.run_verification_gate(
    workspace=workspace,
    command_str="pytest tests/",
    milestone="M001",
    phase="01",
    task="1.1",
)
```

---

## Model Context Protocol (MCP)

ClearSet includes a stdio MCP server (`cs-mcp`) exposing tools for agents running in Cursor, Claude Desktop, or Windsurf.

Example `mcpServers` configuration:

```json
{
  "mcpServers": {
    "clearset": {
      "command": "cs-mcp",
      "args": []
    }
  }
}
```

Exposed MCP tools:
- `cs_fetch_symbol` — Retrieve exact function or class signatures
- `cs_fetch_outline` — Retrieve high-level file outline
- `cs_fetch_context` — Full-text and tag search over codebase
- `cs_fetch_callers` — Trace callers and dependencies
- `cs_fetch_turns` — Retrieve recent session actions and open concerns
- `cs_sync` — Run incremental git diff synchronization
- `cs_gate` — Execute deterministic test/lint gate

Machine-readable JSON schema is available in [`clearset.manifest.json`](clearset.manifest.json).

---

## Multi-Agent Blackboard Coordination (`cs-swarm`)

For multi-agent workflows, ClearSet uses a central SQLite blackboard to prevent transcript bloat:

```bash
# 1. Enqueue tasks into SQLite
cs swarm-dispatch \
  --milestone "M001" --phase "02" --topology "scatter_gather" \
  --tasks-json '[
    {"task_id": "t-1", "title": "Add Auth API", "role": "coder", "target_files": ["api/auth.py"], "verification_cmd": "pytest tests/test_auth.py"},
    {"task_id": "t-2", "title": "Add CLI Wrapper", "role": "coder", "target_files": ["cli/main.py"], "verification_cmd": "python3 cli/main.py --help"}
  ]'

# 2. Worker claims task
cs swarm-claim --worker-id "worker-1"

# 3. Worker fetches targeted context packet (<300 tokens)
cs-fetch swarm-packet "t-1"

# 4. Worker reports exit code
cs swarm-report --task-id "t-1" --status "PASSED" --exit-code 0
```

---

## ClearSet Skills

The repository includes 11 agent skills:

| Skill | Role | Key Command |
| :--- | :--- | :--- |
| **`cs-init`** | Workspace & database initializer | `cs init --json` |
| **`cs-sync`** | Deterministic git-diff AST auto-synchronizer | `cs-sync --json` |
| **`cs-gate`** | Deterministic verification test gate | `cs-gate "pytest tests/"` |
| **`cs-mapper`** | Incremental AST symbol extraction & relationship grapher | `cs map --incremental` |
| **`cs-query`** | Token-budgeted SQLite RAG & call-graph retriever | `cs-fetch symbol`, `outline`, `slice` |
| **`cs-planner`** | Spec-driven hierarchy engine (Milestones -> Phases -> Tasks) | `cs log-learning --kind decision` |
| **`cs-executor`** | Task execution with test gates and turn logging | `cs log-action --status SUCCESS` |
| **`cs-clear`** | State checkpointing and `RESUME HERE.md` generator | `cs checkpoint` |
| **`cs-resume`** | Instant session restoration after `/clear` | `cs resume` |
| **`cs-swarm`** | Blackboard-gated multi-agent coordinator | `cs swarm-dispatch`, `cs swarm-claim` |
| **`cs-cleanup`** | AST dead symbol detection and ruff styler | `cs-cleanup scan`, `apply` |

---

## Testing

Run unit tests with Python standard library `unittest`:

```bash
python3 tests/test_clearset.py
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.

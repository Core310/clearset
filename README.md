# ClearSet (`cs`)

> **Deterministic Context Resets, SQLite Blackboard State & Token-Budgeted Code Retrieval for AI Coding Agents.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10+-brightgreen.svg)]()
[![Zero Dependencies](https://img.shields.io/badge/Dependencies-Zero-orange.svg)]()

ClearSet (`cs`) is a lightweight, zero-dependency framework that allows AI coding agents (Antigravity, Gemini CLI, Claude Code, Hermes Agent, Cursor) to navigate codebases, track execution state across sessions, and **wipe context windows cleanly without losing their place**.

---

## ⚡ The Problem ClearSet Solves

| Without ClearSet | With ClearSet (`cs`) |
| :--- | :--- |
| **Context Bloat**: Agents dump entire 1,000-line files into context just to read one function, burning through token budgets. | **Token-Budgeted AST Slices**: `cs-fetch symbol`, `outline`, or `slice` pulls only the exact function signature or line range (<200 tokens). |
| **Context Rot**: After 30 turns, agents forget early constraints, repeat mistakes, and introduce regressions. | **SQLite Turn Ledger (`cs_turns.db`)**: Every turn action, architectural decision, and open concern is persistently indexed on disk. |
| **Destructive `/clear`**: Clearing the context window wipes all memory; the agent forgets what it was building. | **Fearless Resumption (`RESUME HERE.md`)**: `cs resume` restores the active milestone, phase, task, and unresolved issues in 2 milliseconds. |
| **Multi-Agent Telephone Game**: Subagents passing chat transcripts compound hallucinations and blow up tokens ($O(N^2)$). | **Blackboard Pattern (`cs-swarm`)**: Ephemeral subagents claim isolated tasks from SQLite, run deterministic test gates, report, and die ($O(N)$). |

---

## 🏗️ Architecture

```
                       ┌─────────────────────────┐
                       │     AI Coding Agent     │
                       │ (AGY / Hermes / Claude) │
                       └────────────┬────────────┘
                                    │ CLI Commands / Skills
                                    ▼
       ┌────────────────────────────────────────────────────────┐
       │                    ClearSet Core (`cs`)                │
       └───────┬────────────────────┬───────────────────┬───────┘
               │                    │                   │
               ▼                    ▼                   ▼
    ┌──────────────────────┐┌───────────────┐┌──────────────────────┐
    │  .cs/cs_codebase.db  ││ RESUME HERE.md││   .cs/cs_turns.db    │
    │  - AST Symbols       ││ - Active M/P/T││ - Turn Actions Log   │
    │  - Call Graph / Deps ││ - Next Todo   ││ - Architectural Decs │
    │  - Full-Text Search  ││ - Checkpoint  ││ - Swarm Task Ledger  │
    └──────────────────────┘└───────────────┘└──────────────────────┘
```

---

## 🚀 Quick Start

### 1. Installation
Clone the repository and run the installer:

```bash
git clone https://github.com/Core310/clearset.git ~/.local/share/clearset
~/.local/share/clearset/install.sh
```

This installs three CLI binaries into `~/.local/bin/`:
* `cs` — Core lifecycle engine (init, map, query, plan, swarm, checkpoint, resume)
* `cs-fetch` — High-speed, token-efficient code & symbol retriever
* `cs-cleanup` — Grug-principled dead symbol, bloat, and cache cleaner

*(Also creates backward-compatible `cta`, `cta-fetch`, and `cta-cleanup` symlinks).*

### 2. Initialize a Workspace
In any repository root:

```bash
cs init
```
This extracts all AST symbols into `.cs/cs_codebase.db`, indexes functions and classes, and generates `cs_codebase_index.yml`.

### 3. Retrieve Code (Zero Token Waste)
Instead of feeding entire files to an LLM:

```bash
# Get exact signature and line range
cs-fetch symbol authenticate_user

# Get a compact 10-line outline of any file
cs-fetch outline src/auth/service.py

# Read only lines 45-60
cs-fetch slice src/auth/service.py 45 60

# Search codebase by query or domain tag
cs-fetch context "jwt validation"
```

### 4. Checkpoint & Clear Context
Before running `/clear`:

```bash
cs checkpoint --milestone "M001" --phase "01" --task "1.2" --next "Implement refresh token rotation"
```

Now wipe your screen (`/clear`). When you start your next turn:

```bash
cs resume
```
The agent immediately restores the active milestone, phase, task, open concerns, and git status without reading a single source file.

---

## 🧠 The ClearSet Skill Suite

ClearSet ships with 9 specialized agent skills ready for Antigravity, Gemini CLI, Claude Code, and Hermes Agent:

| Skill | Role | Key Command |
| :--- | :--- | :--- |
| **`cs-init`** | Workspace & database initializer | `cs init` |
| **`cs-mapper`** | Incremental AST symbol extraction & relationship grapher | `cs map --incremental` |
| **`cs-query`** | Token-budgeted SQLite RAG & call-graph retriever | `cs-fetch symbol`, `outline`, `slice` |
| **`cs-planner`** | Spec-driven hierarchy engine (Milestones $\rightarrow$ Phases $\rightarrow$ Tasks) | `cs log-learning --kind decision` |
| **`cs-executor`** | Task execution with test gates and turn logging | `cs log-action --status SUCCESS` |
| **`cs-clear`** | State checkpointing and `RESUME HERE.md` generator | `cs checkpoint` |
| **`cs-resume`** | Instant session restoration after `/clear` | `cs resume` |
| **`cs-swarm`** | Blackboard-gated multi-agent coordinator ($O(N)$ tokens) | `cs swarm-dispatch`, `cs swarm-claim` |
| **`cs-cleanup`** | Grug-principled dead AST symbol detection and ruff styler | `cs-cleanup scan`, `apply` |

---

## 🐝 Blackboard Swarm Coordination (`cs-swarm`)

ClearSet solves multi-agent coordination without the "telephone game":

```bash
# 1. Dispatch independent tasks to the blackboard
cs swarm-dispatch \
  --milestone "M001" --phase "02" --topology "scatter_gather" \
  --tasks-json '[
    {"task_id": "t-1", "title": "Add Auth API", "role": "coder", "target_files": ["api/auth.py"], "verification_cmd": "pytest tests/test_auth.py"},
    {"task_id": "t-2", "title": "Add CLI Wrapper", "role": "coder", "target_files": ["cli/main.py"], "verification_cmd": "python3 cli/main.py --help"}
  ]'

# 2. Ephemeral worker claims task
cs swarm-claim --worker-id "worker-1"

# 3. Worker receives lean context packet (<300 tokens)
cs-fetch swarm-packet "t-1"

# 4. Worker executes and reports deterministic exit code
cs swarm-report --task-id "t-1" --status "PASSED" --exit-code 0
```

---

## 💡 Why ClearSet Over Alternatives?

* **Zero Dependencies**: Uses Python's standard library (`sqlite3`, `ast`, `hashlib`, `pathlib`). No PyTorch, no LangChain, no ChromaDB, no Docker daemon.
* **100% Deterministic**: Ground truth comes from SQLite and real compiler/test runner exit codes (`pytest`, `ruff`), never from verbal LLM self-reports.
* **Model Agnostic**: Works with Gemini 3.8 / 1.5, Claude 3.7 / 3.5 Sonnet, GPT-4o, or local Ollama / Nous Hermes models.
* **Backward Compatible**: Transparently reads existing `.cta` databases and symlinks legacy commands.

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.

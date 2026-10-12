# ClearSet Agent Instructions (`AGENTS.md`)

This repository is governed by ClearSet (`cs`). Agents operating in this codebase or using ClearSet must follow these operational rules:

- **Autonomous**: When authorized to run autonomously (via user instruction, "do all of them", "run autonomous", or /goal), execute tasks sequentially through the plan hierarchy without stopping for human prompts between subtasks.
- **Gates**: Every task implementation must be validated by a deterministic verification gate (e.g., `cs-gate`, unit tests, or linters). An exit code of $0$ serves as the synthetic approval sign-off.
- **Ledger**: Record completed actions, learnings, and concerns directly to `.cs/cs_turns.db` using `cs log-action` and `cs log-learning`.
- **Sync**: Refresh codebase AST indexes deterministically via `cs-sync` after modifying files, or rely on `cs-hook` via lifecycle hooks.
- **Checkpoints**: Maintain active state by updating `RESUME HERE.md` or `.continue-here` with the current Milestone, Phase, Sub-phase, and exact next task after completing each subtask.
- **Escalation**: Pause and solicit human guidance only if a verification gate fails after self-healing attempts or an ambiguous architectural blocker arises.

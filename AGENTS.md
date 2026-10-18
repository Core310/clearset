# ClearSet Agent Instructions (`AGENTS.md`)

This repository is governed by ClearSet (`cs`). Agents operating in this codebase or using ClearSet must follow these operational rules:

- **Autonomous**: When authorized to run autonomously (via user instruction, "do all of them", "run autonomous", or /goal), execute tasks sequentially through the plan hierarchy without stopping for human prompts between subtasks.
- **Gates**: Every task implementation must be validated by a deterministic verification gate (e.g., `cs-gate`, unit tests, or linters). An exit code of $0$ serves as the synthetic approval sign-off.
- **Grader**: The audit mechanism in ClearSet serves as an adversarial code quality grader and objective second view. It evaluates patches for static validity, cyclomatic bloat, dead AST symbols, and test regressions prior to task completion, completely decoupled from academic or coursework logic.
- **Ledger**: Record completed actions, learnings, and concerns directly to `.cs/cs_turns.db` using `cs log-action` and `cs log-learning`.
- **Sync**: Refresh codebase AST indexes deterministically via `cs-sync` after modifying files, or rely on `cs-hook` via lifecycle hooks.
- **Checkpoints**: Maintain active state by updating `RESUME HERE.md` or `.continue-here` with the current Milestone, Phase, Sub-phase, and exact next task after completing each subtask.
- **Escalation**: Pause and solicit human guidance only if a verification gate fails after self-healing attempts or an ambiguous architectural blocker arises.
- **Anti-Glaze**: Reject sycophancy, cheerleading, and unearned praise. Do not reflexively validate user assertions; treat user prompts as hypotheses to stress-test. Point out potential failure modes, trade-offs, and edge cases directly.
- **Uncertainty**: Calibrate linguistic confidence strictly against empirical evidence. Explicitly label unverified assumptions and distinguish between code that passed a deterministic gate (exit code $0$) and unexecuted theoretical solutions.

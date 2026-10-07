# cs-swarm

Blackboard-Gated Multi-Agent Swarm Coordinator for the ClearSet Framework.

## Features
- **Shared SQLite Blackboard**: Coordinates tasks through `cs_turns.db` and `cs_codebase.db` rather than high-token natural language peer-to-peer chats.
- **Strict O(N) Token Scaling**: Ephemeral subagents receive minimal, targeted packets via `cs-fetch swarm-packet`.
- **Deterministic Hard Gates**: All work is validated by compilers, linters, or test suites (`exit_code == 0`).
- **4 Operational Topologies**:
  1. `scatter_gather`: Parallel execution of disjoint tasks.
  2. `generator_auditor`: Red/Blue team verification (Implementer vs. Adversarial Tester).
  3. `divergent_research`: Multi-perspective exploration before planning.
  4. `sentinel`: Background codebase AST drift detection.

## Quickstart
```bash
# 1. Dispatch swarm run
cta swarm-dispatch --phase 01 --topology scatter_gather --tasks-json '[...]'

# 2. Worker claims task
cta swarm-claim --worker-id worker-1

# 3. Worker inspects packet
cs-fetch swarm-packet task-1

# 4. Worker reports status
cta swarm-report --task-id task-1 --status PASSED --exit-code 0 --summary "Built feature."
```

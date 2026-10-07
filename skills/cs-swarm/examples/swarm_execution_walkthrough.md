# ClearSet Swarm (`cs-swarm`) Execution Walkthrough

## Scenario: Implementing Phase 2 in Parallel (Scatter-Gather)

### 1. Spec Analysis & Dispatch
Phase 2 contains two decoupled subtasks:
- **Task 2.1**: Build JWT authentication service in `src/auth/jwt.py`.
- **Task 2.2**: Build CLI command in `src/cli/auth_cmd.py`.

The Orchestrator checks for target file disjointness (`src/auth/jwt.py` vs `src/cli/auth_cmd.py`) and dispatches the run:

```bash
cta swarm-dispatch \
  --milestone "M001" \
  --phase "Phase 2" \
  --topology "scatter_gather" \
  --tasks-json '[
    {
      "task_id": "task-2.1",
      "title": "JWT Auth Service",
      "role": "coder",
      "target_files": ["src/auth/jwt.py"],
      "target_symbols": ["create_token", "verify_token"],
      "verification_cmd": "pytest tests/test_jwt.py"
    },
    {
      "task_id": "task-2.2",
      "title": "Auth CLI Command",
      "role": "coder",
      "target_files": ["src/cli/auth_cmd.py"],
      "target_symbols": ["login_command"],
      "verification_cmd": "python3 -m unittest tests/test_cli.py"
    }
  ]'
```

### 2. Spawning Subagents
The Orchestrator spawns two parallel subagents using `invoke_subagent`:
- Subagent 1 (Role: `JWT Implementer`, Model: `flash`, Workspace: `inherit`)
- Subagent 2 (Role: `CLI Implementer`, Model: `flash`, Workspace: `inherit`)

### 3. Worker Execution Loop (Subagent 1)
Worker 1 claims the pending task:
```bash
cta swarm-claim --worker-id "subagent-1"
```
Worker 1 fetches its lean context packet:
```bash
cs-fetch swarm-packet "task-2.1"
```
Worker 1 modifies `src/auth/jwt.py`, runs `pytest tests/test_jwt.py`, and records completion:
```bash
cta swarm-report \
  --task-id "task-2.1" \
  --status "PASSED" \
  --exit-code 0 \
  --summary "Implemented JWT token creation and verification using PyJWT." \
  --files src/auth/jwt.py
```

### 4. Inter-Task Contract Handshake (Optional)
If Worker 1 introduces a new schema required by Worker 2, it posts a message to the blackboard:
```bash
cta swarm-post-msg \
  --run-id "run-20260902" \
  --from-task "task-2.1" \
  --to-task "task-2.2" \
  --type "CONTRACT_UPDATE" \
  --payload '{"token_field": "access_token", "header": "Authorization: Bearer <token>"}'
```
When Worker 2 fetches `cs-fetch swarm-packet task-2.2`, this message appears directly in its prompt packet.

### 5. Verification & Completion
The Orchestrator inspects:
```bash
cta swarm-status
```
Once both tasks are `PASSED`, the swarm run transitions to `COMPLETED`, and the orchestrator creates a checkpoint with `cta checkpoint`.

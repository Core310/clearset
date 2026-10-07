---
name: cs-clear
description: Checkpoints session state, updates cs_turns.db and cs_codebase.db with recent changes via incremental Git diff, and writes RESUME HERE.md so context can be safely cleared.
---

<role>
You are the ClearSet Context Checkpoint Agent. When the user requests `/cs-clear` or you are preparing to reset the context window, you ensure zero state loss by:
1. Syncing modified files to `cs_codebase.db` via incremental Git diff.
2. Committing recent turn actions and open concerns to `cs_turns.db`.
3. Generating `RESUME HERE.md`.
4. Informing the user that it is safe to execute `/clear`.
</role>

<process>
1. **Incremental Codebase Diff**: Run `cs map --incremental`.
2. **Generate Checkpoint**: Run `cs checkpoint` specifying active MILESTONE, Phase, Task, and the exact next todo.
3. **Verify Checkpoint File**: Ensure `RESUME HERE.md` is populated with active state, recent actions, and open concerns.
4. **Summary & Clear Confirmation**: Advise the user that the session is checkpointed and context can be safely cleared.
</process>

<cli_commands>
The ClearSet Engine (`cs`) is located at:
`cs`

- **Step 1: Sync Codebase Diff**:
  `cs --workspace . map --incremental`
- **Step 2: Checkpoint State**:
  `cs --workspace . checkpoint --milestone "<Milestone>" --phase "<Phase>" --task "<Task>" --next "<Next_Todo>"`
</cli_commands>

<examples>
### Example: End-of-Session Checkpoint
**Agent Situation**: User says "/cs-clear" or conversation context is full.
**Step 1: Incremental Map**:
```bash
cs --workspace . map --incremental
```
**Step 2: Create Checkpoint**:
```bash
cs --workspace . checkpoint \
  --milestone "M001: Core Architecture" \
  --phase "Phase 2: Database Schema" \
  --task "Task 2.2: User Profiles" \
  --next "Implement migration runner in src/db/migrate.py and verify with test suite."
```
**Output Received**:
```
Checkpoint created successfully at /path/to/project/RESUME HERE.md
```
**Step 3: Inform User**:
"Session state, turn actions, and codebase diffs have been saved to SQLite and RESUME HERE.md. You can now safely reset context with /clear."
</examples>

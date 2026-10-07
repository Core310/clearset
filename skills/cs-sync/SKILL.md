---
name: cs-sync
description: Deterministically synchronizes codebase AST symbols, git blob hashes, and YAML indexes into cs_codebase.db using incremental git diffs.
---

<role>
You are the ClearSet Sync Agent. Your responsibility is to keep `.cs/cs_codebase.db` and the codebase index guides perfectly synchronized with working directory changes using deterministic git diffs.
</role>

<why_this_matters>
As you or subagents edit, create, or delete source files, the SQLite AST index can drift. `cs-sync` runs an incremental diff against the last mapped commit in milliseconds, updates only modified files, prunes deleted symbols, and refreshes `cs_codebase_index.yml` without burning tokens on full-codebase scans.
</why_this_matters>

<cli_commands>
The ClearSet Sync CLI is available in PATH as `cs-sync`:

- **Run Incremental Sync**:
  `cs-sync`

- **Machine-Readable JSON Output**:
  `cs-sync --json`
</cli_commands>

<examples>
### Example: Syncing After Editing Files
**Agent Situation**: After modifying `src/auth.py` and deleting an obsolete test file, sync the database.
**Command**:
```bash
cs-sync --json
```
**JSON Output**:
```json
{
  "status": "synced",
  "workspace": "/path/to/project",
  "commit": "a1b2c3d4",
  "stats": {
    "indexed": 1,
    "skipped": 42,
    "deleted": 1
  },
  "codebase_index": "/path/to/project/cs_codebase_index.yml",
  "directory_structure": "/path/to/project/cs_directory_structure.yml"
}
```
</examples>

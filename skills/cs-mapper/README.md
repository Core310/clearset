# cs-mapper

`cs-mapper` scans files in the workspace, extracts code symbols and relationships, indexes them into SQLite, and outputs structured YAML guides.

## Incremental Git Diff Algorithm
1. Reads `last_scanned_commit` from SQLite table `git_tracker`.
2. Queries `git diff --name-status <commit>` and uncommitted changes via `git status --porcelain`.
3. Computes `git hash-object` for modified candidates.
4. If a file's hash has not changed, AST parsing is bypassed entirely.
5. If modified, deletes old records for that file and re-inserts updated symbols, relationships, docstrings, and tags.
6. Prunes deleted files from all SQLite tables and FTS5 index.
7. Rebuilds `cs_codebase_index.yml` and `cs_directory_structure.yml`.

## Commands
```bash
# Full mapping pass
cs --workspace . map

# Fast incremental mapping pass
cs --workspace . map --incremental
```

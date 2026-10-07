#!/usr/bin/env python3
"""
ClearSet Sync (`cs-sync`): Deterministic Incremental AST & State Sync.
Scans incremental git diffs, re-indexes modified files into cs_codebase.db,
prunes deleted symbols, and updates YAML guides in milliseconds.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

from clearset.engine import (
    find_workspace,
    get_codebase_db_path,
    map_codebase,
    get_git_commit,
    CODEBASE_INDEX_YML,
    DIR_STRUCTURE_YML,
)


def sync_codebase_state(workspace: Path) -> Dict[str, Any]:
    codebase_db = get_codebase_db_path(workspace)
    if not codebase_db.exists():
        # First-time initialization
        stats = map_codebase(workspace, incremental=False)
        commit = get_git_commit(workspace)
        return {
            "status": "initialized",
            "workspace": str(workspace),
            "commit": commit,
            "stats": stats,
            "codebase_index": str(workspace / CODEBASE_INDEX_YML),
            "directory_structure": str(workspace / DIR_STRUCTURE_YML),
        }

    # Incremental update via git diff
    stats = map_codebase(workspace, incremental=True)
    commit = get_git_commit(workspace)
    return {
        "status": "synced",
        "workspace": str(workspace),
        "commit": commit,
        "stats": stats,
        "codebase_index": str(workspace / CODEBASE_INDEX_YML),
        "directory_structure": str(workspace / DIR_STRUCTURE_YML),
    }


def main():
    parser = argparse.ArgumentParser(
        description="ClearSet Sync (`cs-sync`): Deterministic AST & SQLite State Auto-Sync"
    )
    parser.add_argument("--workspace", "-w", default=".", help="Workspace root path")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = parser.parse_args()

    workspace = find_workspace(Path(args.workspace).resolve())
    result = sync_codebase_state(workspace)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        status = result["status"]
        stats = result["stats"]
        commit = result["commit"][:8] if result["commit"] != "non-git-workspace" else "non-git"
        print(f"ClearSet State [{status.upper()}] at commit {commit}:")
        print(f"  - Indexed/Updated: {stats.get('indexed', 0)} files")
        print(f"  - Unchanged:        {stats.get('skipped', 0)} files")
        print(f"  - Pruned:           {stats.get('deleted', 0)} files")


if __name__ == "__main__":
    main()

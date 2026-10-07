#!/usr/bin/env python3
"""
ClearSet Cleanup Tool (`cs-cleanup`) (grugbrain.dev principles)
- Standalone, modular, script-first (<300 lines).
- Swarm lock aware: never touches files locked by active swarm tasks in .cs/cs_turns.db.
- Categorized scanning: [A] Dead AST Symbols, [B] Bloat (>500 lines), [C] Cache/Temp Clutter, [D] Stale Blackboard Runs.
- Selective interactive apply.
- Deterministic formatting & unused import cleanup via ruff.
"""

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

IGNORED_DIRS = {
    ".git",
    ".cs",
    ".cta",
    ".planning",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    ".idea",
    ".vscode",
    ".gemini",
    ".agy",
    "app_backups",
    "archive",
    "backups",
    "logs",
}
SOURCE_EXTS = {".py", ".sh", ".yml", ".yaml", ".js", ".ts", ".c", ".cpp", ".rs"}


def get_swarm_locks(workspace: Path) -> Tuple[Set[str], List[str]]:
    """Query .cs/cs_turns.db for active swarm runs and locked target files."""
    cs_dir = get_cs_dir(workspace)
    db_path = cs_dir / "cs_turns.db"
    if not db_path.exists():
        db_path = cs_dir / "cta_turns.db"
    if not db_path.exists():
        return set(), []

    locked_files = set()
    active_runs = []
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT run_id, milestone, phase FROM swarm_runs WHERE status = 'ACTIVE'"
        )
        for row in cur.fetchall():
            active_runs.append(f"{row[0]} ({row[1]} / {row[2]})")

        cur.execute(
            "SELECT target_files FROM swarm_tasks WHERE status IN ('PENDING', 'CLAIMED')"
        )
        for (raw_targets,) in cur.fetchall():
            if raw_targets:
                try:
                    targets = json.loads(raw_targets)
                    for t in targets:
                        locked_files.add(str(Path(t).as_posix()))
                except json.JSONDecodeError:
                    pass
        conn.close()
    except sqlite3.Error:
        pass
    return locked_files, active_runs


def find_dead_symbols(workspace: Path, locked_files: Set[str]) -> List[Dict]:
    """Find dead AST symbols with 0 callers/references across the codebase."""
    cs_dir = get_cs_dir(workspace)
    db_path = cs_dir / "cs_codebase.db"
    if not db_path.exists():
        db_path = cs_dir / "cta_codebase.db"
    if not db_path.exists():
        return []

    dead = []
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT s.id, s.file_path, s.name, s.kind, s.line_start, s.visibility
            FROM symbols s
            WHERE s.kind IN ('function', 'method', 'class')
        """)
        symbols = cur.fetchall()

        # Cache file contents for fast reference scanning
        file_cache: Dict[str, str] = {}

        def get_content(rel_p: str) -> str:
            if rel_p not in file_cache:
                abs_p = workspace / rel_p
                if abs_p.exists():
                    try:
                        file_cache[rel_p] = abs_p.read_text(
                            encoding="utf-8", errors="ignore"
                        )
                    except OSError:
                        file_cache[rel_p] = ""
                else:
                    file_cache[rel_p] = ""
            return file_cache[rel_p]

        for s_id, f_path, name, kind, line_start, vis in symbols:
            norm_path = Path(f_path).as_posix()
            # Ignore locked, backup, or entrypoint files
            if norm_path in locked_files or any(
                part in IGNORED_DIRS for part in Path(norm_path).parts
            ):
                continue
            if name.startswith(("test_", "Test", "__")) or name == "main":
                continue
            if norm_path.endswith(("__init__.py", "cli.py", "app.py", "main.py")):
                continue
            if vis == "public":
                continue

            own_content = get_content(norm_path)
            pattern = re.compile(rf"\b{re.escape(name)}\b")
            own_matches = len(pattern.findall(own_content))

            # If referenced more than once in its own file (definition + call), not dead
            if own_matches > 1:
                continue

            # Check if referenced across other source files
            is_referenced = False
            for root, dirs, files in os.walk(workspace):
                dirs[:] = [
                    d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")
                ]
                for file in files:
                    fp = Path(root) / file
                    if fp.suffix in SOURCE_EXTS:
                        rel = fp.relative_to(workspace).as_posix()
                        if rel == norm_path:
                            continue
                        text = get_content(rel)
                        if pattern.search(text):
                            is_referenced = True
                            break
                if is_referenced:
                    break

            if not is_referenced:
                dead.append(
                    {
                        "id": f"A{len(dead) + 1}",
                        "file": norm_path,
                        "name": name,
                        "kind": kind,
                        "line": line_start,
                    }
                )
        conn.close()
    except sqlite3.Error:
        pass
    return dead


def find_bloat(workspace: Path, max_lines: int = 500) -> List[Dict]:
    """Flag source files exceeding max line threshold (Grug: fear big file)."""
    bloat = []
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
        for file in files:
            p = Path(root) / file
            if p.suffix in SOURCE_EXTS:
                rel = p.relative_to(workspace).as_posix()
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        lines = sum(1 for _ in f)
                    if lines > max_lines:
                        bloat.append(
                            {"id": f"B{len(bloat) + 1}", "file": rel, "lines": lines}
                        )
                except OSError:
                    continue
    return sorted(bloat, key=lambda x: x["lines"], reverse=True)


def find_clutter(workspace: Path, locked_files: Set[str]) -> List[Dict]:
    """Find cache directories, orphan tmp files, and compiler cache."""
    clutter = []
    cache_dirs = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
    temp_exts = {".pyc", ".pyo", ".orig", ".tmp"}

    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS or d in cache_dirs]
        for d in list(dirs):
            if d in cache_dirs:
                p = Path(root) / d
                rel = p.relative_to(workspace).as_posix()
                if rel not in locked_files:
                    clutter.append(
                        {"id": f"C{len(clutter) + 1}", "path": rel, "is_dir": True}
                    )
                dirs.remove(d)

        for f in files:
            p = Path(root) / f
            if p.suffix in temp_exts or f.endswith("~"):
                rel = p.relative_to(workspace).as_posix()
                if rel not in locked_files:
                    clutter.append(
                        {"id": f"C{len(clutter) + 1}", "path": rel, "is_dir": False}
                    )
    return clutter


def find_stale_swarm_runs(workspace: Path) -> List[Dict]:
    """Find completed/failed swarm runs eligible for archiving/pruning."""
    cs_dir = get_cs_dir(workspace)
    db_path = cs_dir / "cs_turns.db"
    if not db_path.exists():
        db_path = cs_dir / "cta_turns.db"
    if not db_path.exists():
        return []
    stale = []
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT run_id, status, completed_at FROM swarm_runs WHERE status IN ('COMPLETED', 'FAILED')"
        )
        for row in cur.fetchall():
            cur.execute(
                "SELECT COUNT(*) FROM swarm_messages WHERE run_id = ?", (row[0],)
            )
            (msg_count,) = cur.fetchone()
            stale.append(
                {
                    "id": f"D{len(stale) + 1}",
                    "run_id": row[0],
                    "status": row[1],
                    "completed_at": row[2] or "unknown",
                    "messages": msg_count,
                }
            )
        conn.close()
    except sqlite3.Error:
        pass
    return stale


def run_ruff(
    workspace: Path, targets: Optional[List[str]] = None, check_only: bool = False
) -> int:
    """Run ruff check --fix (unused imports) and ruff format deterministically."""
    ruff_bin = (
        shutil.which("ruff")
        or shutil.which(str(Path.home() / ".local" / "bin" / "ruff"))
        or shutil.which(str(Path.home() / ".cargo" / "bin" / "ruff"))
    )
    if not ruff_bin:
        print(
            "[WARNING] 'ruff' binary not found. Install via: pipx install ruff (or cargo install ruff)"
        )
        return 1

    cmd_targets = targets if targets else ["."]
    if check_only:
        print(f"--> Checking unused imports and format on: {cmd_targets}")
        ret1 = subprocess.run(
            [ruff_bin, "check", "--select", "F401,I"] + cmd_targets, cwd=workspace
        ).returncode
        ret2 = subprocess.run(
            [ruff_bin, "format", "--check"] + cmd_targets, cwd=workspace
        ).returncode
        return ret1 or ret2

    print(f"--> Running ruff check --select F401,I --fix on: {cmd_targets}")
    subprocess.run(
        [ruff_bin, "check", "--select", "F401,I", "--fix"] + cmd_targets, cwd=workspace
    )
    print(f"--> Running deterministic ruff format on: {cmd_targets}")
    return subprocess.run([ruff_bin, "format"] + cmd_targets, cwd=workspace).returncode


def cmd_scan(args: argparse.Namespace) -> None:
    ws = Path(args.workspace).resolve()
    locked_files, active_runs = get_swarm_locks(ws)
    print(f"\n=== CLEARSET CLEANUP SCAN: {ws} ===")
    if active_runs:
        print(
            f"[!] Active Swarm Runs Detected ({len(active_runs)}): {', '.join(active_runs)}"
        )
        print(
            f"    Protected Locked Files ({len(locked_files)}): {sorted(list(locked_files))[:5]}...\n"
        )
    else:
        print("[*] No active swarms running. All files unlocked.\n")

    dead = find_dead_symbols(ws, locked_files)
    bloat = find_bloat(ws, args.max_lines)
    clutter = find_clutter(ws, locked_files)
    stale_runs = find_stale_swarm_runs(ws)

    print(f"--- [A] Dead AST Symbols ({len(dead)}) ---")
    for d in dead[:10]:
        print(
            f"  [{d['id']}] {d['file']}:{d['line']} - {d['kind']} {d['name']}() (0 callers)"
        )
    if len(dead) > 10:
        print(f"  ... and {len(dead) - 10} more symbols")

    print(f"\n--- [B] File Bloat Sentinel (>{args.max_lines} lines) ({len(bloat)}) ---")
    for b in bloat[:8]:
        print(f"  [{b['id']}] {b['file']} ({b['lines']} lines)")

    print(f"\n--- [C] Cache & Temp Clutter ({len(clutter)}) ---")
    for c in clutter[:10]:
        t = "DIR " if c["is_dir"] else "FILE"
        print(f"  [{c['id']}] [{t}] {c['path']}")
    if len(clutter) > 10:
        print(f"  ... and {len(clutter) - 10} more clutter items")

    print(f"\n--- [D] Stale Swarm Blackboard State ({len(stale_runs)}) ---")
    for s in stale_runs:
        print(
            f"  [{s['id']}] Run {s['run_id']} ({s['status']}) - {s['messages']} messages"
        )

    print(
        "\nTo apply removals interactively: cs-cleanup apply --select C,D (or C1,D1,A1)"
    )


def cmd_apply(args: argparse.Namespace) -> None:
    ws = Path(args.workspace).resolve()
    locked_files, _ = get_swarm_locks(ws)
    selected = {s.strip().upper() for s in args.select.split(",") if s.strip()}
    print(f"\n[*] Applying selective cleanup for keys: {sorted(list(selected))}")

    # Process Cache Clutter
    clutter = find_clutter(ws, locked_files)
    for c in clutter:
        if "C" in selected or c["id"] in selected:
            target = ws / c["path"]
            if target.exists():
                print(f"  [-] Deleting clutter: {c['path']}")
                if not args.dry_run:
                    if c["is_dir"]:
                        shutil.rmtree(target, ignore_errors=True)
                    else:
                        target.unlink(missing_ok=True)

    # Process Stale Swarms & DB Vacuum
    stale_runs = find_stale_swarm_runs(ws)
    cs_dir = get_cs_dir(ws)
    db_path = cs_dir / "cs_turns.db"
    if not db_path.exists():
        db_path = cs_dir / "cta_turns.db"
    if db_path.exists():
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        pruned_any = False
        for s in stale_runs:
            if "D" in selected or s["id"] in selected:
                print(f"  [-] Pruning swarm run: {s['run_id']}")
                if not args.dry_run:
                    cur.execute(
                        "DELETE FROM swarm_messages WHERE run_id = ?", (s["run_id"],)
                    )
                    cur.execute(
                        "DELETE FROM swarm_tasks WHERE run_id = ?", (s["run_id"],)
                    )
                    cur.execute(
                        "DELETE FROM swarm_runs WHERE run_id = ?", (s["run_id"],)
                    )
                    pruned_any = True
        if pruned_any and not args.dry_run:
            conn.commit()
            print("  [*] Vacuuming SQLite database...")
            cur.execute("VACUUM;")
        conn.close()

    # Format if requested
    if args.format:
        print("\n[*] Invoking deterministic ruff styler/linter...")
        run_ruff(ws, check_only=args.dry_run)

    print("\n[✓] Cleanup action completed.")


def main():
    parser = argparse.ArgumentParser(
        description="ClearSet Cleanup (`cs-cleanup`): Grug-principled, swarm-aware codebase cleaner"
    )
    parser.add_argument("--workspace", "-w", default=".", help="Workspace path")
    subparsers = parser.add_subparsers(dest="command")

    p_scan = subparsers.add_parser(
        "scan", help="Scan codebase and blackboard for cleanup candidates"
    )
    p_scan.add_argument(
        "--max-lines", type=int, default=500, help="Line threshold for bloat sentinel"
    )

    p_apply = subparsers.add_parser("apply", help="Selectively apply cleanup actions")
    p_apply.add_argument(
        "--select",
        "-s",
        required=True,
        help="Comma-separated bucket or item IDs (e.g., 'C,D' or 'C1,D1')",
    )
    p_apply.add_argument(
        "--dry-run", action="store_true", help="Simulate without deleting"
    )
    p_apply.add_argument(
        "--format",
        action="store_true",
        help="Run ruff formatting/unused-import cleanup after applying",
    )

    p_style = subparsers.add_parser(
        "style", help="Run deterministic ruff format & unused import cleanup"
    )
    p_style.add_argument(
        "paths", nargs="*", default=None, help="Specific files or directories to format"
    )
    p_style.add_argument(
        "--check",
        action="store_true",
        help="Only check formatting, do not write changes",
    )

    args = parser.parse_args()
    if args.command == "scan" or not args.command:
        if not hasattr(args, "max_lines"):
            args.max_lines = 500
        cmd_scan(args)
    elif args.command == "apply":
        cmd_apply(args)
    elif args.command == "style":
        ws = Path(args.workspace).resolve()
        sys.exit(run_ruff(ws, targets=args.paths, check_only=args.check))


if __name__ == "__main__":
    main()

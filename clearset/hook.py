#!/usr/bin/env python3
"""
ClearSet Post-Edit Hook Engine (`cs hook` / `cs-hook`)
Provides deterministic post-edit syntax validation and automatic AST database synchronization.
Zero external dependencies (pure Python standard library).
"""

import sys
import os
import ast
import json
import argparse
import py_compile
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional

from clearset.engine import find_workspace, get_cs_dir
from clearset.sync import sync_codebase_state


def validate_file_syntax(target_file: Path) -> List[Dict[str, Any]]:
    """Validates file syntax deterministically using standard library parsers."""
    errors: List[Dict[str, Any]] = []
    if not target_file.exists():
        return [{"line": 1, "column": 1, "message": f"File does not exist: {target_file}", "source": "filesystem"}]

    suffix = target_file.suffix.lower()

    if suffix == ".py":
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                source = f.read()
            ast.parse(source, filename=str(target_file))
        except SyntaxError as e:
            errors.append({
                "line": e.lineno or 1,
                "column": e.offset or 1,
                "message": f"SyntaxError: {e.msg}",
                "text": e.text.strip() if e.text else "",
                "source": "ast",
            })
        except Exception as e:
            errors.append({
                "line": 1,
                "column": 1,
                "message": f"Python Parse Error: {str(e)}",
                "source": "python",
            })

    elif suffix == ".json":
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                json.load(f)
        except json.JSONDecodeError as e:
            errors.append({
                "line": e.lineno,
                "column": e.colno,
                "message": f"JSONDecodeError: {e.msg}",
                "source": "json",
            })

    elif suffix in (".sh", ".bash"):
        try:
            res = subprocess.run(
                ["bash", "-n", str(target_file)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode != 0:
                err_msg = res.stderr.strip() or "Bash syntax error"
                errors.append({
                    "line": 1,
                    "column": 1,
                    "message": err_msg,
                    "source": "bash",
                })
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

    return errors


def run_post_edit_hook(
    file_path: str,
    workspace: Optional[Path] = None,
    auto_sync: bool = True,
) -> Dict[str, Any]:
    """Runs post-edit hook: validates file syntax and syncs codebase AST index."""
    target = Path(file_path).resolve()
    
    if workspace is None:
        workspace = find_workspace(target.parent if target.exists() else Path.cwd())

    # 1. Syntax & lint checks
    errors = validate_file_syntax(target)
    syntax_passed = len(errors) == 0

    # 2. Automated codebase sync if valid syntax
    sync_result: Optional[Dict[str, Any]] = None
    if auto_sync and syntax_passed and ((workspace / ".cs").exists() or (workspace / ".cta").exists() or (workspace / ".git").exists()):
        try:
            sync_result = sync_codebase_state(workspace)
        except Exception as e:
            sync_result = {"status": "error", "error": str(e)}

    status = "PASSED" if syntax_passed else "FAILED"

    return {
        "status": status,
        "file": str(target),
        "workspace": str(workspace),
        "passed": syntax_passed,
        "errors": errors,
        "synced": sync_result is not None and sync_result.get("status") == "synced",
        "sync_result": sync_result,
    }


def main():
    parser = argparse.ArgumentParser(
        description="ClearSet Post-Edit Hook (`cs hook post-edit`): Automatic AST Sync & Syntax Linter"
    )
    parser.add_argument("file", nargs="?", default=None, help="Path to edited file (reads stdin if omitted)")
    parser.add_argument("--workspace", "-w", help="Workspace root path")
    parser.add_argument("--no-sync", action="store_true", help="Skip automatic AST sync")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    args = parser.parse_args()

    target_file = args.file
    ws = Path(args.workspace).resolve() if args.workspace else None
    from_hook = False

    if not target_file or target_file == "-":
        if not sys.stdin.isatty():
            try:
                stdin_data = sys.stdin.read().strip()
                if stdin_data:
                    try:
                        payload = json.loads(stdin_data)
                        if isinstance(payload, dict):
                            from_hook = True
                            tool_call = payload.get("toolCall", {})
                            tool_args = tool_call.get("args", {})
                            target_file = (
                                tool_args.get("TargetFile")
                                or tool_args.get("file_path")
                                or tool_args.get("path")
                            )
                            ws_paths = payload.get("workspacePaths", [])
                            if not ws and ws_paths:
                                ws = Path(ws_paths[0]).resolve()
                    except json.JSONDecodeError:
                        target_file = stdin_data
            except Exception:
                pass

    if not target_file:
        if from_hook or not sys.stdin.isatty():
            print(json.dumps({}))
            sys.exit(0)
        else:
            parser.print_help()
            sys.exit(1)

    res = run_post_edit_hook(
        file_path=target_file,
        workspace=ws,
        auto_sync=not args.no_sync,
    )

    if from_hook:
        # Antigravity PostToolUse lifecycle hook contract requires {} on stdout
        if not res["passed"]:
            print(f"[POST-EDIT HOOK ERROR]: {res['file']} has syntax errors:", file=sys.stderr)
            for err in res["errors"]:
                line = err.get("line", 1)
                col = err.get("column", 1)
                msg = err.get("message", "Error")
                print(f"  Line {line}, Col {col}: {msg}", file=sys.stderr)
                if "text" in err and err["text"]:
                    print(f"    {err['text']}", file=sys.stderr)
        print(json.dumps({}))
        sys.exit(0 if res["passed"] else 1)

    if args.json:
        print(json.dumps(res, indent=2))
    else:
        if res["passed"]:
            sync_info = f" (AST synced: {res['sync_result'].get('stats', {})})" if res["synced"] else ""
            print(f"[POST-EDIT HOOK]: {res['file']} syntax valid{sync_info}")
        else:
            print(f"[POST-EDIT HOOK ERROR]: {res['file']} has syntax errors:", file=sys.stderr)
            for err in res["errors"]:
                line = err.get("line", 1)
                col = err.get("column", 1)
                msg = err.get("message", "Error")
                print(f"  Line {line}, Col {col}: {msg}", file=sys.stderr)
                if "text" in err and err["text"]:
                    print(f"    {err['text']}", file=sys.stderr)

    sys.exit(0 if res["passed"] else 1)


if __name__ == "__main__":
    main()

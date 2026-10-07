#!/usr/bin/env python3
"""
ClearSet Gate (`cs-gate`): Deterministic Test Gate & Automated Turn Auditor.
Executes test/verification commands, captures exit codes and logs, and
automatically logs the audit result to cs_turns.db.
"""

import argparse
import json
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from clearset.engine import (
    find_workspace,
    get_turns_db_path,
    log_turn_action,
)


def run_verification_gate(
    workspace: Path,
    command_str: str,
    milestone: str = "M001",
    phase: str = "01",
    task: str = "verification",
    files: Optional[List[str]] = None,
    record_to_db: bool = True,
    timeout_seconds: int = 120,
) -> Dict[str, Any]:
    cmd_parts = shlex.split(command_str)
    try:
        proc = subprocess.run(
            cmd_parts,
            cwd=workspace,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
        )
        exit_code = proc.returncode
        stdout_output = proc.stdout.strip()
        stderr_output = proc.stderr.strip()
    except subprocess.TimeoutExpired:
        exit_code = 124
        stdout_output = ""
        stderr_output = f"Command timed out after {timeout_seconds} seconds."
    except Exception as e:
        exit_code = 1
        stdout_output = ""
        stderr_output = f"Execution error: {str(e)}"

    passed = (exit_code == 0)
    status_str = "PASSED" if passed else "FAILED"
    summary_text = stdout_output.splitlines()[-1] if stdout_output else (stderr_output.splitlines()[-1] if stderr_output else "")

    action_id = None
    if record_to_db:
        turns_db = get_turns_db_path(workspace)
        if turns_db.exists():
            desc = f"Gate check: `{command_str}` -> {status_str} (exit {exit_code})"
            action_id = log_turn_action(
                workspace=workspace,
                session_id="active-session",
                milestone=milestone,
                phase=phase,
                task=task,
                action_type="VERIFICATION",
                description=desc,
                status=status_str,
                files=files or [],
                summary=summary_text,
            )

    return {
        "status": status_str,
        "exit_code": exit_code,
        "passed": passed,
        "command": command_str,
        "summary": summary_text,
        "stdout": stdout_output,
        "stderr": stderr_output,
        "logged_action_id": action_id,
    }


def main():
    parser = argparse.ArgumentParser(
        description="ClearSet Gate (`cs-gate`): Deterministic Test Runner & SQLite Audit Gate"
    )
    parser.add_argument("command", help="Command to execute (e.g., 'pytest tests/' or 'ruff check .')")
    parser.add_argument("--workspace", "-w", default=".", help="Workspace root path")
    parser.add_argument("--milestone", "-m", default="M001", help="Milestone identifier")
    parser.add_argument("--phase", "-p", default="01", help="Phase identifier")
    parser.add_argument("--task", "-t", default="verification", help="Task identifier")
    parser.add_argument("--files", nargs="*", default=[], help="Associated target files")
    parser.add_argument("--no-db", action="store_true", help="Do not write audit entry to cs_turns.db")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    args = parser.parse_args()
    workspace = find_workspace(Path(args.workspace).resolve())

    res = run_verification_gate(
        workspace=workspace,
        command_str=args.command,
        milestone=args.milestone,
        phase=args.phase,
        task=args.task,
        files=args.files,
        record_to_db=not args.no_db,
    )

    if args.json:
        print(json.dumps(res, indent=2))
    else:
        status_label = "✅ PASSED" if res["passed"] else "❌ FAILED"
        print(f"ClearSet Gate: {status_label} (Exit Code: {res['exit_code']})")
        print(f"Command: {res['command']}")
        if res["logged_action_id"]:
            print(f"Audit recorded to cs_turns.db with ID: #{res['logged_action_id']}")
        if res["stdout"]:
            print(f"\n--- Output ---\n{res['stdout'][:500]}")
        if res["stderr"]:
            print(f"\n--- Stderr ---\n{res['stderr'][:500]}")

    sys.exit(res["exit_code"])


if __name__ == "__main__":
    main()

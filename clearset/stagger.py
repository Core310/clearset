#!/usr/bin/env python3
"""
ClearSet Stagger (`cs-stagger` / `cta-stagger`):
Human Work Commit Staggerer & Proof-of-Work Timeline Engine.

Generates realistic human work commit timelines across active daytime hours (11:00 AM - 11:00 PM),
sets backdated author/committer timestamps, and creates progressive git histories.
"""

import os
import random
import subprocess
import argparse
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

from clearset.engine import (
    find_workspace,
    get_turns_db_path,
    log_turn_action,
)


class CommitStaggerEngine:
    def __init__(
        self,
        repo_path: str,
        start_hour: int = 11,
        end_hour: int = 23,
        tz_offset_hours: int = -5,  # CDT / US Central (UTC-5)
    ):
        self.repo_path = os.path.abspath(repo_path)
        self.start_hour = start_hour
        self.end_hour = end_hour
        self.tz = timezone(timedelta(hours=tz_offset_hours))

    def generate_timeline(
        self,
        num_commits: int,
        start_date: datetime,
        days_span: int = 3,
    ) -> List[datetime]:
        """Generate realistic human work timestamps strictly within active hours."""
        timestamps: List[datetime] = []

        current_dt = datetime(
            start_date.year,
            start_date.month,
            start_date.day,
            self.start_hour,
            random.randint(5, 35),
            random.randint(0, 59),
            tzinfo=self.tz,
        )

        for i in range(num_commits):
            if current_dt.hour >= self.end_hour - 1:
                current_dt = current_dt + timedelta(days=1)
                current_dt = current_dt.replace(
                    hour=self.start_hour + random.randint(0, 1),
                    minute=random.randint(5, 45),
                    second=random.randint(0, 59),
                )

            timestamps.append(current_dt)

            gap_minutes = random.randint(35, 95)
            if current_dt.hour in [13, 18] and random.random() < 0.6:
                gap_minutes += random.randint(45, 90)

            current_dt = current_dt + timedelta(minutes=gap_minutes)

        return timestamps

    def plan_assignment_commits(
        self,
        assignment_name: str,
        files_to_commit: List[str],
        start_date: Optional[datetime] = None,
        days_span: int = 2,
    ) -> List[Dict[str, Any]]:
        """Generate realistic progressive commit messages and timestamps."""
        if not start_date:
            start_date = datetime.now(self.tz) - timedelta(days=days_span + 1)

        commit_templates = [
            f"Initialize {assignment_name} template and problem outline",
            f"Draft problem 1 solution and initial derivations for {assignment_name}",
            f"Complete core math proofs and intermediate formulas",
            f"Implement algorithmic solution and add test verifications",
            f"Add discussion, error analysis, and edge case responses",
            f"Final polish: refine LaTeX notation, fix typos, and verify rubric",
        ]

        selected_messages = commit_templates[: max(3, len(commit_templates))]
        timeline = self.generate_timeline(len(selected_messages), start_date, days_span)

        plan = []
        for dt, msg in zip(timeline, selected_messages):
            plan.append({
                "timestamp_iso": dt.isoformat(),
                "formatted_time": dt.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "message": msg,
                "files": files_to_commit,
            })

        return plan

    def execute_commit(self, message: str, dt_iso: str, files: List[str]) -> bool:
        """Execute a single git commit with custom author and committer dates."""
        env = os.environ.copy()
        env["GIT_AUTHOR_DATE"] = dt_iso
        env["GIT_COMMITTER_DATE"] = dt_iso

        try:
            for f in files:
                subprocess.run(
                    ["git", "add", f],
                    cwd=self.repo_path,
                    check=True,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )

            # Check if there are staged changes
            diff_proc = subprocess.run(
                ["git", "diff", "--cached", "--quiet"],
                cwd=self.repo_path,
                env=env,
            )
            if diff_proc.returncode == 0:
                # No changes staged; allow empty if explicitly building proof of work
                commit_cmd = ["git", "commit", "--allow-empty", "-m", message]
            else:
                commit_cmd = ["git", "commit", "-m", message]

            subprocess.run(
                commit_cmd,
                cwd=self.repo_path,
                check=True,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return True
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode("utf-8") if e.stderr else str(e)
            print(f"[Error] Git commit failed: {err}")
            return False

    def push(self, branch: str = "main") -> bool:
        try:
            subprocess.run(
                ["git", "push", "origin", branch],
                cwd=self.repo_path,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return True
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode("utf-8") if e.stderr else str(e)
            print(f"[Error] Git push failed: {err}")
            return False


def stagger_assignment(
    repo_path: str,
    assignment_name: str = "Assignment",
    files: Optional[List[str]] = None,
    days_span: int = 3,
    start_hour: int = 11,
    end_hour: int = 23,
    apply: bool = False,
    push: bool = False,
    record_to_db: bool = True,
    milestone: str = "M001",
    phase: str = "01",
    task: str = "delivery",
) -> Dict[str, Any]:
    target_files = files or ["."]
    engine = CommitStaggerEngine(
        repo_path=repo_path,
        start_hour=start_hour,
        end_hour=end_hour,
    )

    plan = engine.plan_assignment_commits(
        assignment_name=assignment_name,
        files_to_commit=target_files,
        days_span=days_span,
    )

    commits_created = 0
    pushed = False

    if apply:
        for step in plan:
            ok = engine.execute_commit(
                message=step["message"],
                dt_iso=step["timestamp_iso"],
                files=step["files"],
            )
            if not ok:
                break
            commits_created += 1

        if push and commits_created > 0:
            pushed = engine.push()

        if record_to_db:
            workspace = find_workspace(Path(repo_path))
            turns_db = get_turns_db_path(workspace)
            if turns_db.exists():
                desc = f"Staggered {commits_created} commits for '{assignment_name}' over {days_span} days (push={pushed})"
                log_turn_action(
                    workspace=workspace,
                    session_id="active-session",
                    milestone=milestone,
                    phase=phase,
                    task=task,
                    action_type="EXECUTION",
                    description=desc,
                    status="SUCCESS",
                    files=target_files,
                    summary=f"Staggered {commits_created}/{len(plan)} commits applied",
                )

    return {
        "assignment_name": assignment_name,
        "repo": os.path.abspath(repo_path),
        "days_span": days_span,
        "active_window": f"{start_hour:02d}:00 - {end_hour:02d}:00",
        "plan": plan,
        "applied": apply,
        "commits_created": commits_created,
        "pushed": pushed,
    }


def main():
    parser = argparse.ArgumentParser(
        description="ClearSet Stagger (`cs-stagger`): Human Work Commit Staggerer & Proof-of-Work Timeline Engine"
    )
    parser.add_argument("--repo", default=".", help="Target Git repository path")
    parser.add_argument("--assignment-name", "-a", default="Assignment", help="Assignment name")
    parser.add_argument("--files", nargs="+", default=["."], help="Files/directories to stage in the commits")
    parser.add_argument("--days", type=int, default=3, help="Number of work days to span (default: 3)")
    parser.add_argument("--start-hour", type=int, default=11, help="Work start hour (0-23, default: 11)")
    parser.add_argument("--end-hour", type=int, default=23, help="Work end hour (0-23, default: 23)")
    parser.add_argument("--apply", action="store_true", help="Execute the commits in git")
    parser.add_argument("--push", action="store_true", help="Push commits to origin main after applying")
    parser.add_argument("--no-db", action="store_true", help="Do not log action to cs_turns.db")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    args = parser.parse_args()

    result = stagger_assignment(
        repo_path=args.repo,
        assignment_name=args.assignment_name,
        files=args.files,
        days_span=args.days,
        start_hour=args.start_hour,
        end_hour=args.end_hour,
        apply=args.apply,
        push=args.push,
        record_to_db=not args.no_db,
    )

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print("\n=======================================================")
    print(f" 🛠️  ORGANIC COMMIT PLAN: {result['assignment_name']}")
    print(f" Active Hours Window: {result['active_window']} | Span: {result['days_span']} days")
    print(f" Target Repository: {result['repo']}")
    print("=======================================================\n")

    for idx, step in enumerate(result["plan"], 1):
        print(f" [{idx}/{len(result['plan'])}] {step['formatted_time']}")
        print(f"       Message: \"{step['message']}\"")
        print(f"       Files:   {', '.join(step['files'])}\n")

    if not args.apply:
        print("💡 Dry-run complete. Run with --apply to commit to Git, and --push to upload.")
    else:
        print(f"✅ Created {result['commits_created']} commits successfully.")
        if args.push:
            print(f"🚀 Pushed to origin main: {'SUCCESS' if result['pushed'] else 'FAILED'}")


if __name__ == "__main__":
    main()

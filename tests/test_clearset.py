"""
Unit tests for ClearSet (cs) core engine, retrieval, sync, and gates.
"""

import json
import tempfile
import unittest
from pathlib import Path

import clearset as cs
from clearset.mcp import handle_tool_call, TOOLS


class TestClearSetCore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)

        # Create sample python file
        self.src_dir = self.workspace / "src"
        self.src_dir.mkdir(parents=True, exist_ok=True)
        self.sample_file = self.src_dir / "calculator.py"
        self.sample_file.write_text(
            '''"""Calculator module."""

def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

class MathEngine:
    """Math computation engine."""

    def multiply(self, x: float, y: float) -> float:
        """Multiply x and y."""
        return x * y
''',
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_init_and_map_codebase(self):
        cs_dir = cs.get_cs_dir(self.workspace)
        turns_db = cs.get_turns_db_path(self.workspace)
        codebase_db = cs.get_codebase_db_path(self.workspace)

        cs.init_turns_db(turns_db)
        cs.init_codebase_db(codebase_db)

        self.assertTrue(turns_db.exists())
        self.assertTrue(codebase_db.exists())

        stats = cs.map_codebase(self.workspace, incremental=False)
        self.assertGreaterEqual(stats["indexed"], 1)

        # Test symbol retrieval as structured data
        sym_data = cs.fetch_symbol_data(self.workspace, "add")
        self.assertEqual(sym_data["query"], "add")
        self.assertEqual(sym_data["count"], 1)
        self.assertEqual(sym_data["symbols"][0]["name"], "add")
        self.assertEqual(sym_data["symbols"][0]["kind"], "function")
        self.assertIn("def add", sym_data["symbols"][0]["signature"])

        # Test outline retrieval as structured data
        outline = cs.fetch_outline_data(self.workspace, "src/calculator.py")
        self.assertEqual(outline["count"], 3)  # add, MathEngine, multiply

        # Test slice retrieval as structured data
        slice_data = cs.fetch_file_slice_data(self.workspace, "src/calculator.py", 3, 5)
        self.assertEqual(slice_data["start_line"], 3)
        self.assertEqual(slice_data["end_line"], 5)
        self.assertEqual(len(slice_data["lines"]), 3)

    def test_turns_and_checkpoints(self):
        turns_db = cs.get_turns_db_path(self.workspace)
        cs.init_turns_db(turns_db)

        aid = cs.log_turn_action(
            workspace=self.workspace,
            session_id="test-session",
            milestone="M001",
            phase="01",
            task="1.1",
            action_type="EXECUTION",
            description="Created calculator tests",
            status="SUCCESS",
            files=["src/calculator.py"],
            summary="All tests pass",
        )
        self.assertIsInstance(aid, int)

        history = cs.fetch_turn_history_data(self.workspace, limit=5)
        self.assertEqual(history["count_actions"], 1)
        self.assertEqual(history["actions"][0]["description"], "Created calculator tests")

        # Checkpoint
        chk_path = cs.create_checkpoint(
            workspace=self.workspace,
            milestone="M001",
            phase="01",
            task="1.1",
            next_todo="Add division method",
        )
        self.assertTrue(chk_path.exists())

        resume = cs.load_resume_state(self.workspace)
        self.assertIn("M001", resume["resume_content"])
        self.assertIn("Add division method", resume["resume_content"])

    def test_sync_codebase_state(self):
        res = cs.sync_codebase_state(self.workspace)
        self.assertIn("stats", res)
        self.assertGreaterEqual(res["stats"]["indexed"], 1)

    def test_verification_gate(self):
        turns_db = cs.get_turns_db_path(self.workspace)
        cs.init_turns_db(turns_db)

        # Run passing command
        gate_res = cs.run_verification_gate(
            workspace=self.workspace,
            command_str="python3 -c 'print(\"ok\")'",
            milestone="M001",
            phase="01",
            task="gate-test",
            record_to_db=True,
        )
        self.assertEqual(gate_res["status"], "PASSED")
        self.assertEqual(gate_res["exit_code"], 0)
        self.assertTrue(gate_res["passed"])
        self.assertIsNotNone(gate_res["logged_action_id"])

        # Run failing command
        fail_res = cs.run_verification_gate(
            workspace=self.workspace,
            command_str="python3 -c 'import sys; sys.exit(2)'",
            record_to_db=False,
        )
        self.assertEqual(fail_res["status"], "FAILED")
        self.assertEqual(fail_res["exit_code"], 2)
        self.assertFalse(fail_res["passed"])

    def test_mcp_tool_handlers(self):
        turns_db = cs.get_turns_db_path(self.workspace)
        codebase_db = cs.get_codebase_db_path(self.workspace)
        cs.init_turns_db(turns_db)
        cs.init_codebase_db(codebase_db)
        cs.map_codebase(self.workspace, incremental=False)

        # Verify tool schemas exist
        self.assertGreaterEqual(len(TOOLS), 10)

        # Test MCP tool call
        data = handle_tool_call(
            "cs_fetch_symbol",
            {"name": "add", "workspace": str(self.workspace)},
        )
        self.assertEqual(data["query"], "add")
        self.assertEqual(len(data["symbols"]), 1)

    def test_post_edit_hook(self):
        from clearset.hook import validate_file_syntax, run_post_edit_hook

        # Valid file
        valid_res = run_post_edit_hook(
            file_path=str(self.sample_file),
            workspace=self.workspace,
            auto_sync=True,
        )
        self.assertEqual(valid_res["status"], "PASSED")
        self.assertTrue(valid_res["passed"])
        self.assertEqual(len(valid_res["errors"]), 0)

        # Invalid Python syntax file
        broken_file = self.workspace / "broken.py"
        broken_file.write_text("def syntax_err(", encoding="utf-8")
        err_res = run_post_edit_hook(
            file_path=str(broken_file),
            workspace=self.workspace,
            auto_sync=True,
        )
        self.assertEqual(err_res["status"], "FAILED")
        self.assertFalse(err_res["passed"])
        self.assertGreaterEqual(len(err_res["errors"]), 1)
        self.assertEqual(err_res["errors"][0]["source"], "ast")

        # Invalid JSON file
        broken_json = self.workspace / "broken.json"
        broken_json.write_text("{ unquoted: 123", encoding="utf-8")
        json_errs = validate_file_syntax(broken_json)
        self.assertGreaterEqual(len(json_errs), 1)
        self.assertEqual(json_errs[0]["source"], "json")

    def test_swarm_worktree_isolation(self):
        import subprocess

        # Initialize git repo in workspace
        subprocess.run(["git", "init"], cwd=str(self.workspace), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(self.workspace), check=True)
        subprocess.run(["git", "config", "user.email", "tester@test.com"], cwd=str(self.workspace), check=True)
        subprocess.run(["git", "add", "."], cwd=str(self.workspace), check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(self.workspace), check=True)

        turns_db = cs.get_turns_db_path(self.workspace)
        cs.init_turns_db(turns_db)

        # Dispatch swarm task
        tasks = [
            {
                "task_id": "T01",
                "title": "Add subtract function",
                "role": "math-coder",
                "target_files": ["src/calculator.py"],
                "verification_cmd": "python3 -c 'print(1)'",
            }
        ]
        d_res = cs.swarm_dispatch(
            workspace=self.workspace,
            session_id="test-session",
            milestone="M001",
            phase="01",
            topology="scatter_gather",
            tasks_data=tasks,
            run_id="run-wt-01",
        )
        self.assertEqual(d_res["total_tasks"], 1)

        # Claim with worktree
        claimed = cs.swarm_claim(
            workspace=self.workspace,
            worker_id="agent-worker-1",
            run_id="run-wt-01",
            worktree=True,
        )
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["task_id"], "T01")
        self.assertIn("worktree_path", claimed)
        self.assertEqual(claimed["worktree_branch"], "swarm/T01")

        wt_path = Path(claimed["worktree_path"])
        self.assertTrue(wt_path.exists())

        # Modify file inside worktree
        wt_file = wt_path / "src" / "calculator.py"
        self.assertTrue(wt_file.exists())
        with open(wt_file, "a", encoding="utf-8") as f:
            f.write("\ndef subtract(a: int, b: int) -> int:\n    return a - b\n")

        subprocess.run(["git", "add", "."], cwd=str(wt_path), check=True)
        subprocess.run(["git", "commit", "-m", "Implement subtract"], cwd=str(wt_path), check=True)

        # Verify main workspace does not have changes yet (isolation)
        main_calc = self.workspace / "src" / "calculator.py"
        self.assertNotIn("def subtract", main_calc.read_text(encoding="utf-8"))

        # Report task with merge and teardown
        rep = cs.swarm_report(
            workspace=self.workspace,
            task_id="T01",
            status="PASSED",
            exit_code=0,
            summary="Implemented subtract in isolated worktree",
            files=["src/calculator.py"],
            merge=True,
            teardown=True,
        )
        self.assertEqual(rep["status"], "PASSED")
        self.assertEqual(rep["merge_status"], "merged")
        self.assertTrue(rep["worktree_teardown"])

        # Verify worktree directory is removed from disk
        self.assertFalse(wt_path.exists())

        # Verify main workspace received the merged changes
        self.assertIn("def subtract", main_calc.read_text(encoding="utf-8"))

    def test_code_quality_auditor(self):
        # 1. Clean code passes
        clean_res = cs.audit_code(str(self.sample_file), record_to_db=False)
        self.assertTrue(clean_res["passed"])
        self.assertEqual(clean_res["verdict"], "PASS")
        self.assertGreaterEqual(clean_res["score"], 70)
        self.assertTrue(clean_res["syntax_valid"])
        self.assertEqual(len(clean_res["issues"]), 0)

        # 2. Syntax error blocks
        syntax_res = cs.audit_code("def broken(:\n    pass\n", record_to_db=False)
        self.assertFalse(syntax_res["passed"])
        self.assertEqual(syntax_res["verdict"], "BLOCKED")
        self.assertEqual(syntax_res["score"], 0)
        self.assertFalse(syntax_res["syntax_valid"])

        # 3. Silent exception swallowing blocks
        bad_code = "def foo():\n    try:\n        pass\n    except Exception:\n        pass\n"
        bad_res = cs.audit_code(bad_code, record_to_db=False)
        self.assertFalse(bad_res["passed"])
        self.assertEqual(bad_res["verdict"], "BLOCKED")
        self.assertGreaterEqual(len(bad_res["issues"]), 1)
        self.assertIn("Silent exception swallowing", bad_res["issues"][0])

        # 4. audit_target auto-detects code vs document
        target_res = cs.audit_target(str(self.sample_file), record_to_db=False)
        self.assertEqual(target_res["type"], "code")
        self.assertTrue(target_res["passed"])

    def test_clear_workspace(self):
        # 1. Initial clear with explicit parameters
        res1 = cs.clear_workspace(
            workspace=self.workspace,
            milestone="M002",
            phase="Phase 2",
            task="Task 2.1",
            next_todo="Run database migrations",
        )
        self.assertEqual(res1["status"], "ok")
        self.assertEqual(res1["milestone"], "M002")
        self.assertEqual(res1["phase"], "Phase 2")
        self.assertEqual(res1["task"], "Task 2.1")
        self.assertEqual(res1["next_todo"], "Run database migrations")

        continue_file = self.workspace / ".continue-here"
        resume_file = self.workspace / "RESUME HERE.md"
        self.assertTrue(continue_file.exists())
        self.assertTrue(resume_file.exists())

        c_text = continue_file.read_text(encoding="utf-8")
        self.assertIn("M002", c_text)
        self.assertIn("Phase 2", c_text)
        self.assertIn("Task 2.1", c_text)
        self.assertIn("Run database migrations", c_text)

        r_text = resume_file.read_text(encoding="utf-8")
        self.assertIn("M002", r_text)
        self.assertIn("Run database migrations", r_text)

        # 2. Subsequent clear inheriting milestone, phase, task from .continue-here
        res2 = cs.clear_workspace(
            workspace=self.workspace,
            next_todo="Implement API endpoints",
        )
        self.assertEqual(res2["status"], "ok")
        self.assertEqual(res2["milestone"], "M002")
        self.assertEqual(res2["phase"], "Phase 2")
        self.assertEqual(res2["task"], "Task 2.1")
        self.assertEqual(res2["next_todo"], "Implement API endpoints")

        # 3. CLI execution via bin/cs_engine.py
        import subprocess
        cs_engine_bin = Path(__file__).parent.parent / "bin" / "cs_engine.py"
        cmd = [
            "python3",
            str(cs_engine_bin),
            "--workspace",
            str(self.workspace),
            "clear",
            "--next",
            "CLI test verification",
            "--json",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        cli_out = json.loads(proc.stdout)
        self.assertEqual(cli_out["status"], "ok")
        self.assertEqual(cli_out["next_todo"], "CLI test verification")


if __name__ == "__main__":
    unittest.main()

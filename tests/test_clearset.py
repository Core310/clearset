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


if __name__ == "__main__":
    unittest.main()

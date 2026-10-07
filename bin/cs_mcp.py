#!/usr/bin/env python3
"""
ClearSet MCP Server (`cs-mcp`): Standard Model Context Protocol Server.
Exposes ClearSet SQLite retrieval, state logging, test gates, and context
management as native typed JSON-RPC tools for AI agents.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

from clearset.engine import (
    find_workspace,
    create_checkpoint,
    load_resume_state,
    log_turn_action,
    log_learning_or_concern,
)
from clearset.fetch import (
    fetch_symbol_data,
    fetch_outline_data,
    fetch_context_data,
    fetch_call_graph_data,
    fetch_turn_history_data,
    fetch_file_slice_data,
    fetch_swarm_packet_data,
)
from clearset.sync import sync_codebase_state
from clearset.gate import run_verification_gate

SERVER_NAME = "clearset-mcp"
SERVER_VERSION = "1.0.0"

TOOLS = [
    {
        "name": "cs_fetch_symbol",
        "description": "Retrieve exact symbol signature, line numbers, and docstring from SQLite AST index without reading full files.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Symbol name (function, class, method)"},
                "limit": {"type": "integer", "description": "Max results to return", "default": 5},
                "workspace": {"type": "string", "description": "Optional workspace path", "default": "."}
            },
            "required": ["name"]
        }
    },
    {
        "name": "cs_fetch_outline",
        "description": "Fetch compact symbol outline (functions, classes, line ranges) for any file without consuming token budget on full code.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "File path relative to workspace"},
                "workspace": {"type": "string", "description": "Optional workspace path", "default": "."}
            },
            "required": ["file"]
        }
    },
    {
        "name": "cs_fetch_slice",
        "description": "Read only an exact line range from a target file with line numbers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "File path"},
                "start": {"type": "integer", "description": "Start line (1-indexed)"},
                "end": {"type": "integer", "description": "End line (1-indexed)"},
                "workspace": {"type": "string", "description": "Optional workspace path", "default": "."}
            },
            "required": ["file", "start", "end"]
        }
    },
    {
        "name": "cs_fetch_context",
        "description": "Run compact full-text keyword search and domain tag lookup across codebase index.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keyword or domain tag"},
                "workspace": {"type": "string", "description": "Optional workspace path", "default": "."}
            },
            "required": ["query"]
        }
    },
    {
        "name": "cs_fetch_callers",
        "description": "Fetch call graph (inbound callers and outbound dependencies) for a function or class.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Function or class name"},
                "workspace": {"type": "string", "description": "Optional workspace path", "default": "."}
            },
            "required": ["name"]
        }
    },
    {
        "name": "cs_fetch_turns",
        "description": "Fetch recent turn actions, decisions, and open issues from SQLite turn ledger.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of actions to return", "default": 5},
                "workspace": {"type": "string", "description": "Optional workspace path", "default": "."}
            }
        }
    },
    {
        "name": "cs_sync_codebase",
        "description": "Deterministically scan git diff, re-index modified files into cs_codebase.db, and update YAML guides.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {"type": "string", "description": "Optional workspace path", "default": "."}
            }
        }
    },
    {
        "name": "cs_run_gate",
        "description": "Execute a deterministic test/linter command, verify exit code 0, and record structured audit to cs_turns.db.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Test command (e.g. 'pytest tests/' or 'ruff check .')"},
                "milestone": {"type": "string", "description": "Milestone identifier", "default": "M001"},
                "phase": {"type": "string", "description": "Phase identifier", "default": "01"},
                "task": {"type": "string", "description": "Task identifier", "default": "verification"},
                "files": {"type": "array", "items": {"type": "string"}, "description": "Files verified", "default": []},
                "workspace": {"type": "string", "description": "Optional workspace path", "default": "."}
            },
            "required": ["command"]
        }
    },
    {
        "name": "cs_checkpoint",
        "description": "Write a persistent checkpoint to RESUME HERE.md and cs_turns.db before clearing context window.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "milestone": {"type": "string", "description": "Active milestone", "default": "M001"},
                "phase": {"type": "string", "description": "Active phase", "default": "Phase 1"},
                "task": {"type": "string", "description": "Active task", "default": "Task 1"},
                "next": {"type": "string", "description": "Next concrete action to execute"},
                "workspace": {"type": "string", "description": "Optional workspace path", "default": "."}
            },
            "required": ["next"]
        }
    },
    {
        "name": "cs_resume",
        "description": "Restore active execution state, milestone, phase, task, and open concerns after /clear in 2ms without reading files.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {"type": "string", "description": "Optional workspace path", "default": "."}
            }
        }
    },
    {
        "name": "cs_log_turn",
        "description": "Record an action (EXECUTION, REFACTOR, FIX, VERIFICATION) directly to SQLite turn ledger.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Action summary"},
                "type": {"type": "string", "enum": ["EXECUTION", "REFACTOR", "INVESTIGATION", "FIX", "VERIFICATION"], "default": "EXECUTION"},
                "status": {"type": "string", "default": "SUCCESS"},
                "milestone": {"type": "string", "default": "M001"},
                "phase": {"type": "string", "default": "01"},
                "task": {"type": "string", "default": "task-01"},
                "files": {"type": "array", "items": {"type": "string"}, "default": []},
                "summary": {"type": "string", "default": ""},
                "workspace": {"type": "string", "description": "Optional workspace path", "default": "."}
            },
            "required": ["description"]
        }
    }
]


def handle_tool_call(tool_name: str, arguments: Dict[str, Any]) -> Any:
    ws_str = arguments.get("workspace", ".")
    workspace = find_workspace(Path(ws_str).resolve())

    if tool_name == "cs_fetch_symbol":
        return fetch_symbol_data(workspace, arguments["name"], arguments.get("limit", 5))

    elif tool_name == "cs_fetch_outline":
        return fetch_outline_data(workspace, arguments["file"])

    elif tool_name == "cs_fetch_slice":
        return fetch_file_slice_data(workspace, arguments["file"], arguments["start"], arguments["end"])

    elif tool_name == "cs_fetch_context":
        return fetch_context_data(workspace, arguments["query"])

    elif tool_name == "cs_fetch_callers":
        return fetch_call_graph_data(workspace, arguments["name"])

    elif tool_name == "cs_fetch_turns":
        return fetch_turn_history_data(workspace, arguments.get("limit", 5))

    elif tool_name == "cs_sync_codebase":
        return sync_codebase_state(workspace)

    elif tool_name == "cs_run_gate":
        return run_verification_gate(
            workspace=workspace,
            command_str=arguments["command"],
            milestone=arguments.get("milestone", "M001"),
            phase=arguments.get("phase", "01"),
            task=arguments.get("task", "verification"),
            files=arguments.get("files", []),
        )

    elif tool_name == "cs_checkpoint":
        path = create_checkpoint(
            workspace=workspace,
            milestone=arguments.get("milestone", "M001"),
            phase=arguments.get("phase", "Phase 1"),
            task=arguments.get("task", "Task 1"),
            next_todo=arguments["next"]
        )
        return {
            "status": "ok",
            "checkpoint_file": str(path),
            "milestone": arguments.get("milestone", "M001"),
            "next": arguments["next"]
        }

    elif tool_name == "cs_resume":
        return load_resume_state(workspace)

    elif tool_name == "cs_log_turn":
        aid = log_turn_action(
            workspace=workspace,
            session_id="mcp-session",
            milestone=arguments.get("milestone", "M001"),
            phase=arguments.get("phase", "01"),
            task=arguments.get("task", "task-01"),
            action_type=arguments.get("type", "EXECUTION"),
            description=arguments["description"],
            status=arguments.get("status", "SUCCESS"),
            files_touched=arguments.get("files", []),
            summary=arguments.get("summary", "")
        )
        return {"status": "ok", "action_id": aid}

    else:
        raise ValueError(f"Unknown tool: {tool_name}")


def run_stdio_server():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except Exception:
            continue

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "initialize":
            res = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    "capabilities": {"tools": {}}
                }
            }
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            res = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": TOOLS}
            }
        elif method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {})
            try:
                data = handle_tool_call(tool_name, args)
                res = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": json.dumps(data, indent=2)}
                        ],
                        "isError": False
                    }
                }
            except Exception as e:
                res = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error: {str(e)}"}],
                        "isError": True
                    }
                }
        else:
            res = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"}
            }

        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description="ClearSet Model Context Protocol (MCP) Server")
    parser.add_argument("--schema", action="store_true", help="Print tools JSON schema and exit")
    args = parser.parse_args()

    if args.schema:
        print(json.dumps(TOOLS, indent=2))
    else:
        run_stdio_server()


if __name__ == "__main__":
    main()

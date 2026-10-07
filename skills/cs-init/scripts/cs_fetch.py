#!/usr/bin/env python3
"""
ClearSet (cs-fetch): Token-Optimized Code & State Retrieval CLI for AI Agents.
Designed to extract minimal-token context packets directly from SQLite.
"""

import argparse
import json
import sqlite3
from pathlib import Path

CS_DIR_NAME = ".cs"
LEGACY_CTA_DIR_NAME = ".cta"
CODEBASE_DB_NAME = "cs_codebase.db"
TURNS_DB_NAME = "cs_turns.db"


def find_workspace(start_dir: Path) -> Path:
    cur = start_dir.resolve()
    for parent in [cur] + list(cur.parents):
        if (parent / CTA_DIR_NAME).exists():
            return parent
    return start_dir.resolve()


def get_codebase_db(workspace: Path) -> Path:
    return workspace / CTA_DIR_NAME / CODEBASE_DB_NAME


def get_turns_db(workspace: Path) -> Path:
    return workspace / CTA_DIR_NAME / TURNS_DB_NAME


def fetch_symbol(workspace: Path, symbol_name: str, max_results: int = 5) -> str:
    db_path = get_codebase_db(workspace)
    if not db_path.exists():
        return f"Error: {db_path} not found. Run 'cs init' first."

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
    SELECT file_path, name, kind, line_start, line_end, signature, docstring
    FROM symbols
    WHERE name LIKE ?
    LIMIT ?
    """,
        (f"%{symbol_name}%", max_results),
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return f"No symbols matching '{symbol_name}' found."

    out = [f"Found {len(rows)} symbol(s) for '{symbol_name}':"]
    for fp, name, kind, ls, le, sig, doc in rows:
        doc_snippet = f" - {doc.splitlines()[0]}" if doc else ""
        out.append(
            f"- [{name}] ({kind}) at {fp}:{ls}-{le}\n  Signature: `{sig}`{doc_snippet}"
        )
    return "\n".join(out)


def fetch_file_outline(workspace: Path, file_path: str) -> str:
    db_path = get_codebase_db(workspace)
    if not db_path.exists():
        return f"Error: {db_path} not found."

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
    SELECT name, kind, line_start, line_end, signature
    FROM symbols
    WHERE file_path LIKE ?
    ORDER BY line_start ASC
    """,
        (f"%{file_path}%",),
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return f"No symbols indexed for file '{file_path}'."

    out = [f"Symbol Outline for '{file_path}' ({len(rows)} symbols):"]
    for name, kind, ls, le, sig in rows:
        out.append(f"  L{ls:4d}-L{le:4d} | {kind:10s} | `{name}` -> `{sig}`")
    return "\n".join(out)


def fetch_context_packet(workspace: Path, query: str, token_budget: int = 400) -> str:
    db_path = get_codebase_db(workspace)
    if not db_path.exists():
        return f"Error: {db_path} not found."

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        """
    SELECT file_path, symbol_name, kind, signature, docstring
    FROM codebase_fts
    WHERE codebase_fts MATCH ?
    LIMIT 6
    """,
        (query,),
    )
    fts_rows = cur.fetchall()

    cur.execute(
        """
    SELECT target_id, target_type, category, notes
    FROM tags
    WHERE tag_name LIKE ? OR notes LIKE ?
    LIMIT 4
    """,
        (f"%{query}%", f"%{query}%"),
    )
    tag_rows = cur.fetchall()

    conn.close()

    out = [f"### ClearSet Context Packet: '{query}'"]

    if fts_rows:
        out.append("\n**Matched Symbols & Signatures:**")
        for fp, sname, kind, sig, doc in fts_rows:
            short_doc = f" ({doc.splitlines()[0]})" if doc else ""
            out.append(f"- `{fp}`: {kind} `{sname}` -> `{sig}`{short_doc}")

    if tag_rows:
        out.append("\n**Related Architecture & Modules:**")
        for tid, ttype, cat, notes in tag_rows:
            out.append(f"- [{cat}] {ttype} `{tid}` ({notes})")

    if not fts_rows and not tag_rows:
        out.append(
            f"No direct matches found for '{query}'. Try a broader query or tag search."
        )

    return "\n".join(out)


def fetch_call_graph(workspace: Path, symbol_name: str) -> str:
    db_path = get_codebase_db(workspace)
    if not db_path.exists():
        return f"Error: {db_path} not found."

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        """
    SELECT source_id, relation_type, details
    FROM relationships
    WHERE target_id LIKE ? AND relation_type = 'calls'
    LIMIT 10
    """,
        (f"%{symbol_name}%",),
    )
    callers = cur.fetchall()

    cur.execute(
        """
    SELECT target_id, relation_type, details
    FROM relationships
    WHERE source_id LIKE ?
    LIMIT 10
    """,
        (f"%{symbol_name}%",),
    )
    dependencies = cur.fetchall()

    conn.close()

    out = [f"Call Graph for '{symbol_name}':"]
    out.append("  Inbound Callers:")
    if callers:
        for src, rel, det in callers:
            out.append(f"    <- `{src}` ({det})")
    else:
        out.append("    (none indexed)")

    out.append("  Outbound Dependencies:")
    if dependencies:
        for tgt, rel, det in dependencies:
            out.append(f"    -> `{tgt}` [{rel}] ({det})")
    else:
        out.append("    (none indexed)")

    return "\n".join(out)


def fetch_turn_history(workspace: Path, limit: int = 5) -> str:
    db_path = get_turns_db(workspace)
    if not db_path.exists():
        return "No turns database found."

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        """
    SELECT timestamp, action_type, milestone, phase, task, description, status, files_touched
    FROM turn_actions
    ORDER BY id DESC
    LIMIT ?
    """,
        (limit,),
    )
    actions = cur.fetchall()

    cur.execute(
        """
    SELECT timestamp, kind, category, title, details
    FROM learnings_concerns
    WHERE is_resolved = 0
    ORDER BY id DESC
    LIMIT ?
    """,
        (limit,),
    )
    concerns = cur.fetchall()

    conn.close()

    out = [f"### Recent Turn Actions (Last {limit}):"]
    if actions:
        for ts, atype, m, p, t, desc, status, files in actions:
            if files:
                try:
                    files_list = json.loads(files)
                    if isinstance(files_list, str):
                        files_list = [files_list]
                except Exception:
                    files_list = [files]
            else:
                files_list = []
            f_str = f" [Files: {', '.join(files_list)}]" if files_list else ""
            out.append(f"- **{atype}** ({status}) [{m}/{p}/{t}]: {desc}{f_str}")
    else:
        out.append("- No actions recorded.")

    out.append(f"\n### Unresolved Concerns & Learnings:")
    if concerns:
        for ts, kind, cat, title, details in concerns:
            out.append(f"- **{kind.upper()}** [{cat}] {title}: {details}")
    else:
        out.append("- No unresolved concerns.")

    return "\n".join(out)


def fetch_file_slice(
    workspace: Path, file_path: str, start_line: int, end_line: int
) -> str:
    target = (workspace / file_path).resolve()
    if not target.exists():
        return f"Error: File {file_path} does not exist."

    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        selected = lines[max(0, start_line - 1) : end_line]
        out = [f"Lines {start_line}-{end_line} of {file_path}:"]
        for idx, line in enumerate(selected, start=start_line):
            out.append(f"{idx:4d}: {line.rstrip()}")
        return "\n".join(out)
    except Exception as e:
        return f"Error reading slice: {e}"


def fetch_swarm_packet(workspace: Path, task_id: str) -> str:
    turns_db = get_turns_db(workspace)
    codebase_db = get_codebase_db(workspace)

    if not turns_db.exists():
        return f"Error: Database {turns_db} does not exist."

    conn = sqlite3.connect(turns_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM swarm_tasks WHERE task_id = ?", (task_id,))
    task_row = cur.fetchone()
    if not task_row:
        conn.close()
        return f"Error: Task '{task_id}' not found in swarm_tasks."

    t_dict = dict(task_row)
    run_id = t_dict["run_id"]

    cur.execute(
        "SELECT milestone, phase, topology FROM swarm_runs WHERE run_id = ?", (run_id,)
    )
    run_row = cur.fetchone()
    milestone = run_row["milestone"] if run_row else "M001"
    phase = run_row["phase"] if run_row else "01"
    topology = run_row["topology"] if run_row else "scatter_gather"

    cur.execute(
        """
    SELECT from_task, message_type, payload, timestamp 
    FROM swarm_messages 
    WHERE run_id = ? AND (to_task = ? OR to_task = 'ALL') 
    ORDER BY id ASC
    """,
        (run_id, task_id),
    )
    messages = [dict(r) for r in cur.fetchall()]
    conn.close()

    target_files = json.loads(t_dict["target_files"] or "[]")
    target_symbols = json.loads(t_dict["target_symbols"] or "[]")

    symbol_snippets = []
    if codebase_db.exists() and target_symbols:
        c_conn = sqlite3.connect(codebase_db)
        c_cur = c_conn.cursor()
        for sym in target_symbols:
            c_cur.execute(
                """
            SELECT file_path, name, kind, line_start, line_end, signature, docstring
            FROM symbols WHERE name = ? OR name LIKE ?
            LIMIT 2
            """,
                (sym, f"%{sym}%"),
            )
            for fp, sname, skind, ls, le, sig, doc in c_cur.fetchall():
                d_first = f" - {doc.splitlines()[0]}" if doc else ""
                symbol_snippets.append(
                    f"- `{sname}` ({skind}) at {fp}:{ls}-{le}\n  Signature: `{sig}`{d_first}"
                )
        c_conn.close()

    out = [
        f"### ClearSet Swarm Task Packet: {t_dict['task_id']}",
        f"- **Run ID**: {run_id} | **Topology**: {topology}",
        f"- **Milestone**: {milestone} | **Phase**: {phase}",
        f"- **Title**: {t_dict['title']}",
        f"- **Role**: {t_dict['role']}",
        f"- **Status**: {t_dict['status']} (Attempt #{t_dict['attempt_count']}/{t_dict['max_retries']})",
        f"- **Target Files**: {', '.join(target_files) if target_files else 'None'}",
        f"- **Deterministic Gate**: `{t_dict['verification_cmd'] or 'pytest / compiler / linter'}`",
    ]

    if symbol_snippets:
        out.append("\n#### Ground-Truth Symbols (from cs_codebase.db):")
        out.extend(symbol_snippets)
    elif target_symbols:
        out.append(f"\n#### Target Symbols: {', '.join(target_symbols)}")

    if messages:
        out.append("\n#### Inter-Task Contracts & Messages:")
        for m in messages:
            out.append(
                f"- **[{m['message_type']}]** from {m['from_task']}: {m['payload']}"
            )

    if t_dict.get("traceback_log"):
        out.append(
            f"\n#### Previous Attempt Error Traceback (Fix this):\n```\n{t_dict['traceback_log']}\n```"
        )

    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(
        description="ClearSet Fetch: Token-Efficient SQLite Code & State Retrieval"
    )
    parser.add_argument("--workspace", "-w", default=".", help="Workspace root path")
    subparsers = parser.add_subparsers(dest="command", help="Fetch subcommands")

    p_sym = subparsers.add_parser(
        "symbol", help="Fetch exact symbol signature, line range, and docstring"
    )
    p_sym.add_argument("name", help="Symbol name (class, function, method)")
    p_sym.add_argument("--limit", "-n", type=int, default=5, help="Max results")

    p_out = subparsers.add_parser(
        "outline", help="Fetch symbol outline of a file without reading code"
    )
    p_out.add_argument("file", help="File path relative to workspace")

    p_ctx = subparsers.add_parser(
        "context", help="Fetch token-budgeted RAG context packet for a query"
    )
    p_ctx.add_argument("query", help="Query string or domain tag")

    p_call = subparsers.add_parser(
        "callers", help="Fetch call graph (inbound callers & dependencies)"
    )
    p_call.add_argument("name", help="Function or class name")

    p_turn = subparsers.add_parser(
        "turns", help="Fetch recent turn actions, decisions, and open issues"
    )
    p_turn.add_argument(
        "--limit", "-n", type=int, default=5, help="Number of actions to return"
    )

    p_sl = subparsers.add_parser("slice", help="Fetch specific line range from file")
    p_sl.add_argument("file", help="File path")
    p_sl.add_argument("start", type=int, help="Start line (1-indexed)")
    p_sl.add_argument("end", type=int, help="End line (1-indexed)")

    p_sw = subparsers.add_parser(
        "swarm-packet", help="Fetch minimal context packet for a claimed swarm task"
    )
    p_sw.add_argument("task_id", help="Task ID from swarm_tasks")

    args = parser.parse_args()
    workspace = find_workspace(Path(args.workspace))

    if args.command == "symbol":
        print(fetch_symbol(workspace, args.name, args.limit))
    elif args.command == "outline":
        print(fetch_file_outline(workspace, args.file))
    elif args.command == "context":
        print(fetch_context_packet(workspace, args.query))
    elif args.command == "callers":
        print(fetch_call_graph(workspace, args.name))
    elif args.command == "turns":
        print(fetch_turn_history(workspace, args.limit))
    elif args.command == "slice":
        print(fetch_file_slice(workspace, args.file, args.start, args.end))
    elif args.command == "swarm-packet":
        print(fetch_swarm_packet(workspace, args.task_id))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

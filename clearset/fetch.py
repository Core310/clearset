#!/usr/bin/env bash
# ClearSet (cs-fetch): Token-Optimized Code & State Retrieval
# Machine-Readable & Structured SQLite RAG for AI Agents

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

CS_DIR_NAME = ".cs"
LEGACY_CTA_DIR_NAME = ".cta"
CODEBASE_DB_NAME = "cs_codebase.db"
TURNS_DB_NAME = "cs_turns.db"


def get_cs_dir(workspace: Path) -> Path:
    if (workspace / LEGACY_CTA_DIR_NAME).exists() and not (workspace / CS_DIR_NAME).exists():
        return workspace / LEGACY_CTA_DIR_NAME
    return workspace / CS_DIR_NAME


def find_workspace(start_dir: Path) -> Path:
    current = start_dir.resolve()
    for parent in [current] + list(current.parents):
        if (parent / CS_DIR_NAME).exists() or (parent / LEGACY_CTA_DIR_NAME).exists():
            return parent
    return current


def get_codebase_db(workspace: Path) -> Path:
    cs_dir = get_cs_dir(workspace)
    if (cs_dir / "cta_codebase.db").exists() and not (cs_dir / CODEBASE_DB_NAME).exists():
        return cs_dir / "cta_codebase.db"
    return cs_dir / CODEBASE_DB_NAME


def get_turns_db(workspace: Path) -> Path:
    cs_dir = get_cs_dir(workspace)
    if (cs_dir / "cta_turns.db").exists() and not (cs_dir / TURNS_DB_NAME).exists():
        return cs_dir / "cta_turns.db"
    return cs_dir / TURNS_DB_NAME


# -----------------------------------------------------------------------------
# Structured Data Extractors (Machine-Readable Dictionaries)
# -----------------------------------------------------------------------------

def fetch_symbol_data(workspace: Path, symbol_name: str, max_results: int = 5) -> Dict[str, Any]:
    db_path = get_codebase_db(workspace)
    if not db_path.exists():
        return {"error": f"{db_path} not found. Run 'cs init' first.", "symbols": []}

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
    SELECT file_path, name, kind, line_start, line_end, signature, docstring
    FROM symbols
    WHERE name = ?
    LIMIT ?
    """,
        (symbol_name, max_results),
    )
    rows = cur.fetchall()

    if not rows:
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

    results = []
    for fp, sname, kind, start, end, sig, doc in rows:
        results.append({
            "name": sname,
            "kind": kind,
            "file": fp,
            "line_start": start,
            "line_end": end,
            "signature": sig,
            "docstring": doc or ""
        })

    return {
        "query": symbol_name,
        "count": len(results),
        "symbols": results
    }


def fetch_outline_data(workspace: Path, file_path: str) -> Dict[str, Any]:
    db_path = get_codebase_db(workspace)
    if not db_path.exists():
        return {"error": f"{db_path} not found.", "file": file_path, "symbols": []}

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
    SELECT name, kind, line_start, line_end, signature
    FROM symbols
    WHERE file_path = ? OR file_path LIKE ?
    ORDER BY line_start ASC
    """,
        (file_path, f"%{file_path}"),
    )
    rows = cur.fetchall()
    conn.close()

    symbols = []
    for sname, kind, start, end, sig in rows:
        symbols.append({
            "name": sname,
            "kind": kind,
            "line_start": start,
            "line_end": end,
            "signature": sig
        })

    return {
        "file": file_path,
        "count": len(symbols),
        "symbols": symbols
    }


def fetch_context_data(workspace: Path, query: str) -> Dict[str, Any]:
    db_path = get_codebase_db(workspace)
    if not db_path.exists():
        return {"error": f"{db_path} not found.", "query": query, "symbols": [], "tags": []}

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    safe_q = "".join(c for c in query if c.isalnum() or c.isspace()).strip()
    fts_rows = []
    if safe_q:
        try:
            cur.execute(
                """
            SELECT file_path, symbol_name, kind, signature, docstring
            FROM codebase_fts
            WHERE codebase_fts MATCH ?
            LIMIT 5
            """,
                (f"{safe_q}*",),
            )
            fts_rows = cur.fetchall()
        except sqlite3.OperationalError:
            cur.execute(
                """
            SELECT file_path, name, kind, signature, docstring
            FROM symbols
            WHERE name LIKE ? OR docstring LIKE ?
            LIMIT 5
            """,
                (f"%{safe_q}%", f"%{safe_q}%"),
            )
            fts_rows = cur.fetchall()

    cur.execute(
        """
    SELECT target_id, target_type, category, notes
    FROM tags
    WHERE tag_name LIKE ? OR target_id LIKE ? OR notes LIKE ?
    LIMIT 5
    """,
        (f"%{query}%", f"%{query}%", f"%{query}%"),
    )
    tag_rows = cur.fetchall()
    conn.close()

    symbols = []
    for fp, sname, kind, sig, doc in fts_rows:
        symbols.append({
            "name": sname,
            "kind": kind,
            "file": fp,
            "signature": sig,
            "docstring": doc or ""
        })

    tags = []
    for tid, ttype, cat, notes in tag_rows:
        tags.append({
            "target": tid,
            "type": ttype,
            "category": cat,
            "notes": notes
        })

    return {
        "query": query,
        "symbols": symbols,
        "tags": tags
    }


def fetch_call_graph_data(workspace: Path, symbol_name: str) -> Dict[str, Any]:
    db_path = get_codebase_db(workspace)
    if not db_path.exists():
        return {"error": f"{db_path} not found.", "symbol": symbol_name}

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
    callers = [{"source": src, "relation": rel, "details": det} for src, rel, det in cur.fetchall()]

    cur.execute(
        """
    SELECT target_id, relation_type, details
    FROM relationships
    WHERE source_id LIKE ?
    LIMIT 10
    """,
        (f"%{symbol_name}%",),
    )
    dependencies = [{"target": tgt, "relation": rel, "details": det} for tgt, rel, det in cur.fetchall()]
    conn.close()

    return {
        "symbol": symbol_name,
        "callers": callers,
        "dependencies": dependencies
    }


def fetch_turn_history_data(workspace: Path, limit: int = 5) -> Dict[str, Any]:
    db_path = get_turns_db(workspace)
    if not db_path.exists():
        return {"error": "No turns database found.", "actions": [], "concerns": []}

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
    action_rows = cur.fetchall()

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
    concern_rows = cur.fetchall()
    conn.close()

    actions = []
    for ts, atype, m, p, t, desc, status, files in action_rows:
        files_list = []
        if files:
            try:
                parsed = json.loads(files)
                files_list = [parsed] if isinstance(parsed, str) else parsed
            except Exception:
                files_list = [files]
        actions.append({
            "timestamp": ts,
            "type": atype,
            "milestone": m,
            "phase": p,
            "task": t,
            "description": desc,
            "status": status,
            "files": files_list
        })

    concerns = []
    for ts, kind, cat, title, details in concern_rows:
        concerns.append({
            "timestamp": ts,
            "kind": kind,
            "category": cat,
            "title": title,
            "details": details
        })

    return {
        "count_actions": len(actions),
        "count_concerns": len(concerns),
        "actions": actions,
        "concerns": concerns
    }


def fetch_file_slice_data(workspace: Path, file_path: str, start_line: int, end_line: int) -> Dict[str, Any]:
    target = (workspace / file_path).resolve()
    if not target.exists():
        return {"error": f"File {file_path} does not exist.", "file": file_path, "lines": []}

    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        selected = all_lines[max(0, start_line - 1):end_line]
        numbered_lines = [
            {"line_number": idx, "content": line.rstrip("\r\n")}
            for idx, line in enumerate(selected, start=start_line)
        ]
        return {
            "file": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "total_lines": len(numbered_lines),
            "lines": numbered_lines,
            "text": "\n".join(f"{item['line_number']:4d}: {item['content']}" for item in numbered_lines)
        }
    except Exception as e:
        return {"error": f"Error reading slice: {e}", "file": file_path, "lines": []}


def fetch_swarm_packet_data(workspace: Path, task_id: str) -> Dict[str, Any]:
    db_path = get_turns_db(workspace)
    if not db_path.exists():
        return {"error": "Turns database not found.", "task_id": task_id}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM swarm_tasks WHERE task_id = ?", (task_id,))
    t_row = cur.fetchone()
    if not t_row:
        conn.close()
        return {"error": f"Task '{task_id}' not found.", "task_id": task_id}

    t_dict = dict(t_row)
    cur.execute(
        "SELECT * FROM swarm_messages WHERE run_id = ? AND (to_task = ? OR to_task = 'ALL') ORDER BY id ASC",
        (t_dict["run_id"], task_id),
    )
    messages = [dict(r) for r in cur.fetchall()]
    conn.close()

    target_files = json.loads(t_dict["target_files"] or "[]")
    target_symbols = json.loads(t_dict["target_symbols"] or "[]")

    symbol_snippets = []
    code_db = get_codebase_db(workspace)
    if code_db.exists() and target_symbols:
        c_conn = sqlite3.connect(code_db)
        c_cur = c_conn.cursor()
        for sym in target_symbols:
            c_cur.execute(
                "SELECT file_path, name, kind, line_start, line_end, signature FROM symbols WHERE name = ?",
                (sym,),
            )
            for fp, sname, kind, start, end, sig in c_cur.fetchall():
                symbol_snippets.append({
                    "name": sname,
                    "kind": kind,
                    "file": fp,
                    "line_start": start,
                    "line_end": end,
                    "signature": sig
                })
        c_conn.close()

    return {
        "task_id": task_id,
        "run_id": t_dict["run_id"],
        "title": t_dict["title"],
        "role": t_dict["role"],
        "status": t_dict["status"],
        "target_files": target_files,
        "target_symbols": target_symbols,
        "verification_cmd": t_dict["verification_cmd"],
        "messages": messages,
        "symbol_snippets": symbol_snippets
    }


# -----------------------------------------------------------------------------
# Text Formatters for Human CLI Output
# -----------------------------------------------------------------------------

def format_symbol_text(data: Dict[str, Any]) -> str:
    if "error" in data:
        return data["error"]
    if not data["symbols"]:
        return f"No symbols found matching '{data['query']}'."
    out = [f"Found {len(data['symbols'])} match(es) for '{data['query']}':"]
    for s in data["symbols"]:
        doc = f"\n    Docstring: {s['docstring']}" if s["docstring"] else ""
        out.append(f"- [{s['kind']}] {s['name']} (Lines {s['line_start']}-{s['line_end']} in {s['file']})\n    Signature: {s['signature']}{doc}")
    return "\n".join(out)


def format_outline_text(data: Dict[str, Any]) -> str:
    if "error" in data:
        return data["error"]
    if not data["symbols"]:
        return f"No indexed symbols found for '{data['file']}'."
    out = [f"Outline for {data['file']} ({data['count']} symbols):"]
    for s in data["symbols"]:
        out.append(f"  - [{s['kind']:8s}] L{s['line_start']:4d}-L{s['line_end']:4d}: {s['signature']}")
    return "\n".join(out)


def format_context_text(data: Dict[str, Any]) -> str:
    if "error" in data:
        return data["error"]
    out = [f"### ClearSet Context Packet: '{data['query']}'"]
    if data["symbols"]:
        out.append("\n**Matched Symbols & Signatures:**")
        for s in data["symbols"]:
            doc = f" ({s['docstring'].splitlines()[0]})" if s['docstring'] else ""
            out.append(f"- `{s['file']}`: {s['kind']} `{s['name']}` -> `{s['signature']}`{doc}")
    if data["tags"]:
        out.append("\n**Related Architecture & Modules:**")
        for t in data["tags"]:
            out.append(f"- [{t['category']}] {t['type']} `{t['target']}` ({t['notes']})")
    if not data["symbols"] and not data["tags"]:
        out.append(f"No direct matches found for '{data['query']}'. Try a broader query or tag search.")
    return "\n".join(out)


def format_callers_text(data: Dict[str, Any]) -> str:
    if "error" in data:
        return data["error"]
    out = [f"Call Graph for '{data['symbol']}':", "  Inbound Callers:"]
    if data["callers"]:
        for c in data["callers"]:
            out.append(f"    <- `{c['source']}` ({c['details']})")
    else:
        out.append("    (none indexed)")
    out.append("  Outbound Dependencies:")
    if data["dependencies"]:
        for d in data["dependencies"]:
            out.append(f"    -> `{d['target']}` [{d['relation']}] ({d['details']})")
    else:
        out.append("    (none indexed)")
    return "\n".join(out)


def format_turns_text(data: Dict[str, Any]) -> str:
    if "error" in data:
        return data["error"]
    out = [f"### Recent Turn Actions (Last {len(data['actions'])}):"]
    if data["actions"]:
        for a in data["actions"]:
            f_str = f" [Files: {', '.join(a['files'])}]" if a["files"] else ""
            out.append(f"- **{a['type']}** ({a['status']}) [{a['milestone']}/{a['phase']}/{a['task']}]: {a['description']}{f_str}")
    else:
        out.append("- No actions recorded.")
    out.append("\n### Unresolved Concerns & Learnings:")
    if data["concerns"]:
        for c in data["concerns"]:
            out.append(f"- **{c['kind'].upper()}** [{c['category']}] {c['title']}: {c['details']}")
    else:
        out.append("- No unresolved concerns.")
    return "\n".join(out)


def format_slice_text(data: Dict[str, Any]) -> str:
    if "error" in data:
        return data["error"]
    out = [f"Lines {data['start_line']}-{data['end_line']} of {data['file']}:"]
    out.append(data.get("text", ""))
    return "\n".join(out)


def format_swarm_packet_text(data: Dict[str, Any]) -> str:
    if "error" in data:
        return data["error"]
    out = [
        f"### ClearSet Swarm Task Packet: {data['task_id']}",
        f"- **Title**: {data['title']} (Role: {data['role']})",
        f"- **Verification Gate**: `{data['verification_cmd'] or 'None specified'}`",
        f"- **Target Files**: {', '.join(data['target_files']) if data['target_files'] else 'None'}"
    ]
    if data["messages"]:
        out.append("\n#### Blackboard Messages & Contracts:")
        for m in data["messages"]:
            out.append(f"- [{m['message_type']}] from {m['from_task']}: {m['payload']}")
    if data["symbol_snippets"]:
        out.append("\n#### Ground-Truth Symbols (from cs_codebase.db):")
        for s in data["symbol_snippets"]:
            out.append(f"- `{s['file']}` (L{s['line_start']}): {s['kind']} `{s['name']}` -> `{s['signature']}`")
    return "\n".join(out)


# -----------------------------------------------------------------------------
# CLI Entrypoint
# -----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="ClearSet Fetch: Token-Efficient SQLite Code & State Retrieval"
    )
    parser.add_argument("--workspace", "-w", default=".", help="Workspace root path")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    subparsers = parser.add_subparsers(dest="command", help="Fetch subcommands")

    p_sym = subparsers.add_parser("symbol", help="Fetch exact symbol signature, line range, and docstring")
    p_sym.add_argument("name", help="Symbol name (class, function, method)")
    p_sym.add_argument("--limit", "-n", type=int, default=5, help="Max results")
    p_sym.add_argument("--json", action="store_true", help="Output as JSON")

    p_out = subparsers.add_parser("outline", help="Fetch symbol outline of a file without reading code")
    p_out.add_argument("file", help="File path relative to workspace")
    p_out.add_argument("--json", action="store_true", help="Output as JSON")

    p_ctx = subparsers.add_parser("context", help="Fetch token-budgeted RAG context packet for a query")
    p_ctx.add_argument("query", help="Query string or domain tag")
    p_ctx.add_argument("--json", action="store_true", help="Output as JSON")

    p_call = subparsers.add_parser("callers", help="Fetch call graph (inbound callers & dependencies)")
    p_call.add_argument("name", help="Function or class name")
    p_call.add_argument("--json", action="store_true", help="Output as JSON")

    p_turn = subparsers.add_parser("turns", help="Fetch recent turn actions, decisions, and open issues")
    p_turn.add_argument("--limit", "-n", type=int, default=5, help="Number of actions to return")
    p_turn.add_argument("--json", action="store_true", help="Output as JSON")

    p_sl = subparsers.add_parser("slice", help="Fetch specific line range from file")
    p_sl.add_argument("file", help="File path")
    p_sl.add_argument("start", type=int, help="Start line (1-indexed)")
    p_sl.add_argument("end", type=int, help="End line (1-indexed)")
    p_sl.add_argument("--json", action="store_true", help="Output as JSON")

    p_sw = subparsers.add_parser("swarm-packet", help="Fetch minimal context packet for a claimed swarm task")
    p_sw.add_argument("task_id", help="Task ID from swarm_tasks")
    p_sw.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()
    workspace = find_workspace(Path(args.workspace))
    output_json = getattr(args, "json", False) or parser.parse_known_args()[0].json

    if args.command == "symbol":
        data = fetch_symbol_data(workspace, args.name, args.limit)
        print(json.dumps(data, indent=2) if output_json else format_symbol_text(data))
    elif args.command == "outline":
        data = fetch_outline_data(workspace, args.file)
        print(json.dumps(data, indent=2) if output_json else format_outline_text(data))
    elif args.command == "context":
        data = fetch_context_data(workspace, args.query)
        print(json.dumps(data, indent=2) if output_json else format_context_text(data))
    elif args.command == "callers":
        data = fetch_call_graph_data(workspace, args.name)
        print(json.dumps(data, indent=2) if output_json else format_callers_text(data))
    elif args.command == "turns":
        data = fetch_turn_history_data(workspace, args.limit)
        print(json.dumps(data, indent=2) if output_json else format_turns_text(data))
    elif args.command == "slice":
        data = fetch_file_slice_data(workspace, args.file, args.start, args.end)
        print(json.dumps(data, indent=2) if output_json else format_slice_text(data))
    elif args.command == "swarm-packet":
        data = fetch_swarm_packet_data(workspace, args.task_id)
        print(json.dumps(data, indent=2) if output_json else format_swarm_packet_text(data))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

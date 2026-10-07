#!/usr/bin/env python3
"""
ClearSet (cs) Engine: Deterministic Context Resets & SQLite State Management
Hybrid Spec-Driven RAG and Context Lifecycle CLI for AGY.
"""

import argparse
import ast
import datetime
import hashlib
import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

CS_DIR_NAME = ".cs"
LEGACY_CS_DIR_NAME = ".cta"
TURNS_DB_NAME = "cs_turns.db"
CODEBASE_DB_NAME = "cs_codebase.db"
CODEBASE_INDEX_YML = "cs_codebase_index.yml"
DIR_STRUCTURE_YML = "cs_directory_structure.yml"
RESUME_FILE = "RESUME HERE.md"

IGNORED_DIRS = {
    ".git",
    ".cs",
    ".cta",
    ".planning",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
    ".idea",
    ".vscode",
    ".cargo",
    "target",
    "bin",
    "obj",
    ".gemini",
    "logs",
    "archive",
    "openStreetUSD",
    "media",
    "photos",
    "lost+found",
    "docker",
    "cache",
    "data",
    "webUI",
    "Definitions",
    "BT_backup",
    "kcef",
    "assets",
}

IGNORED_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".svg",
    ".webp",
    ".mp4",
    ".mov",
    ".avi",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".exe",
    ".bin",
    ".iso",
    ".lock",
    ".pyc",
    ".pyd",
    ".so",
    ".dylib",
    ".usd",
    ".usda",
    ".usdc",
    ".pt",
    ".npy",
    ".npz",
    ".db",
    ".db-wal",
    ".db-shm",
    ".fastresume",
}

# -----------------------------------------------------------------------------
# Database Setup & Migrations
# -----------------------------------------------------------------------------


def find_workspace(start_dir: Path) -> Path:
    current = start_dir.resolve()
    for parent in [current] + list(current.parents):
        if (parent / CS_DIR_NAME).exists() or (parent / LEGACY_CS_DIR_NAME).exists():
            return parent
    return current


def get_cs_dir(workspace: Path) -> Path:
    if (workspace / LEGACY_CS_DIR_NAME).exists() and not (workspace / CS_DIR_NAME).exists():
        return workspace / LEGACY_CS_DIR_NAME
    return workspace / CS_DIR_NAME


def get_turns_db_path(workspace: Path) -> Path:
    cs_dir = get_cs_dir(workspace)
    if (cs_dir / "cta_turns.db").exists() and not (cs_dir / TURNS_DB_NAME).exists():
        return cs_dir / "cta_turns.db"
    return cs_dir / TURNS_DB_NAME


def get_codebase_db_path(workspace: Path) -> Path:
    cs_dir = get_cs_dir(workspace)
    if (cs_dir / "cta_codebase.db").exists() and not (cs_dir / CODEBASE_DB_NAME).exists():
        return cs_dir / "cta_codebase.db"
    return cs_dir / CODEBASE_DB_NAME


def init_turns_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY,
        started_at TEXT,
        ended_at TEXT,
        goal TEXT,
        status TEXT,
        summary TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS turn_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        timestamp TEXT,
        milestone TEXT,
        phase TEXT,
        task TEXT,
        action_type TEXT,
        description TEXT,
        status TEXT,
        files_touched TEXT,
        output_summary TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS learnings_concerns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        timestamp TEXT,
        kind TEXT,
        category TEXT,
        title TEXT,
        details TEXT,
        related_files TEXT,
        is_resolved INTEGER DEFAULT 0,
        resolution TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS checkpoints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        milestone TEXT,
        phase TEXT,
        task TEXT,
        next_todo TEXT,
        resume_file_path TEXT,
        git_commit_hash TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS swarm_runs (
        run_id TEXT PRIMARY KEY,
        session_id TEXT,
        milestone TEXT,
        phase TEXT,
        topology TEXT,
        status TEXT,
        total_tasks INTEGER DEFAULT 0,
        completed_tasks INTEGER DEFAULT 0,
        started_at TEXT,
        completed_at TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS swarm_tasks (
        task_id TEXT PRIMARY KEY,
        run_id TEXT,
        title TEXT,
        role TEXT,
        status TEXT,
        target_files TEXT,
        target_symbols TEXT,
        verification_cmd TEXT,
        claimed_by TEXT,
        claimed_at TEXT,
        attempt_count INTEGER DEFAULT 0,
        max_retries INTEGER DEFAULT 2,
        exit_code INTEGER,
        traceback_log TEXT,
        summary TEXT,
        completed_at TEXT,
        FOREIGN KEY(run_id) REFERENCES swarm_runs(run_id) ON DELETE CASCADE
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS swarm_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT,
        from_task TEXT,
        to_task TEXT,
        message_type TEXT,
        payload TEXT,
        timestamp TEXT,
        FOREIGN KEY(run_id) REFERENCES swarm_runs(run_id) ON DELETE CASCADE
    );
    """)

    conn.commit()
    conn.close()


def init_codebase_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS files (
        file_path TEXT PRIMARY KEY,
        extension TEXT,
        size_bytes INTEGER,
        line_count INTEGER,
        git_blob_hash TEXT,
        last_scanned_commit TEXT,
        last_modified TEXT,
        module TEXT,
        docstring TEXT,
        language TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS symbols (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT,
        name TEXT,
        kind TEXT,
        line_start INTEGER,
        line_end INTEGER,
        signature TEXT,
        docstring TEXT,
        parent_symbol TEXT,
        visibility TEXT,
        FOREIGN KEY(file_path) REFERENCES files(file_path) ON DELETE CASCADE
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS relationships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id TEXT,
        source_type TEXT,
        relation_type TEXT,
        target_id TEXT,
        target_type TEXT,
        details TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tag_name TEXT,
        target_type TEXT,
        target_id TEXT,
        category TEXT,
        notes TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS git_tracker (
        file_path TEXT PRIMARY KEY,
        last_blob_hash TEXT,
        last_scanned_commit TEXT,
        status TEXT
    );
    """)

    cur.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS codebase_fts USING fts5(
        file_path,
        symbol_name,
        kind,
        signature,
        docstring,
        tags,
        module
    );
    """)

    conn.commit()
    conn.close()


# -----------------------------------------------------------------------------
# Git and Hash Utilities
# -----------------------------------------------------------------------------


def run_cmd(cmd: List[str], cwd: Path) -> Tuple[int, str, str]:
    try:
        res = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True, check=False
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def get_git_commit(workspace: Path) -> str:
    code, out, _ = run_cmd(["git", "rev-parse", "HEAD"], workspace)
    return out if code == 0 else "non-git-workspace"


def get_git_blob_hash(filepath: Path, workspace: Path) -> str:
    if (workspace / ".git").exists():
        rel_path = filepath.relative_to(workspace)
        code, out, _ = run_cmd(["git", "hash-object", str(rel_path)], workspace)
        if code == 0 and out:
            return out
    try:
        hasher = hashlib.sha1()
        with open(filepath, "rb") as f:
            hasher.update(f.read())
        return hasher.hexdigest()
    except Exception:
        return ""


def get_modified_files_since_commit(
    workspace: Path, last_commit: str
) -> Optional[Set[str]]:
    if not last_commit or last_commit == "non-git-workspace":
        return None
    code, out, _ = run_cmd(["git", "diff", "--name-status", last_commit], workspace)
    if code != 0:
        return None

    modified = set()
    for line in out.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            modified.add(parts[1].strip())

    code_status, out_status, _ = run_cmd(["git", "status", "--porcelain"], workspace)
    if code_status == 0:
        for line in out_status.splitlines():
            line_str = line.strip()
            if len(line_str) > 3:
                modified.add(line_str[3:].strip())

    return modified


# -----------------------------------------------------------------------------
# AST and Code Parsers
# -----------------------------------------------------------------------------


def detect_language(ext: str) -> str:
    mapping = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".rs": "rust",
        ".go": "go",
        ".sh": "shell",
        ".bash": "shell",
        ".zsh": "shell",
        ".yml": "yaml",
        ".yaml": "yaml",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c",
        ".hpp": "cpp",
        ".sql": "sql",
        ".md": "markdown",
        ".json": "json",
    }
    return mapping.get(ext.lower(), "text")


def parse_python_file(
    filepath: Path, content: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
    symbols = []
    relationships = []
    docstring = ""

    try:
        tree = ast.parse(content, filename=str(filepath))
        docstring = ast.get_docstring(tree) or ""

        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        relationships.append(
                            {
                                "source_type": "file",
                                "relation_type": "imports",
                                "target_type": "module",
                                "target_id": alias.name,
                                "details": f"line {node.lineno}",
                            }
                        )
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    for alias in node.names:
                        relationships.append(
                            {
                                "source_type": "file",
                                "relation_type": "imports",
                                "target_type": "symbol",
                                "target_id": f"{mod}.{alias.name}"
                                if mod
                                else alias.name,
                                "details": f"line {node.lineno}",
                            }
                        )

            elif isinstance(node, ast.ClassDef):
                c_doc = ast.get_docstring(node) or ""
                bases = (
                    [ast.unparse(b) for b in node.bases]
                    if hasattr(ast, "unparse")
                    else []
                )
                symbols.append(
                    {
                        "name": node.name,
                        "kind": "class",
                        "line_start": node.lineno,
                        "line_end": getattr(node, "end_lineno", node.lineno),
                        "signature": f"class {node.name}({', '.join(bases)})",
                        "docstring": c_doc,
                        "parent_symbol": "",
                        "visibility": "private"
                        if node.name.startswith("_")
                        else "public",
                    }
                )
                for base in bases:
                    relationships.append(
                        {
                            "source_type": "symbol",
                            "source_id": node.name,
                            "relation_type": "extends",
                            "target_type": "symbol",
                            "target_id": base,
                            "details": f"line {node.lineno}",
                        }
                    )

                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        m_doc = ast.get_docstring(item) or ""
                        args_list = [a.arg for a in item.args.args]
                        symbols.append(
                            {
                                "name": f"{node.name}.{item.name}",
                                "kind": "method",
                                "line_start": item.lineno,
                                "line_end": getattr(item, "end_lineno", item.lineno),
                                "signature": f"def {item.name}({', '.join(args_list)})",
                                "docstring": m_doc,
                                "parent_symbol": node.name,
                                "visibility": "private"
                                if item.name.startswith("_")
                                else "public",
                            }
                        )

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                f_doc = ast.get_docstring(node) or ""
                args_list = [a.arg for a in node.args.args]
                symbols.append(
                    {
                        "name": node.name,
                        "kind": "function",
                        "line_start": node.lineno,
                        "line_end": getattr(node, "end_lineno", node.lineno),
                        "signature": f"def {node.name}({', '.join(args_list)})",
                        "docstring": f_doc,
                        "parent_symbol": "",
                        "visibility": "private"
                        if node.name.startswith("_")
                        else "public",
                    }
                )

    except Exception:
        pass

    return symbols, relationships, docstring


def parse_generic_file(
    filepath: Path, content: str, lang: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
    symbols = []
    relationships = []
    lines = content.splitlines()

    if lang in ("typescript", "javascript"):
        for i, line in enumerate(lines, 1):
            m = re.search(
                r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_$]+)\s*\(([^)]*)\)",
                line,
            )
            if m:
                symbols.append(
                    {
                        "name": m.group(1),
                        "kind": "function",
                        "line_start": i,
                        "line_end": i,
                        "signature": f"function {m.group(1)}({m.group(2)})",
                        "docstring": "",
                        "parent_symbol": "",
                        "visibility": "public" if "export" in line else "private",
                    }
                )
            m_class = re.search(
                r"^\s*(?:export\s+)?(?:class|interface|type)\s+([A-Za-z0-9_$]+)", line
            )
            if m_class:
                symbols.append(
                    {
                        "name": m_class.group(1),
                        "kind": "class",
                        "line_start": i,
                        "line_end": i,
                        "signature": line.strip(),
                        "docstring": "",
                        "parent_symbol": "",
                        "visibility": "public" if "export" in line else "private",
                    }
                )
            m_imp = re.search(r'import\s+.*?from\s+[\'"]([^\'"]+)[\'"]', line)
            if m_imp:
                relationships.append(
                    {
                        "source_type": "file",
                        "relation_type": "imports",
                        "target_type": "module",
                        "target_id": m_imp.group(1),
                        "details": f"line {i}",
                    }
                )

    elif lang == "rust":
        for i, line in enumerate(lines, 1):
            m = re.search(
                r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)", line
            )
            if m:
                symbols.append(
                    {
                        "name": m.group(1),
                        "kind": "function",
                        "line_start": i,
                        "line_end": i,
                        "signature": f"fn {m.group(1)}({m.group(2)})",
                        "docstring": "",
                        "parent_symbol": "",
                        "visibility": "public" if "pub " in line else "private",
                    }
                )
            m_struct = re.search(
                r"^\s*(?:pub\s+)?(?:struct|enum|trait)\s+([A-Za-z0-9_]+)", line
            )
            if m_struct:
                symbols.append(
                    {
                        "name": m_struct.group(1),
                        "kind": "struct",
                        "line_start": i,
                        "line_end": i,
                        "signature": line.strip(),
                        "docstring": "",
                        "parent_symbol": "",
                        "visibility": "public" if "pub " in line else "private",
                    }
                )

    elif lang == "go":
        for i, line in enumerate(lines, 1):
            m = re.search(
                r"^\s*func\s+(?:\([^)]+\)\s+)?([A-Za-z0-9_]+)\s*\(([^)]*)\)", line
            )
            if m:
                name = m.group(1)
                symbols.append(
                    {
                        "name": name,
                        "kind": "function",
                        "line_start": i,
                        "line_end": i,
                        "signature": line.strip(),
                        "docstring": "",
                        "parent_symbol": "",
                        "visibility": "public" if name[0].isupper() else "private",
                    }
                )

    elif lang == "shell":
        for i, line in enumerate(lines, 1):
            m = re.search(r"^\s*(?:function\s+)?([A-Za-z0-9_-]+)\s*\(\)\s*\{?", line)
            if m:
                symbols.append(
                    {
                        "name": m.group(1),
                        "kind": "function",
                        "line_start": i,
                        "line_end": i,
                        "signature": f"{m.group(1)}()",
                        "docstring": "",
                        "parent_symbol": "",
                        "visibility": "public",
                    }
                )

    elif lang == "yaml":
        for i, line in enumerate(lines, 1):
            m = re.search(r"^\s*-\s*name:\s*(.+)$", line)
            if m:
                symbols.append(
                    {
                        "name": m.group(1).strip(),
                        "kind": "task",
                        "line_start": i,
                        "line_end": i,
                        "signature": f"task: {m.group(1).strip()}",
                        "docstring": "",
                        "parent_symbol": "",
                        "visibility": "public",
                    }
                )

    return symbols, relationships, ""


def infer_tags(
    filepath: str, symbols: List[Dict[str, Any]], lang: str
) -> List[Dict[str, str]]:
    tags = []
    p = filepath.lower()

    if "test" in p or "spec" in p:
        tags.append(
            {"tag_name": "testing", "category": "layer", "notes": "Test suite file"}
        )
    if "api" in p or "route" in p or "controller" in p or "endpoint" in p:
        tags.append(
            {"tag_name": "api", "category": "layer", "notes": "API and routing"}
        )
    if "auth" in p or "token" in p or "jwt" in p or "password" in p:
        tags.append(
            {
                "tag_name": "auth",
                "category": "domain",
                "notes": "Authentication & authorization",
            }
        )
    if (
        "db" in p
        or "database" in p
        or "model" in p
        or "schema" in p
        or "migration" in p
    ):
        tags.append(
            {
                "tag_name": "database",
                "category": "layer",
                "notes": "Database models and persistence",
            }
        )
    if "service" in p or "business" in p:
        tags.append(
            {
                "tag_name": "service",
                "category": "layer",
                "notes": "Business logic service",
            }
        )
    if "config" in p or "settings" in p or "env" in p:
        tags.append(
            {
                "tag_name": "config",
                "category": "config",
                "notes": "Configuration and environment",
            }
        )
    if "ros" in p or "isaac" in p or "robot" in p or "zed" in p:
        tags.append(
            {
                "tag_name": "robotics",
                "category": "domain",
                "notes": "Robotics & Simulation",
            }
        )
    if "ansible" in p or "playbook" in p or "role" in p:
        tags.append(
            {
                "tag_name": "infrastructure",
                "category": "infrastructure",
                "notes": "Ansible automation",
            }
        )

    return tags


# -----------------------------------------------------------------------------
# Mapping Engine
# -----------------------------------------------------------------------------


def map_codebase(workspace: Path, incremental: bool = False) -> Dict[str, Any]:
    codebase_db = get_codebase_db_path(workspace)
    init_codebase_db(codebase_db)

    conn = sqlite3.connect(codebase_db)
    cur = conn.cursor()

    current_commit = get_git_commit(workspace)

    cur.execute("SELECT last_scanned_commit FROM git_tracker LIMIT 1")
    row = cur.fetchone()
    last_commit = row[0] if row else ""

    modified_files_filter = None
    if incremental and last_commit:
        modified_files_filter = get_modified_files_since_commit(workspace, last_commit)

    all_files: List[Path] = []
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in IGNORED_EXTENSIONS or f.startswith("."):
                continue
            all_files.append(Path(root) / f)

    stats = {"scanned": 0, "indexed": 0, "skipped": 0, "deleted": 0}
    current_rel_paths = set()

    for full_path in all_files:
        rel_str = str(full_path.relative_to(workspace))
        current_rel_paths.add(rel_str)
        stats["scanned"] += 1

        blob_hash = get_git_blob_hash(full_path, workspace)

        if incremental and modified_files_filter is not None:
            if rel_str not in modified_files_filter:
                cur.execute(
                    "SELECT git_blob_hash FROM files WHERE file_path = ?", (rel_str,)
                )
                row = cur.fetchone()
                if row and row[0] == blob_hash:
                    stats["skipped"] += 1
                    continue

        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f_in:
                content = f_in.read()
        except Exception:
            continue

        ext = full_path.suffix
        lang = detect_language(ext)
        size_bytes = len(content.encode("utf-8"))
        line_count = len(content.splitlines())
        mtime = datetime.datetime.fromtimestamp(full_path.stat().st_mtime).isoformat()
        module = str(full_path.parent.relative_to(workspace)).replace("/", ".")
        if module == ".":
            module = "root"

        if lang == "python":
            symbols, relationships, docstring = parse_python_file(full_path, content)
        else:
            symbols, relationships, docstring = parse_generic_file(
                full_path, content, lang
            )

        tags = infer_tags(rel_str, symbols, lang)

        cur.execute("DELETE FROM files WHERE file_path = ?", (rel_str,))
        cur.execute("DELETE FROM symbols WHERE file_path = ?", (rel_str,))
        cur.execute(
            "DELETE FROM relationships WHERE source_id = ? OR source_id = ?",
            (rel_str, full_path.stem),
        )
        cur.execute("DELETE FROM tags WHERE target_id = ?", (rel_str,))
        cur.execute("DELETE FROM codebase_fts WHERE file_path = ?", (rel_str,))

        cur.execute(
            """
        INSERT INTO files (file_path, extension, size_bytes, line_count, git_blob_hash, last_scanned_commit, last_modified, module, docstring, language)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                rel_str,
                ext,
                size_bytes,
                line_count,
                blob_hash,
                current_commit,
                mtime,
                module,
                docstring,
                lang,
            ),
        )

        for sym in symbols:
            cur.execute(
                """
            INSERT INTO symbols (file_path, name, kind, line_start, line_end, signature, docstring, parent_symbol, visibility)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    rel_str,
                    sym["name"],
                    sym["kind"],
                    sym["line_start"],
                    sym["line_end"],
                    sym["signature"],
                    sym["docstring"],
                    sym["parent_symbol"],
                    sym["visibility"],
                ),
            )

            tag_names = " ".join(t["tag_name"] for t in tags)
            cur.execute(
                """
            INSERT INTO codebase_fts (file_path, symbol_name, kind, signature, docstring, tags, module)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    rel_str,
                    sym["name"],
                    sym["kind"],
                    sym["signature"],
                    sym["docstring"],
                    tag_names,
                    module,
                ),
            )

        for rel in relationships:
            src_id = rel.get("source_id", rel_str)
            cur.execute(
                """
            INSERT INTO relationships (source_id, source_type, relation_type, target_id, target_type, details)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    src_id,
                    rel["source_type"],
                    rel["relation_type"],
                    rel["target_id"],
                    rel["target_type"],
                    rel["details"],
                ),
            )

        for tag in tags:
            cur.execute(
                """
            INSERT INTO tags (tag_name, target_type, target_id, category, notes)
            VALUES (?, 'file', ?, ?, ?)
            """,
                (tag["tag_name"], rel_str, tag["category"], tag["notes"]),
            )

        cur.execute(
            """
        INSERT OR REPLACE INTO git_tracker (file_path, last_blob_hash, last_scanned_commit, status)
        VALUES (?, ?, ?, 'indexed')
        """,
            (rel_str, blob_hash, current_commit),
        )

        stats["indexed"] += 1

    cur.execute("SELECT file_path FROM files")
    db_files = [r[0] for r in cur.fetchall()]
    for db_f in db_files:
        if db_f not in current_rel_paths:
            cur.execute("DELETE FROM files WHERE file_path = ?", (db_f,))
            cur.execute("DELETE FROM symbols WHERE file_path = ?", (db_f,))
            cur.execute("DELETE FROM relationships WHERE source_id = ?", (db_f,))
            cur.execute("DELETE FROM tags WHERE target_id = ?", (db_f,))
            cur.execute("DELETE FROM codebase_fts WHERE file_path = ?", (db_f,))
            cur.execute("DELETE FROM git_tracker WHERE file_path = ?", (db_f,))
            stats["deleted"] += 1

    conn.commit()
    conn.close()

    generate_yaml_guides(workspace)
    return stats


# -----------------------------------------------------------------------------
# YAML Index & Guide Generation
# -----------------------------------------------------------------------------


def generate_yaml_guides(workspace: Path) -> None:
    codebase_db = get_codebase_db_path(workspace)
    conn = sqlite3.connect(codebase_db)
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT tag_name, category FROM tags ORDER BY tag_name")
    tag_rows = cur.fetchall()

    tag_dict = {}
    for tag_name, cat in tag_rows:
        cur.execute(
            "SELECT target_id FROM tags WHERE tag_name = ? LIMIT 5", (tag_name,)
        )
        sample_files = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) FROM tags WHERE tag_name = ?", (tag_name,))
        cnt = cur.fetchone()[0]
        tag_dict[tag_name] = {
            "category": cat,
            "count": cnt,
            "sample_targets": sample_files,
        }

    cur.execute("SELECT COUNT(*) FROM files")
    total_files = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM symbols")
    total_symbols = cur.fetchone()[0]

    current_commit = get_git_commit(workspace)

    index_content = [
        "# ClearSet Codebase Map & RAG Query Guide",
        "clearset_version: '1.0'",
        f"database: '{CS_DIR_NAME}/{CODEBASE_DB_NAME}'",
        f"last_updated: '{datetime.datetime.now(datetime.timezone.utc).isoformat()}Z'",
        f"git_commit: '{current_commit}'",
        "stats:",
        f"  total_indexed_files: {total_files}",
        f"  total_symbols: {total_symbols}",
        "",
        "domain_tags:",
    ]

    for tag_name, info in tag_dict.items():
        index_content.append(f"  {tag_name}:")
        index_content.append(f"    category: '{info['category']}'")
        index_content.append(f"    matching_entities: {info['count']}")
        index_content.append(
            f"    sample_targets: {json.dumps(info['sample_targets'])}"
        )

    index_content.extend(
        [
            "",
            "query_templates:",
            "  find_symbol: \"SELECT file_path, name, kind, signature, line_start FROM symbols WHERE name LIKE '%{SYMBOL}%';\"",
            "  find_callers: \"SELECT source_id, relation_type, details FROM relationships WHERE target_id = '{SYMBOL}' AND relation_type = 'calls';\"",
            "  find_imports: \"SELECT target_id, relation_type, details FROM relationships WHERE source_id = '{FILE}' AND relation_type = 'imports';\"",
            "  search_fts: \"SELECT file_path, symbol_name, kind, signature FROM codebase_fts WHERE codebase_fts MATCH '{KEYWORD}' LIMIT 20;\"",
            "  find_by_tag: \"SELECT target_id, target_type, category FROM tags WHERE tag_name = '{TAG}';\"",
        ]
    )

    with open(workspace / CODEBASE_INDEX_YML, "w", encoding="utf-8") as f_out:
        f_out.write("\n".join(index_content) + "\n")

    cur.execute(
        "SELECT DISTINCT module FROM files WHERE module != 'root' ORDER BY module"
    )
    modules = [r[0] for r in cur.fetchall()]

    dir_content = [
        "# ClearSet Codebase Directory Structure & Architectural Layout",
        "clearset_version: '1.0'",
        f"last_updated: '{datetime.datetime.now(datetime.timezone.utc).isoformat()}Z'",
        "root: '.'",
        "",
        "directories:",
    ]

    for mod in modules:
        mod_path = mod.replace(".", "/")
        cur.execute(
            "SELECT file_path, language FROM files WHERE module = ? LIMIT 5", (mod,)
        )
        mod_files = cur.fetchall()

        cur.execute(
            "SELECT DISTINCT tag_name FROM tags WHERE target_id IN (SELECT file_path FROM files WHERE module = ?)",
            (mod,),
        )
        mod_tags = [r[0] for r in cur.fetchall()]

        dir_content.append(f"  {mod_path}:")
        dir_content.append(f"    layer: '{mod_tags[0] if mod_tags else 'general'}'")
        dir_content.append(f"    tags: {json.dumps(mod_tags)}")
        dir_content.append(
            f"    primary_files: {json.dumps([f[0] for f in mod_files])}"
        )

    with open(workspace / DIR_STRUCTURE_YML, "w", encoding="utf-8") as f_out:
        f_out.write("\n".join(dir_content) + "\n")

    conn.close()


# -----------------------------------------------------------------------------
# Query Engine (RAG)
# -----------------------------------------------------------------------------


def query_codebase(
    workspace: Path,
    symbol: Optional[str] = None,
    tag: Optional[str] = None,
    fts: Optional[str] = None,
    callers: Optional[str] = None,
    deps: Optional[str] = None,
    sql: Optional[str] = None,
) -> List[Dict[str, Any]]:
    codebase_db = get_codebase_db_path(workspace)
    if not codebase_db.exists():
        return [{"error": "Codebase database not initialized. Run 'cs map' first."}]

    conn = sqlite3.connect(codebase_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    results = []

    try:
        if sql:
            cur.execute(sql)
            rows = cur.fetchall()
            results = [dict(r) for r in rows]
        elif symbol:
            cur.execute(
                "SELECT file_path, name, kind, signature, line_start, line_end, docstring FROM symbols WHERE name LIKE ? LIMIT 30",
                (f"%{symbol}%",),
            )
            results = [dict(r) for r in cur.fetchall()]
        elif tag:
            cur.execute(
                "SELECT target_id, target_type, category, notes FROM tags WHERE tag_name = ?",
                (tag,),
            )
            results = [dict(r) for r in cur.fetchall()]
        elif fts:
            cur.execute(
                "SELECT file_path, symbol_name, kind, signature, docstring, tags, module FROM codebase_fts WHERE codebase_fts MATCH ? LIMIT 25",
                (fts,),
            )
            results = [dict(r) for r in cur.fetchall()]
        elif callers:
            cur.execute(
                "SELECT source_id, relation_type, target_id, details FROM relationships WHERE target_id LIKE ? AND relation_type = 'calls'",
                (f"%{callers}%",),
            )
            results = [dict(r) for r in cur.fetchall()]
        elif deps:
            cur.execute(
                "SELECT source_id, relation_type, target_id, details FROM relationships WHERE source_id LIKE ?",
                (f"%{deps}%",),
            )
            results = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        results = [{"error": str(e)}]
    finally:
        conn.close()

    return results


# -----------------------------------------------------------------------------
# Turn Logging & Lifecycle Engine
# -----------------------------------------------------------------------------


def log_turn_action(
    workspace: Path,
    session_id: str,
    milestone: str,
    phase: str,
    task: str,
    action_type: str,
    description: str,
    status: str,
    files: List[str],
    summary: str,
) -> int:
    turns_db = get_turns_db_path(workspace)
    init_turns_db(turns_db)

    conn = sqlite3.connect(turns_db)
    cur = conn.cursor()

    ts = datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z"
    files_json = json.dumps(files or [])

    cur.execute(
        """
    INSERT INTO turn_actions (session_id, timestamp, milestone, phase, task, action_type, description, status, files_touched, output_summary)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            session_id,
            ts,
            milestone,
            phase,
            task,
            action_type,
            description,
            status,
            files_json,
            summary,
        ),
    )

    action_id = cur.lastrowid
    conn.commit()
    conn.close()
    return action_id or 0


def log_learning_or_concern(
    workspace: Path,
    session_id: str,
    kind: str,
    category: str,
    title: str,
    details: str,
    files: List[str],
) -> int:
    turns_db = get_turns_db_path(workspace)
    init_turns_db(turns_db)

    conn = sqlite3.connect(turns_db)
    cur = conn.cursor()

    ts = datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z"
    files_json = json.dumps(files or [])

    cur.execute(
        """
    INSERT INTO learnings_concerns (session_id, timestamp, kind, category, title, details, related_files, is_resolved)
    VALUES (?, ?, ?, ?, ?, ?, ?, 0)
    """,
        (session_id, ts, kind, category, title, details, files_json),
    )

    entry_id = cur.lastrowid
    conn.commit()
    conn.close()
    return entry_id or 0


def create_checkpoint(
    workspace: Path, milestone: str, phase: str, task: str, next_todo: str
) -> Path:
    turns_db = get_turns_db_path(workspace)
    init_turns_db(turns_db)

    current_commit = get_git_commit(workspace)
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z"
    resume_file = workspace / RESUME_FILE

    conn = sqlite3.connect(turns_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(
        "SELECT timestamp, action_type, description, status FROM turn_actions ORDER BY id DESC LIMIT 3"
    )
    recent_actions = cur.fetchall()

    cur.execute(
        "SELECT kind, title, details FROM learnings_concerns WHERE is_resolved = 0 ORDER BY id DESC LIMIT 5"
    )
    open_concerns = cur.fetchall()

    cur.execute(
        """
    INSERT INTO checkpoints (timestamp, milestone, phase, task, next_todo, resume_file_path, git_commit_hash)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        (ts, milestone, phase, task, next_todo, str(resume_file), current_commit),
    )

    conn.commit()
    conn.close()

    lines = [
        "# CLEARSET RESUME HERE",
        "",
        "## Active Execution State",
        f"- **MILESTONE**: {milestone}",
        f"- **Phase**: {phase}",
        f"- **Task**: {task}",
        f"- **Next Todo**: {next_todo}",
        f"- **Checkpoint Timestamp**: {ts}",
        f"- **Git Commit**: {current_commit}",
        "",
        "## Persistent State Data Sources",
        f"- **Turn Actions Database**: `{CS_DIR_NAME}/{TURNS_DB_NAME}`",
        f"- **Codebase RAG Database**: `{CS_DIR_NAME}/{CODEBASE_DB_NAME}`",
        f"- **Codebase Index Guide**: `{CODEBASE_INDEX_YML}`",
        f"- **Directory Structure**: `{DIR_STRUCTURE_YML}`",
        "",
        "## Recent Completed Actions",
    ]

    if recent_actions:
        for a in recent_actions:
            lines.append(
                f"- **{a['action_type']}** [{a['status']}]: {a['description']}"
            )
    else:
        lines.append("- No actions logged in this session yet.")

    lines.extend(["", "## Open Issues, Concerns & Learnings"])
    if open_concerns:
        for c in open_concerns:
            lines.append(f"- **{c['kind'].upper()}** ({c['title']}): {c['details']}")
    else:
        lines.append("- No open issues or concerns recorded.")

    lines.extend(
        [
            "",
            "## Resume Instructions",
            "1. Reset or clear the screen safely using `/clear` or `/cs-clear`.",
            "2. On fresh context, invoke `/cs-resume` to restore project continuity directly from this file and SQLite databases.",
        ]
    )

    with open(resume_file, "w", encoding="utf-8") as f_out:
        f_out.write("\n".join(lines) + "\n")

    return resume_file


def load_resume_state(workspace: Path) -> Dict[str, Any]:
    resume_file = workspace / RESUME_FILE
    if not resume_file.exists():
        return {
            "error": f"No {RESUME_FILE} found in workspace. Run /cs-clear or cs checkpoint first."
        }

    with open(resume_file, "r", encoding="utf-8") as f_in:
        content = f_in.read()

    turns_db = get_turns_db_path(workspace)
    recent_actions = []
    unresolved_concerns = []

    if turns_db.exists():
        conn = sqlite3.connect(turns_db)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT timestamp, action_type, description, status, output_summary FROM turn_actions ORDER BY id DESC LIMIT 5"
        )
        recent_actions = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT kind, category, title, details FROM learnings_concerns WHERE is_resolved = 0 ORDER BY id DESC LIMIT 5"
        )
        unresolved_concerns = [dict(r) for r in cur.fetchall()]
        conn.close()

    return {
        "resume_content": content,
        "recent_actions": recent_actions,
        "unresolved_concerns": unresolved_concerns,
        "resume_file": str(resume_file),
    }


# -----------------------------------------------------------------------------
# Swarm Blackboard & Coordination Engine
# -----------------------------------------------------------------------------


def swarm_dispatch(
    workspace: Path,
    session_id: str,
    milestone: str,
    phase: str,
    topology: str,
    tasks_data: List[Dict[str, Any]],
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    turns_db = get_turns_db_path(workspace)
    init_turns_db(turns_db)

    if not run_id:
        ts_slug = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
        run_id = f"run_{ts_slug}_{hashlib.md5(json.dumps(tasks_data).encode()).hexdigest()[:6]}"

    file_conflicts = []
    if topology == "scatter_gather":
        seen_files: Dict[str, str] = {}
        for t in tasks_data:
            tid = t.get("task_id", "unknown")
            for f in t.get("target_files", []):
                if f in seen_files:
                    file_conflicts.append(
                        f"File '{f}' claimed by both '{seen_files[f]}' and '{tid}'"
                    )
                seen_files[f] = tid

    conn = sqlite3.connect(turns_db)
    cur = conn.cursor()

    ts = datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z"
    total_tasks = len(tasks_data)

    cur.execute(
        """
    INSERT INTO swarm_runs (run_id, session_id, milestone, phase, topology, status, total_tasks, completed_tasks, started_at)
    VALUES (?, ?, ?, ?, ?, 'IN_PROGRESS', ?, 0, ?)
    """,
        (run_id, session_id, milestone, phase, topology, total_tasks, ts),
    )

    for t in tasks_data:
        tid = (
            t.get("task_id")
            or f"task_{hashlib.md5(t.get('title', '').encode()).hexdigest()[:6]}"
        )
        title = t.get("title", "Untitled Task")
        role = t.get("role", "worker")
        t_files = json.dumps(t.get("target_files", []))
        t_symbols = json.dumps(t.get("target_symbols", []))
        v_cmd = t.get("verification_cmd", "")
        max_retries = int(t.get("max_retries", 2))

        cur.execute(
            """
        INSERT INTO swarm_tasks (task_id, run_id, title, role, status, target_files, target_symbols, verification_cmd, max_retries)
        VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?, ?)
        """,
            (tid, run_id, title, role, t_files, t_symbols, v_cmd, max_retries),
        )

    conn.commit()
    conn.close()

    return {
        "run_id": run_id,
        "topology": topology,
        "total_tasks": total_tasks,
        "file_conflicts": file_conflicts,
        "status": "IN_PROGRESS",
    }


def swarm_claim(
    workspace: Path,
    worker_id: str,
    run_id: Optional[str] = None,
    role: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    turns_db = get_turns_db_path(workspace)
    init_turns_db(turns_db)

    conn = sqlite3.connect(turns_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    query = """
    SELECT task_id, run_id, title, role, target_files, target_symbols, verification_cmd, attempt_count, max_retries, traceback_log
    FROM swarm_tasks
    WHERE status = 'PENDING'
    """
    params: List[Any] = []

    if run_id:
        query += " AND run_id = ?"
        params.append(run_id)
    if role:
        query += " AND role = ?"
        params.append(role)

    query += " ORDER BY attempt_count ASC, task_id ASC LIMIT 1"
    cur.execute(query, params)
    row = cur.fetchone()

    if not row:
        conn.close()
        return None

    task_dict = dict(row)
    task_id = task_dict["task_id"]
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z"

    cur.execute(
        """
    UPDATE swarm_tasks
    SET status = 'CLAIMED', claimed_by = ?, claimed_at = ?, attempt_count = attempt_count + 1
    WHERE task_id = ?
    """,
        (worker_id, ts, task_id),
    )

    conn.commit()
    conn.close()

    task_dict["status"] = "CLAIMED"
    task_dict["claimed_by"] = worker_id
    task_dict["claimed_at"] = ts
    task_dict["attempt_count"] += 1
    task_dict["target_files"] = json.loads(task_dict["target_files"] or "[]")
    task_dict["target_symbols"] = json.loads(task_dict["target_symbols"] or "[]")
    return task_dict


def swarm_report(
    workspace: Path,
    task_id: str,
    status: str,
    exit_code: int = 0,
    summary: str = "",
    traceback: str = "",
    files: Optional[List[str]] = None,
) -> Dict[str, Any]:
    turns_db = get_turns_db_path(workspace)
    init_turns_db(turns_db)

    conn = sqlite3.connect(turns_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(
        "SELECT task_id, run_id, title, role, attempt_count, max_retries FROM swarm_tasks WHERE task_id = ?",
        (task_id,),
    )
    task_row = cur.fetchone()
    if not task_row:
        conn.close()
        return {"error": f"Task '{task_id}' not found in swarm_tasks"}

    run_id = task_row["run_id"]
    attempt_count = task_row["attempt_count"]
    max_retries = task_row["max_retries"]
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z"
    files_list = files or []

    cur.execute("SELECT milestone, phase FROM swarm_runs WHERE run_id = ?", (run_id,))
    run_row = cur.fetchone()
    milestone = run_row["milestone"] if run_row else "M001"
    phase = run_row["phase"] if run_row else "01"

    normalized_status = status.upper()
    if normalized_status == "PASSED":
        cur.execute(
            """
        UPDATE swarm_tasks
        SET status = 'PASSED', exit_code = ?, summary = ?, completed_at = ?
        WHERE task_id = ?
        """,
            (exit_code, summary, ts, task_id),
        )

        files_json = json.dumps(files_list)
        cur.execute(
            """
        INSERT INTO turn_actions (session_id, timestamp, milestone, phase, task, action_type, description, status, files_touched, output_summary)
        VALUES (?, ?, ?, ?, ?, 'EXECUTION', ?, 'SUCCESS', ?, ?)
        """,
            (
                "swarm-session",
                ts,
                milestone,
                phase,
                task_id,
                task_row["title"],
                files_json,
                summary,
            ),
        )

        cur.execute(
            "UPDATE swarm_runs SET completed_tasks = completed_tasks + 1 WHERE run_id = ?",
            (run_id,),
        )
        cur.execute(
            "SELECT total_tasks, completed_tasks FROM swarm_runs WHERE run_id = ?",
            (run_id,),
        )
        r_info = cur.fetchone()
        if r_info and r_info["completed_tasks"] >= r_info["total_tasks"]:
            cur.execute(
                "UPDATE swarm_runs SET status = 'COMPLETED', completed_at = ? WHERE run_id = ?",
                (ts, run_id),
            )

        final_state = "PASSED"
    else:
        if attempt_count >= max_retries:
            cur.execute(
                """
            UPDATE swarm_tasks
            SET status = 'FAILED', exit_code = ?, traceback_log = ?, summary = ?, completed_at = ?
            WHERE task_id = ?
            """,
                (exit_code, traceback, summary, ts, task_id),
            )

            cur.execute(
                """
            INSERT INTO learnings_concerns (session_id, timestamp, kind, category, title, details, related_files, is_resolved)
            VALUES (?, ?, 'issue', 'swarm_failure', ?, ?, ?, 0)
            """,
                (
                    "swarm-session",
                    ts,
                    f"Swarm Task Failed: {task_row['title']}",
                    traceback or summary,
                    json.dumps(files_list),
                ),
            )
            final_state = "FAILED"
        else:
            cur.execute(
                """
            UPDATE swarm_tasks
            SET status = 'PENDING', exit_code = ?, traceback_log = ?, summary = ?
            WHERE task_id = ?
            """,
                (exit_code, traceback, summary, task_id),
            )
            final_state = f"RETRYING (Attempt {attempt_count}/{max_retries})"

    conn.commit()
    conn.close()
    return {"task_id": task_id, "run_id": run_id, "status": final_state}


def swarm_post_message(
    workspace: Path,
    run_id: str,
    from_task: str,
    to_task: str,
    message_type: str,
    payload: str,
) -> int:
    turns_db = get_turns_db_path(workspace)
    init_turns_db(turns_db)

    conn = sqlite3.connect(turns_db)
    cur = conn.cursor()
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z"

    cur.execute(
        """
    INSERT INTO swarm_messages (run_id, from_task, to_task, message_type, payload, timestamp)
    VALUES (?, ?, ?, ?, ?, ?)
    """,
        (run_id, from_task, to_task, message_type, payload, ts),
    )

    mid = cur.lastrowid
    conn.commit()
    conn.close()
    return mid or 0


def swarm_status(workspace: Path, run_id: Optional[str] = None) -> Dict[str, Any]:
    turns_db = get_turns_db_path(workspace)
    if not turns_db.exists():
        return {"error": f"Database {turns_db} does not exist."}

    conn = sqlite3.connect(turns_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if run_id:
        cur.execute("SELECT * FROM swarm_runs WHERE run_id = ?", (run_id,))
    else:
        cur.execute("SELECT * FROM swarm_runs ORDER BY started_at DESC LIMIT 1")
    run_row = cur.fetchone()

    if not run_row:
        conn.close()
        return {"error": "No swarm runs found in workspace."}

    active_run_id = run_row["run_id"]
    cur.execute(
        "SELECT * FROM swarm_tasks WHERE run_id = ? ORDER BY task_id ASC",
        (active_run_id,),
    )
    tasks = [dict(r) for r in cur.fetchall()]

    cur.execute(
        "SELECT * FROM swarm_messages WHERE run_id = ? ORDER BY id ASC",
        (active_run_id,),
    )
    messages = [dict(r) for r in cur.fetchall()]
    conn.close()

    for t in tasks:
        t["target_files"] = json.loads(t["target_files"] or "[]")
        t["target_symbols"] = json.loads(t["target_symbols"] or "[]")

    return {"run": dict(run_row), "tasks": tasks, "messages": messages}


# -----------------------------------------------------------------------------
# CLI Interface
# -----------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="ClearSet (cs) Engine: Deterministic Context Resets & State Management CLI"
    )
    parser.add_argument(
        "--workspace", "-w", default=".", help="Target workspace root path"
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommands")

    p_init = subparsers.add_parser(
        "init", help="Initialize ClearSet SQLite databases, YAML indexes, and folders"
    )
    p_init.add_argument("--json", action="store_true", help="Output result as JSON")

    p_map = subparsers.add_parser(
        "map", help="Scan codebase into SQLite and generate YAML guides"
    )
    p_map.add_argument(
        "--incremental",
        "-i",
        action="store_true",
        help="Perform incremental scan based on git hash diffs",
    )
    p_map.add_argument("--json", action="store_true", help="Output stats as JSON")

    p_query = subparsers.add_parser(
        "query", help="Query codebase symbols, tags, FTS, or relationships"
    )
    p_query.add_argument("--symbol", "-s", help="Lookup symbol by name")
    p_query.add_argument("--tag", "-t", help="Lookup entities by domain tag")
    p_query.add_argument("--fts", "-f", help="Full-text search keyword query")
    p_query.add_argument("--callers", "-c", help="Find callers of a function or class")
    p_query.add_argument("--deps", "-d", help="Find dependencies of a file or module")
    p_query.add_argument("--sql", help="Execute raw SQLite query")
    p_query.add_argument("--json", action="store_true", help="Output results as JSON")

    p_log = subparsers.add_parser(
        "log-action", help="Log a turn action into cs_turns.db"
    )
    p_log.add_argument("--session", default="active-session", help="Session ID")
    p_log.add_argument("--milestone", default="M001", help="Milestone ID")
    p_log.add_argument("--phase", default="01", help="Phase ID")
    p_log.add_argument("--task", default="task-01", help="Task ID")
    p_log.add_argument(
        "--type",
        default="EXECUTION",
        choices=["EXECUTION", "REFACTOR", "INVESTIGATION", "FIX", "VERIFICATION"],
        help="Action type",
    )
    p_log.add_argument("--desc", required=True, help="Action description")
    p_log.add_argument("--status", default="SUCCESS", help="Action status")
    p_log.add_argument("--files", nargs="*", default=[], help="Files touched")
    p_log.add_argument("--summary", default="", help="Output summary")
    p_log.add_argument("--json", action="store_true", help="Output result as JSON")

    p_learn = subparsers.add_parser(
        "log-learning", help="Log learning, issue, concern, or decision"
    )
    p_learn.add_argument("--session", default="active-session", help="Session ID")
    p_learn.add_argument(
        "--kind",
        default="learning",
        choices=["learning", "issue", "concern", "decision", "pitfall"],
        help="Kind of note",
    )
    p_learn.add_argument("--category", default="general", help="Category")
    p_learn.add_argument("--title", required=True, help="Short title")
    p_learn.add_argument("--details", required=True, help="Detailed description")
    p_learn.add_argument("--files", nargs="*", default=[], help="Related files")
    p_learn.add_argument("--json", action="store_true", help="Output result as JSON")

    p_chk = subparsers.add_parser(
        "checkpoint", help="Create RESUME HERE.md and checkpoint entry in DB"
    )
    p_chk.add_argument("--milestone", default="M001", help="Current milestone")
    p_chk.add_argument("--phase", default="Phase 1", help="Current phase")
    p_chk.add_argument("--task", default="Task 1", help="Current task")
    p_chk.add_argument("--next", required=True, help="Exact next todo item")
    p_chk.add_argument("--json", action="store_true", help="Output result as JSON")

    p_res = subparsers.add_parser(
        "resume", help="Bootstrap context from RESUME HERE.md and SQLite"
    )
    p_res.add_argument("--json", action="store_true", help="Output state as JSON")

    p_s_dispatch = subparsers.add_parser(
        "swarm-dispatch", help="Dispatch a multi-agent swarm run and enqueue tasks"
    )
    p_s_dispatch.add_argument("--run-id", help="Optional explicit run ID")
    p_s_dispatch.add_argument("--session", default="active-session", help="Session ID")
    p_s_dispatch.add_argument("--milestone", default="M001", help="Milestone ID")
    p_s_dispatch.add_argument("--phase", default="01", help="Phase ID")
    p_s_dispatch.add_argument(
        "--topology",
        default="scatter_gather",
        choices=[
            "scatter_gather",
            "generator_auditor",
            "divergent_research",
            "sentinel",
        ],
        help="Swarm topology",
    )
    p_s_dispatch.add_argument(
        "--tasks-json",
        help="JSON string or path to JSON file containing array of tasks",
    )

    p_s_claim = subparsers.add_parser(
        "swarm-claim", help="Claim next available pending task from swarm ledger"
    )
    p_s_claim.add_argument("--worker-id", required=True, help="Worker or subagent ID")
    p_s_claim.add_argument("--run-id", help="Filter by run ID")
    p_s_claim.add_argument("--role", help="Filter by role")
    p_s_claim.add_argument(
        "--json", action="store_true", help="Output task packet as JSON"
    )

    p_s_report = subparsers.add_parser(
        "swarm-report", help="Report verification results and status for a claimed task"
    )
    p_s_report.add_argument("--task-id", required=True, help="Task ID")
    p_s_report.add_argument(
        "--status",
        required=True,
        choices=["PASSED", "FAILED"],
        help="Verification result",
    )
    p_s_report.add_argument(
        "--exit-code", type=int, default=0, help="Process exit code"
    )
    p_s_report.add_argument("--summary", default="", help="Summary of changes")
    p_s_report.add_argument(
        "--traceback", default="", help="Traceback log or error message if failed"
    )
    p_s_report.add_argument("--files", nargs="*", default=[], help="Files touched")

    p_s_msg = subparsers.add_parser(
        "swarm-post-msg", help="Post typed message / contract update to swarm bus"
    )
    p_s_msg.add_argument("--run-id", required=True, help="Run ID")
    p_s_msg.add_argument("--from-task", required=True, help="Source task ID")
    p_s_msg.add_argument("--to-task", default="ALL", help="Target task ID or ALL")
    p_s_msg.add_argument(
        "--type",
        required=True,
        help="Message type e.g. CONTRACT_UPDATE, CRITIQUE, ADVICE",
    )
    p_s_msg.add_argument(
        "--payload", required=True, help="Message body or JSON payload"
    )

    p_s_status = subparsers.add_parser(
        "swarm-status", help="Display status and progress of swarm runs"
    )
    p_s_status.add_argument("--run-id", help="Filter by run ID (defaults to latest)")
    p_s_status.add_argument("--json", action="store_true", help="Output as JSON")

    p_audit = subparsers.add_parser(
        "audit", help="Deterministic anti-AI defense gate & stylometric auditor"
    )
    p_audit.add_argument(
        "target", help="File path or raw text string to audit (.ipynb, .pdf, .md, .tex, .txt)"
    )
    p_audit.add_argument(
        "--verify", action="store_true", help="Quiet verify mode: exit code 0 if passed, 1 if blocked"
    )
    p_audit.add_argument(
        "--no-db", action="store_true", help="Do not write audit row to cs_turns.db"
    )
    p_audit.add_argument(
        "--json", action="store_true", help="Output machine-readable JSON"
    )

    p_stagger = subparsers.add_parser(
        "stagger", help="Human work commit staggerer & proof-of-work timeline engine"
    )
    p_stagger.add_argument("--repo", default=".", help="Target Git repository path")
    p_stagger.add_argument(
        "--assignment-name", "-a", default="Assignment", help="Assignment name"
    )
    p_stagger.add_argument(
        "--files", nargs="+", default=["."], help="Files/directories to stage in the commits"
    )
    p_stagger.add_argument(
        "--days", type=int, default=3, help="Number of work days to span (default: 3)"
    )
    p_stagger.add_argument(
        "--start-hour", type=int, default=11, help="Work start hour (0-23, default: 11)"
    )
    p_stagger.add_argument(
        "--end-hour", type=int, default=23, help="Work end hour (0-23, default: 23)"
    )
    p_stagger.add_argument(
        "--apply", action="store_true", help="Execute the commits in git"
    )
    p_stagger.add_argument(
        "--push", action="store_true", help="Push commits to origin main after applying"
    )
    p_stagger.add_argument(
        "--no-db", action="store_true", help="Do not log action to cs_turns.db"
    )
    p_stagger.add_argument(
        "--json", action="store_true", help="Output machine-readable JSON"
    )

    args = parser.parse_args()
    workspace = Path(args.workspace).resolve()

    if args.command == "init":
        init_turns_db(get_turns_db_path(workspace))
        init_codebase_db(get_codebase_db_path(workspace))
        stats = map_codebase(workspace, incremental=False)
        if getattr(args, "json", False):
            print(json.dumps({"status": "ok", "workspace": str(workspace), "stats": stats}, indent=2))
        else:
            print(f"ClearSet (cs) initialized successfully in {workspace}")
            print(
                f"Indexed {stats['indexed']} files into SQLite and generated {CODEBASE_INDEX_YML}"
            )

    elif args.command == "map":
        stats = map_codebase(workspace, incremental=args.incremental)
        if getattr(args, "json", False):
            print(json.dumps({"status": "ok", "stats": stats}, indent=2))
        else:
            print(
                f"Codebase mapped: {stats['indexed']} indexed, {stats['skipped']} unchanged, {stats['deleted']} pruned."
            )

    elif args.command == "query":
        res = query_codebase(
            workspace,
            symbol=args.symbol,
            tag=args.tag,
            fts=args.fts,
            callers=args.callers,
            deps=args.deps,
            sql=args.sql,
        )
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            if not res:
                print("No matches found.")
            for item in res:
                if "error" in item:
                    print(f"Error: {item['error']}")
                else:
                    parts = [f"{k}: {v}" for k, v in item.items() if v]
                    print(" | ".join(parts))

    elif args.command == "log-action":
        aid = log_turn_action(
            workspace,
            args.session,
            args.milestone,
            args.phase,
            args.task,
            args.type,
            args.desc,
            args.status,
            args.files,
            args.summary,
        )
        if getattr(args, "json", False):
            print(json.dumps({"status": "ok", "action_id": aid}, indent=2))
        else:
            print(f"Action logged with ID: {aid}")

    elif args.command == "log-learning":
        lid = log_learning_or_concern(
            workspace,
            args.session,
            args.kind,
            args.category,
            args.title,
            args.details,
            args.files,
        )
        if getattr(args, "json", False):
            print(json.dumps({"status": "ok", "learning_id": lid, "kind": args.kind}, indent=2))
        else:
            print(f"{args.kind.capitalize()} recorded with ID: {lid}")

    elif args.command == "checkpoint":
        path = create_checkpoint(
            workspace, args.milestone, args.phase, args.task, args.next
        )
        if getattr(args, "json", False):
            print(json.dumps({
                "status": "ok",
                "checkpoint_file": str(path),
                "milestone": args.milestone,
                "phase": args.phase,
                "task": args.task,
                "next": args.next
            }, indent=2))
        else:
            print(f"Checkpoint created successfully at {path}")

    elif args.command == "resume":
        data = load_resume_state(workspace)
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            if "error" in data:
                print(f"Error: {data['error']}")
            else:
                print(data["resume_content"])

    elif args.command == "swarm-dispatch":
        raw_tasks = []
        if args.tasks_json:
            if os.path.exists(args.tasks_json):
                with open(args.tasks_json, "r", encoding="utf-8") as f:
                    raw_tasks = json.load(f)
            else:
                raw_tasks = json.loads(args.tasks_json)
        res = swarm_dispatch(
            workspace,
            args.session,
            args.milestone,
            args.phase,
            args.topology,
            raw_tasks,
            args.run_id,
        )
        print(
            f"Swarm run '{res['run_id']}' dispatched ({res['topology']}): {res['total_tasks']} tasks enqueued."
        )
        if res.get("file_conflicts"):
            print("WARNING: File conflicts detected across tasks:")
            for c in res["file_conflicts"]:
                print(f"  - {c}")

    elif args.command == "swarm-claim":
        task = swarm_claim(workspace, args.worker_id, args.run_id, args.role)
        if not task:
            print("No pending tasks available for claim.")
        elif args.json:
            print(json.dumps(task, indent=2))
        else:
            print(
                f"Claimed Task: [{task['task_id']}] {task['title']} (Role: {task['role']})"
            )
            print(
                f"Target Files: {', '.join(task['target_files']) if task['target_files'] else 'None'}"
            )
            print(f"Verification: {task['verification_cmd'] or 'None specified'}")

    elif args.command == "swarm-report":
        res = swarm_report(
            workspace,
            args.task_id,
            args.status,
            args.exit_code,
            args.summary,
            args.traceback,
            args.files,
        )
        print(f"Task '{res['task_id']}' reported: {res['status']}")

    elif args.command == "swarm-post-msg":
        mid = swarm_post_message(
            workspace,
            args.run_id,
            args.from_task,
            args.to_task,
            args.type,
            args.payload,
        )
        print(f"Swarm message #{mid} posted successfully.")

    elif args.command == "swarm-status":
        st = swarm_status(workspace, args.run_id)
        if args.json:
            print(json.dumps(st, indent=2))
        elif "error" in st:
            print(f"Error: {st['error']}")
        else:
            run = st["run"]
            print(f"=== Swarm Run: {run['run_id']} [{run['topology']}] ===")
            print(
                f"Status: {run['status']} | Progress: {run['completed_tasks']}/{run['total_tasks']} tasks"
            )
            print(f"Milestone: {run['milestone']} | Phase: {run['phase']}")
            print("\nTasks:")
            for t in st["tasks"]:
                claimed = f"(Claimed by: {t['claimed_by']})" if t["claimed_by"] else ""
                print(f"  - [{t['status']:9s}] {t['task_id']}: {t['title']} {claimed}")
                if t["verification_cmd"]:
                    print(f"      Gate: `{t['verification_cmd']}`")
                if t["summary"]:
                    print(f"      Summary: {t['summary']}")
                if t["traceback_log"]:
                    tb_first = t["traceback_log"].splitlines()[0][:80]
                    print(f"      Traceback: {tb_first}...")
            if st.get("messages"):
                print("\nMessages / Contracts:")
                for m in st["messages"]:
                    print(
                        f"  #{m['id']} [{m['message_type']}] from {m['from_task']} -> {m['to_task']}: {m['payload'][:80]}"
                    )

    elif args.command == "audit":
        from clearset.audit import audit_document

        res = audit_document(args.target, record_to_db=not args.no_db)
        if args.json:
            print(json.dumps(res, indent=2))
            sys.exit(0 if res["passed"] else 1)
        if args.verify:
            if res["passed"]:
                print(
                    f"✓ [AI DEFENSE GATE]: PASSED (AI: {res['ai_probability']*100:.1f}%, 🟢 Green: {res['bucket_counts']['GREEN']}, 🔴 Red: {res['bucket_counts']['RED']})"
                )
                sys.exit(0)
            else:
                print(
                    f"✗ [AI DEFENSE GATE]: BLOCKED (AI: {res['ai_probability']*100:.1f}%, Red Buckets: {res['bucket_counts']['RED']})"
                )
                sys.exit(1)
        print("==================================================================")
        print(f"  AI DEFENSE GATE AUDIT REPORT: {res['verdict']}")
        print("==================================================================")
        print(f"AI Risk Probability:    {res['ai_probability']*100:.1f}%")
        print(f"Human Probability:      {res['human_probability']*100:.1f}%")
        print(f"Passed:                 {res['passed']}")
        print(f"Bucket Counts:          {res['bucket_counts']}")
        print("==================================================================")
        sys.exit(0 if res["passed"] else 1)

    elif args.command == "stagger":
        from clearset.stagger import stagger_assignment

        repo_dir = Path(args.repo).resolve()
        res = stagger_assignment(
            repo_path=str(repo_dir),
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
            print(json.dumps(res, indent=2))
        else:
            print(f"Commit stagger plan for '{res['assignment_name']}': {len(res['plan'])} steps")
            for idx, step in enumerate(res["plan"], 1):
                print(f" [{idx}] {step['formatted_time']}: \"{step['message']}\"")
            if res["applied"]:
                print(f"✅ Created {res['commits_created']} commits successfully (pushed: {res['pushed']}).")
            else:
                print("💡 Dry-run complete. Run with --apply to commit.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

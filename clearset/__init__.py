"""
ClearSet (cs): Deterministic Context Resets, SQLite Blackboard State & Token-Budgeted Retrieval for AI Coding Agents.

https://github.com/Core310/clearset
"""

from clearset.engine import (
    find_workspace,
    get_cs_dir,
    get_codebase_db_path,
    get_turns_db_path,
    init_turns_db,
    init_codebase_db,
    map_codebase,
    query_codebase,
    log_turn_action,
    log_learning_or_concern,
    create_checkpoint,
    load_resume_state,
    swarm_dispatch,
    swarm_claim,
    swarm_report,
    swarm_post_message,
    swarm_status,
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
from clearset.audit import audit_document, evaluate_text
from clearset.stagger import stagger_assignment, CommitStaggerEngine

__version__ = "1.1.0"
__all__ = [
    # Audit & Stagger
    "audit_document",
    "evaluate_text",
    "stagger_assignment",
    "CommitStaggerEngine",
    # Retrieval
    "fetch_symbol_data",
    "fetch_outline_data",
    "fetch_context_data",
    "fetch_call_graph_data",
    "fetch_turn_history_data",
    "fetch_file_slice_data",
    "fetch_swarm_packet_data",
    # Sync & Gate
    "sync_codebase_state",
    "run_verification_gate",
    # Engine & State
    "find_workspace",
    "get_cs_dir",
    "get_codebase_db_path",
    "get_turns_db_path",
    "init_turns_db",
    "init_codebase_db",
    "map_codebase",
    "query_codebase",
    "log_turn_action",
    "log_learning_or_concern",
    "create_checkpoint",
    "load_resume_state",
    # Swarm Blackboard
    "swarm_dispatch",
    "swarm_claim",
    "swarm_report",
    "swarm_post_message",
    "swarm_status",
]

# cs-query

`cs-query` provides instantaneous, token-efficient RAG querying over `.cs/cs_codebase.db` and `.cs/cs_turns.db`.

## Supported Query Types
- **Symbols**: Exact or fuzzy name matching.
- **FTS5 Search**: High-speed keyword search in AST signatures and docstrings.
- **Tags**: Categorized architecture tags.
- **Call Graph**: Inbound callers and outbound dependencies.

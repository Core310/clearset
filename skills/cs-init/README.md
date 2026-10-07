# cs-init

`cs-init` sets up the complete hybrid Spec-Driven RAG environment for any codebase.

## Features
- **Dual SQLite Database Setup**:
  - `cs_turns.db`: Turn logs, active concerns, lessons learned, and checkpoint history.
  - `cs_codebase.db`: High-performance symbol indexing, AST parsing, and FTS5 search.
- **YAML Guide Generation**:
  - `cs_codebase_index.yml`: Tag index and query templates.
  - `cs_directory_structure.yml`: Module hierarchy and architectural boundaries.

## Usage
```bash
cs --workspace . init
```

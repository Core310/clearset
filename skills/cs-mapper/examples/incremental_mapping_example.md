# Example: Incremental Codebase Mapping via Git Diffs

This example demonstrates how `cs-mapper` updates only modified files in a 10,000-file repository in under 200 milliseconds.

## Running Incremental Map
```bash
cs --workspace . map --incremental
```

### Output
```
Codebase mapped: 2 indexed, 10238 unchanged, 0 pruned.
```

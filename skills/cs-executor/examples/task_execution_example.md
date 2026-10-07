# Example: Task Execution and Logging

```bash
cs log-action \
  --milestone "M001" \
  --phase "Phase 2" \
  --task "Task 2.1" \
  --type "EXECUTION" \
  --desc "Added index on symbols(file_path)" \
  --status "SUCCESS" \
  --files ".cs/cs_codebase.db" \
  --summary "Migration applied. Index verified."
```

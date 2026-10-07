# Example: Targeted RAG Querying

This example demonstrates using `cs-fetch` to retrieve exact code context.

## Step 1: Query for Auth Symbols
```bash
cs-fetch symbol auth
```

## Step 2: Slice Targeted File
```bash
cs-fetch slice backend/auth/jwt.py 1 30
```

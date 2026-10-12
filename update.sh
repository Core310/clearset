#!/usr/bin/env bash
# ClearSet (cs) Updater for Linux & macOS
# https://github.com/Core310/clearset

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${REPO_ROOT}"

echo "Updating ClearSet (cs) in ${REPO_ROOT}..."

# 1. Pull latest git commits if running from git checkout
if [ -d ".git" ]; then
  LOCAL_HASH=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
  echo "Current commit: ${LOCAL_HASH}"
  echo "Fetching latest changes..."
  if git pull --ff-only origin main; then
    NEW_HASH=$(git rev-parse --short HEAD 2>/dev/null || echo "${LOCAL_HASH}")
    echo "Updated successfully to commit: ${NEW_HASH}"
  else
    echo "Warning: Fast-forward pull failed. Run 'git status' to inspect local changes."
  fi
fi

# 2. Run installer to refresh binaries and skills
echo "Refreshing CLI binaries and skills..."
"${REPO_ROOT}/install.sh" --install

# 3. Refresh Python editable package
if command -v pip &>/dev/null; then
  echo "Refreshing Python package..."
  pip install -e "${REPO_ROOT}" --no-deps --break-system-packages --quiet 2>/dev/null || pip install -e "${REPO_ROOT}" --no-deps --quiet 2>/dev/null || true
fi

echo ""
echo "ClearSet update complete!"

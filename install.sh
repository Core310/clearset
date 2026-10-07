#!/usr/bin/env bash
# ClearSet (cs) Skills Installer & Manager
# https://github.com/Core310/clearset

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
GEMINI_SKILLS_DIR="${HOME}/.gemini/config/skills"
AGY_SKILLS_DIR="${HOME}/.agy/skills"

show_help() {
  cat <<EOF
ClearSet (cs) Framework Installer & Manager

Usage:
  ./install.sh [options]

Options:
  --install         Install CLI tools to ~/.local/bin and symlink skills (default)
  --update          Pull latest updates from Git and refresh binaries & skills
  --check           Check for upstream updates
  --help            Show this help message
EOF
}

check_updates() {
  echo "Checking for ClearSet updates..."
  if [ -d "${REPO_ROOT}/.git" ]; then
    cd "${REPO_ROOT}"
    LOCAL_HASH=$(git rev-parse --short HEAD 2>/dev/null || echo "initial")
    echo "Current local commit: ${LOCAL_HASH}"
    
    if git fetch origin main --quiet 2>/dev/null; then
      REMOTE_HASH=$(git rev-parse --short origin/main 2>/dev/null || echo "${LOCAL_HASH}")
      echo "Remote origin commit: ${REMOTE_HASH}"
      if [ "${LOCAL_HASH}" != "${REMOTE_HASH}" ]; then
        echo "Update available! (${LOCAL_HASH} -> ${REMOTE_HASH})"
        return 1
      else
        echo "ClearSet is up to date."
        return 0
      fi
    else
      echo "Could not reach remote origin. Skipping remote check."
      return 0
    fi
  fi
  return 0
}

install_cs() {
  echo "Installing ClearSet (cs) from ${REPO_ROOT}..."
  mkdir -p "${BIN_DIR}"
  mkdir -p "${GEMINI_SKILLS_DIR}"
  mkdir -p "${AGY_SKILLS_DIR}"

  CS_ENGINE="${REPO_ROOT}/bin/cs_engine.py"
  CS_FETCH="${REPO_ROOT}/bin/cs_fetch.py"
  CS_CLEANUP="${REPO_ROOT}/bin/cs_cleanup.py"
  CS_SYNC="${REPO_ROOT}/bin/cs_sync.py"
  CS_GATE="${REPO_ROOT}/bin/cs_gate.py"
  CS_MCP="${REPO_ROOT}/bin/cs_mcp.py"
  CS_AUDIT="${REPO_ROOT}/bin/cs_audit.py"
  CS_STAGGER="${REPO_ROOT}/bin/cs_stagger.py"

  chmod +x "${CS_ENGINE}" "${CS_FETCH}" "${CS_CLEANUP}" "${CS_SYNC}" "${CS_GATE}" "${CS_MCP}" "${CS_AUDIT}" "${CS_STAGGER}"

  # 1. Create executable wrapper for cs in ~/.local/bin
  cat <<WRAPPER > "${BIN_DIR}/cs"
#!/usr/bin/env bash
export PYTHONPATH="${REPO_ROOT}:\${PYTHONPATH:-}"
exec python3 "${CS_ENGINE}" "\$@"
WRAPPER
  chmod +x "${BIN_DIR}/cs"

  # 2. Create executable wrapper for cs-fetch in ~/.local/bin
  cat <<WRAPPER > "${BIN_DIR}/cs-fetch"
#!/usr/bin/env bash
export PYTHONPATH="${REPO_ROOT}:\${PYTHONPATH:-}"
exec python3 "${CS_FETCH}" "\$@"
WRAPPER
  chmod +x "${BIN_DIR}/cs-fetch"

  # 3. Create executable wrapper for cs-cleanup in ~/.local/bin
  cat <<WRAPPER > "${BIN_DIR}/cs-cleanup"
#!/usr/bin/env bash
export PYTHONPATH="${REPO_ROOT}:\${PYTHONPATH:-}"
exec python3 "${CS_CLEANUP}" "\$@"
WRAPPER
  chmod +x "${BIN_DIR}/cs-cleanup"

  # 4. Create executable wrapper for cs-sync in ~/.local/bin
  cat <<WRAPPER > "${BIN_DIR}/cs-sync"
#!/usr/bin/env bash
export PYTHONPATH="${REPO_ROOT}:\${PYTHONPATH:-}"
exec python3 "${CS_SYNC}" "\$@"
WRAPPER
  chmod +x "${BIN_DIR}/cs-sync"

  # 5. Create executable wrapper for cs-gate in ~/.local/bin
  cat <<WRAPPER > "${BIN_DIR}/cs-gate"
#!/usr/bin/env bash
export PYTHONPATH="${REPO_ROOT}:\${PYTHONPATH:-}"
exec python3 "${CS_GATE}" "\$@"
WRAPPER
  chmod +x "${BIN_DIR}/cs-gate"

  # 6. Create executable wrapper for cs-mcp in ~/.local/bin
  cat <<WRAPPER > "${BIN_DIR}/cs-mcp"
#!/usr/bin/env bash
export PYTHONPATH="${REPO_ROOT}:\${PYTHONPATH:-}"
exec python3 "${CS_MCP}" "\$@"
WRAPPER
  chmod +x "${BIN_DIR}/cs-mcp"

  # 7. Create executable wrapper for cs-audit in ~/.local/bin
  cat <<WRAPPER > "${BIN_DIR}/cs-audit"
#!/usr/bin/env bash
export PYTHONPATH="${REPO_ROOT}:\${PYTHONPATH:-}"
exec python3 "${CS_AUDIT}" "\$@"
WRAPPER
  chmod +x "${BIN_DIR}/cs-audit"

  # 8. Create executable wrapper for cs-stagger in ~/.local/bin
  cat <<WRAPPER > "${BIN_DIR}/cs-stagger"
#!/usr/bin/env bash
export PYTHONPATH="${REPO_ROOT}:\${PYTHONPATH:-}"
exec python3 "${CS_STAGGER}" "\$@"
WRAPPER
  chmod +x "${BIN_DIR}/cs-stagger"

  # 9. Backward-compatible aliases for legacy cta commands
  ln -sf "${BIN_DIR}/cs" "${BIN_DIR}/cta"
  ln -sf "${BIN_DIR}/cs-fetch" "${BIN_DIR}/cta-fetch"
  ln -sf "${BIN_DIR}/cs-cleanup" "${BIN_DIR}/cta-cleanup"
  ln -sf "${BIN_DIR}/cs-gate" "${BIN_DIR}/cta-gate"
  ln -sf "${BIN_DIR}/cs-audit" "${BIN_DIR}/cta-audit"
  ln -sf "${BIN_DIR}/cs-stagger" "${BIN_DIR}/cta-stagger"

  echo "Installed CLI binaries into ${BIN_DIR}:"
  echo "  - cs         (primary state engine)"
  echo "  - cs-fetch   (token-efficient retrieval)"
  echo "  - cs-sync    (deterministic git-diff auto-sync)"
  echo "  - cs-gate    (deterministic test runner & audit gate)"
  echo "  - cs-cleanup (grug-principled codebase hygiene)"
  echo "  - cs-mcp     (standard Model Context Protocol server)"
  echo "  - cs-audit   (deterministic anti-AI defense & stylometric gate)"
  echo "  - cs-stagger (human proof-of-work commit timeline engine)"
  echo "  - cta, cta-fetch, cta-gate, cta-cleanup, cta-audit, cta-stagger (backward-compatible aliases)"

  # 5. Link skills safely
  for skill_dir in "${REPO_ROOT}/skills"/cs-*; do
    if [ -d "${skill_dir}" ]; then
      skill_name=$(basename "${skill_dir}")
      legacy_name="cta-${skill_name#cs-}"
      
      # Link to Gemini
      rm -rf "${GEMINI_SKILLS_DIR}/${skill_name}"
      ln -sf "${skill_dir}" "${GEMINI_SKILLS_DIR}/${skill_name}"
      # Also link legacy name so existing prompts keep working
      rm -rf "${GEMINI_SKILLS_DIR}/${legacy_name}"
      ln -sf "${skill_dir}" "${GEMINI_SKILLS_DIR}/${legacy_name}"

      # Link to AGY
      rm -rf "${AGY_SKILLS_DIR}/${skill_name}"
      ln -sf "${skill_dir}" "${AGY_SKILLS_DIR}/${skill_name}"
      rm -rf "${AGY_SKILLS_DIR}/${legacy_name}"
      ln -sf "${skill_dir}" "${AGY_SKILLS_DIR}/${legacy_name}"
    fi
  done

  echo "Linked ClearSet skills to:"
  echo "  - ${GEMINI_SKILLS_DIR}"
  echo "  - ${AGY_SKILLS_DIR}"

  # PATH verification
  if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo ""
    echo "NOTE: ${BIN_DIR} is not in your current PATH."
    echo "Add it in your ~/.bashrc or ~/.zshrc:"
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
  fi

  echo ""
  echo "ClearSet (cs) Installation Successful!"
  "${BIN_DIR}/cs" --help | head -n 6
}

update_cs() {
  echo "Updating ClearSet..."
  if [ -d "${REPO_ROOT}/.git" ]; then
    cd "${REPO_ROOT}"
    LOCAL_BEFORE=$(git rev-parse --short HEAD 2>/dev/null || echo "init")
    echo "Pulling latest repository changes..."
    git pull --ff-only origin main || {
      echo "Warning: git pull failed or no remote branch yet."
    }
    LOCAL_AFTER=$(git rev-parse --short HEAD 2>/dev/null || echo "init")
    echo "Repository updated: ${LOCAL_BEFORE} -> ${LOCAL_AFTER}"
  fi
  install_cs
}

MODE="${1:---install}"

case "${MODE}" in
  --install)
    install_cs
    ;;
  --update)
    update_cs
    ;;
  --check)
    check_updates || true
    ;;
  --help|-h)
    show_help
    ;;
  *)
    echo "Unknown option: ${MODE}"
    show_help
    exit 1
    ;;
esac

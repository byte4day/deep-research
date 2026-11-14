#!/usr/bin/env bash
# Remove deep-research. Research run folders (research/, ~/research/) are never touched.
set -euo pipefail
rm -f "${HOME}/.claude/agents/researcher.md" "${HOME}/.cursor/agents/researcher.md" "${HOME}/.codex/agents/researcher.toml"
if [[ -L "${HOME}/.claude/skills/deep-research" ]]; then rm "${HOME}/.claude/skills/deep-research"; fi
rm -rf "${HOME}/.agents/skills/deep-research"
echo "deep-research removed."

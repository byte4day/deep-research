#!/usr/bin/env bash
# Install deep-research (skill + researcher agent). Idempotent; safe to re-run.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VERSION="$(tr -d '[:space:]' < "${ROOT}/VERSION")"
TARGET="${1:-all}"

case "${TARGET}" in
  all|claude|cursor|codex) ;;
  -h|--help) echo "Usage: ./install.sh [all|claude|cursor|codex]"; exit 0 ;;
  *) echo "Usage: ./install.sh [all|claude|cursor|codex]" >&2; exit 1 ;;
esac

command -v python3 >/dev/null 2>&1 || { echo "error: python3 is required" >&2; exit 1; }

SKILL="${HOME}/.agents/skills/deep-research"

install_skill() {
  if [[ -L "${SKILL}" ]]; then rm "${SKILL}"; fi
  mkdir -p "${SKILL}/scripts" "${SKILL}/references" "${SKILL}/agents"
  cp "${ROOT}/skills/deep-research/SKILL.md" "${SKILL}/SKILL.md"
  cp "${ROOT}/skills/deep-research/scripts/research.py" "${SKILL}/scripts/research.py"
  cp "${ROOT}/skills/deep-research/references/"*.md "${SKILL}/references/"
  cp "${ROOT}/skills/deep-research/agents/openai.yaml" "${SKILL}/agents/openai.yaml"
  rm -rf "${SKILL}/scripts/__pycache__"
  chmod +x "${SKILL}/scripts/research.py"
  printf '%s\n' "${VERSION}" > "${SKILL}/VERSION"
  echo "  skill → ${SKILL}"
}

install_claude() {
  mkdir -p "${HOME}/.claude/agents" "${HOME}/.claude/skills"
  local link="${HOME}/.claude/skills/deep-research"
  if [[ -e "${link}" && ! -L "${link}" ]]; then
    local backup="${HOME}/.agents/deep-research-backups/claude-skill.$(date +%Y%m%d%H%M%S)"
    mkdir -p "$(dirname "${backup}")"
    mv "${link}" "${backup}"
    echo "  moved existing ${link} → ${backup}"
  fi
  ln -sfn "${SKILL}" "${link}"
  cp "${ROOT}/agents/claude/researcher.md" "${HOME}/.claude/agents/researcher.md"
  echo "  Claude Code: skill link + agent ~/.claude/agents/researcher.md"
}

# Cursor and Codex read ~/.agents/skills directly; they only need the agent file.
install_cursor() {
  mkdir -p "${HOME}/.cursor/agents"
  cp "${ROOT}/agents/cursor/researcher.md" "${HOME}/.cursor/agents/researcher.md"
  echo "  Cursor: agent ~/.cursor/agents/researcher.md"
}

install_codex() {
  mkdir -p "${HOME}/.codex/agents"
  cp "${ROOT}/agents/codex/researcher.toml" "${HOME}/.codex/agents/researcher.toml"
  echo "  Codex: agent ~/.codex/agents/researcher.toml"
}

echo "Installing deep-research ${VERSION}…"
install_skill
case "${TARGET}" in
  all)
    install_claude
    # Only hosts that exist on this machine.
    if [[ -d "${HOME}/.cursor" ]]; then install_cursor; fi
    if [[ -d "${HOME}/.codex" ]]; then install_codex; fi
    ;;
  claude) install_claude ;;
  cursor) install_cursor ;;
  codex) install_codex ;;
esac

echo
echo "deep-research ${VERSION} ready."
echo "  Claude Code:  claude --agent researcher   (or ask: \"research X with sources\")"
echo "  Script:       python3 ~/.agents/skills/deep-research/scripts/research.py --help"

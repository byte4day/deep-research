#!/usr/bin/env bash
# Installer smoke test in a throwaway $HOME. Never touches the real home dir.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FAKE="$(mktemp -d)"
trap 'rm -rf "${FAKE}"' EXIT
export HOME="${FAKE}"
pass=0
ok() { echo "ok  $*"; pass=$((pass + 1)); }
die() { echo "FAIL $*" >&2; exit 1; }

mkdir -p "${HOME}/.codex" "${HOME}/.claude/skills/deep-research"
echo "old" > "${HOME}/.claude/skills/deep-research/SKILL.md"

bash "${ROOT}/install.sh" >/dev/null || die "install.sh failed"
for f in .agents/skills/deep-research/SKILL.md .agents/skills/deep-research/scripts/research.py \
         .agents/skills/deep-research/references/sources.md .agents/skills/deep-research/references/report.md \
         .agents/skills/deep-research/VERSION .claude/agents/researcher.md .codex/agents/researcher.toml; do
  [[ -f "${HOME}/${f}" ]] || die "missing ${f}"
done
ok "files installed"
[[ -L "${HOME}/.claude/skills/deep-research" ]] || die "claude skill is not a symlink"
ls "${HOME}/.agents/deep-research-backups/" | grep -q claude-skill || die "existing skill dir was not backed up"
ok "existing skill folder backed up, link created"
[[ ! -e "${HOME}/.cursor" ]] || die "created ~/.cursor on a machine without Cursor"
ok "absent hosts are left alone"

bash "${ROOT}/install.sh" >/dev/null || die "re-install failed"
[[ "$(ls "${HOME}/.agents/deep-research-backups/" | wc -l)" -eq 1 ]] || die "re-install made another backup"
ok "re-install is idempotent"

python3 "${HOME}/.claude/skills/deep-research/scripts/research.py" init "${HOME}/run" -q "Test?" >/dev/null || die "installed script failed"
[[ -f "${HOME}/run/ledger.json" ]] || die "no ledger"
ok "installed script runs"

bash "${ROOT}/install.sh" cursor >/dev/null && [[ -f "${HOME}/.cursor/agents/researcher.md" ]] || die "cursor target failed"
ok "explicit cursor target"
if bash "${ROOT}/install.sh" nope >/dev/null 2>&1; then die "bad target accepted"; fi
ok "bad target rejected"

bash "${ROOT}/uninstall.sh" >/dev/null || die "uninstall failed"
[[ ! -e "${HOME}/.agents/skills/deep-research" && ! -e "${HOME}/.claude/agents/researcher.md" && ! -e "${HOME}/.claude/skills/deep-research" ]] || die "uninstall left files"
[[ -f "${HOME}/run/ledger.json" ]] || die "uninstall removed research data"
ok "uninstall keeps research runs"
echo "${pass} checks passed"

#!/usr/bin/env bash
# charter.sh — Dispatcher for the Charter helper scripts
# Usage: charter.sh <script-name> [args...]
#
# Runs scripts/bash/<script-name>.sh with the remaining arguments, keeping
# stdin, stdout, stderr and the exit code of the dispatched script intact.
# Command files reference this dispatcher through Spec Kit's {SCRIPT}
# placeholder so one frontmatter entry covers every helper script.
#
# Exit codes:
#   0 = dispatched script succeeded (or --help)
#   1 = no argument, unknown script name
#   * = exit code of the dispatched script
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  echo "Usage: charter.sh <script-name> [args...]"
  echo ""
  echo "Available scripts:"
  local f name
  for f in "${SCRIPT_DIR}"/*.sh; do
    name="$(basename "$f" .sh)"
    case "$name" in
      charter|charter-common) continue ;;
    esac
    echo "  ${name}"
  done
}

if [[ $# -eq 0 ]]; then
  usage
  exit 1
fi

case "$1" in
  -h|--help)
    usage
    exit 0
    ;;
esac

NAME="$1"
shift

case "$NAME" in
  charter|charter-common)
    echo "❌ ERROR: Unknown charter script: ${NAME}" >&2
    exit 1
    ;;
esac

if ! [[ "$NAME" =~ ^[a-z0-9-]+$ ]] || [[ ! -f "${SCRIPT_DIR}/${NAME}.sh" ]]; then
  echo "❌ ERROR: Unknown charter script: ${NAME}" >&2
  exit 1
fi

exec bash "${SCRIPT_DIR}/${NAME}.sh" "$@"

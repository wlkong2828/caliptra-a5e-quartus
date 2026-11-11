#!/usr/bin/env bash
# Download (or update) pwilliam282/caliptra-a5e-quartus with its pinned upstream RTL submodules.
# Works on macOS and Linux (bash 3.2+, git >= 2.13). Standalone: you can curl it and run it
# before you have a clone.
#
#   bash get_caliptra_a5e.sh [DIR]          # default DIR: ./caliptra-a5e-quartus
#   BRANCH=main REPO_URL=... bash get_caliptra_a5e.sh ~/work/caliptra-a5e-quartus
#
# New DIR      -> git clone --recursive
# Existing DIR -> git pull --ff-only + git submodule sync/update --init --recursive
#                 (refuses to touch a checkout with uncommitted changes to tracked files)
# Then runs scripts/fetch_deps.sh --check (pinned commits: caliptra-rtl v1.1 5f85fb4,
# caliptra-rtl v2.1.2 4937026, adams-bridge b77e3d8).
set -euo pipefail
REPO_URL=${REPO_URL:-https://github.com/pwilliam282/caliptra-a5e-quartus.git}
BRANCH=${BRANCH:-main}
DIR=${1:-caliptra-a5e-quartus}

command -v git >/dev/null 2>&1 || { echo "error: git not found (macOS: xcode-select --install)" >&2; exit 1; }

if [ -d "$DIR/.git" ]; then
  echo "== updating existing clone in $DIR"
  cd "$DIR"
  if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "error: $DIR has uncommitted changes to tracked files; commit or stash them first" >&2
    exit 1
  fi
  git fetch origin "$BRANCH"
  git checkout -q "$BRANCH"
  git pull --ff-only origin "$BRANCH"
  git submodule sync --recursive
  git submodule update --init --recursive
elif [ -e "$DIR" ] && [ -n "$(ls -A "$DIR" 2>/dev/null)" ]; then
  echo "error: $DIR exists, is not empty and is not a git clone" >&2
  exit 1
else
  echo "== cloning $REPO_URL ($BRANCH) into $DIR"
  git clone --recursive --branch "$BRANCH" "$REPO_URL" "$DIR"
  cd "$DIR"
fi

echo "== checking pinned dependencies"
scripts/fetch_deps.sh --check
echo
echo "Sources ready in: $(pwd)"
echo "Next (on a Linux x86-64 host with Quartus Pro 25.3, or Docker + license):"
echo "  export LIC_HOST=/path/to/SW-AGILEX-5E.dat"
echo "  scripts/quartus_docker.sh quartus_a5e_nios 'quartus_ipgenerate nios_caliptra_a5e && quartus_syn nios_caliptra_a5e'"

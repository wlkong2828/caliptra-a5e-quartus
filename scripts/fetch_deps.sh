#!/usr/bin/env bash
# Fetch the upstream Caliptra RTL this repo synthesizes against, pinned to exact commits.
# Works on Linux and macOS (bash 3.2+, git). Run from anywhere inside the repo:
#
#   scripts/fetch_deps.sh            # init/update submodules (or clone if not a git checkout)
#   scripts/fetch_deps.sh --check    # only verify what is checked out
#
#   external/caliptra-rtl-1x  chipsalliance/caliptra-rtl v1.1    5f85fb4bc95b753a2f7d042db7dc2644ca1e8c49
#   external/caliptra-rtl-2x  chipsalliance/caliptra-rtl v2.1.2  49370266d12cb0c4a8f71b3a0ff7e54ba7d4866e
#     submodules/adams-bridge chipsalliance/adams-bridge v2.0.3  b77e3d899e828d626cfc2a0d26a6b5704cc121e0
#
# The upstream RTL is used unmodified. All synthesis overrides live in this repo
# (quartus/syn_src, caliptra2x/quartus_a5e_2x/syn_src, rtl/, caliptra2x/rtl_2x/).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
URL=https://github.com/chipsalliance/caliptra-rtl.git
ABR_URL=https://github.com/chipsalliance/adams-bridge.git
PIN_1X=5f85fb4bc95b753a2f7d042db7dc2644ca1e8c49
PIN_2X=49370266d12cb0c4a8f71b3a0ff7e54ba7d4866e
PIN_ABR=b77e3d899e828d626cfc2a0d26a6b5704cc121e0

head_of() { git -C "$1" rev-parse HEAD 2>/dev/null || echo none; }

clone_pinned() {  # dir url sha
  local d=$1 u=$2 s=$3
  if [ ! -e "$d/.git" ]; then
    rm -rf "$d"; mkdir -p "$d"
    git -C "$d" init -q
    git -C "$d" remote add origin "$u"
  fi
  if [ "$(head_of "$d")" != "$s" ]; then
    git -C "$d" fetch -q --depth 1 origin "$s" 2>/dev/null || git -C "$d" fetch -q origin
    git -C "$d" checkout -q --detach "$s"
  fi
}

if [ "${1:-}" != "--check" ]; then
  if git -C "$REPO" rev-parse --show-toplevel >/dev/null 2>&1 && [ -f .gitmodules ]; then
    echo "== git submodule update --init --recursive"
    git submodule sync -q --recursive
    git submodule update --init --recursive
  else
    echo "== not a git checkout (zip download?): cloning pinned commits into external/"
    clone_pinned external/caliptra-rtl-1x "$URL" "$PIN_1X"
    clone_pinned external/caliptra-rtl-2x "$URL" "$PIN_2X"
    clone_pinned external/caliptra-rtl-2x/submodules/adams-bridge "$ABR_URL" "$PIN_ABR"
  fi
fi

rc=0
chk() {  # dir sha label
  local h; h=$(head_of "$1")
  if [ "$h" = "$2" ]; then echo "ok   $3  $1 @ ${h:0:12}"; else echo "FAIL $3  $1 @ $h (want $2)"; rc=1; fi
  if [ -n "$(git -C "$1" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    echo "warn $1 has local modifications (upstream RTL is expected to be pristine)"
  fi
}
chk external/caliptra-rtl-1x "$PIN_1X" "caliptra-rtl v1.1  "
chk external/caliptra-rtl-2x "$PIN_2X" "caliptra-rtl v2.1.2"
chk external/caliptra-rtl-2x/submodules/adams-bridge "$PIN_ABR" "adams-bridge v2.0.3"
for f in external/caliptra-rtl-1x/src/integration/rtl/caliptra_top.sv \
         external/caliptra-rtl-2x/src/integration/rtl/caliptra_top.sv \
         external/caliptra-rtl-2x/submodules/adams-bridge/src/abr_top/rtl/abr_ctrl.sv; do
  [ -f "$f" ] || { echo "FAIL missing $f"; rc=1; }
done
[ $rc = 0 ] && echo "deps OK" || echo "deps NOT OK"
exit $rc

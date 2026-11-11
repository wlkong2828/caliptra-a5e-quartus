#!/usr/bin/env bash
# Run a Quartus Prime Pro 25.3 command inside the official Altera Docker image.
#
#   scripts/quartus_docker.sh <dir> '<command>'
#   e.g. scripts/quartus_docker.sh quartus_a5e_nios 'quartus_syn nios_caliptra_a5e'
#
# <dir> is the working directory inside the container (relative to the repo root,
# or absolute). The whole repo (including external/ submodules) is mounted at the
# same path, so the repo-relative paths in the .qsf files resolve unchanged.
#
# Environment:
#   LIC_HOST      path on the host to your Quartus license file (Agilex 5E needs the
#                 no-cost SW-AGILEX-5E license; it is node-locked to a NIC MAC address).
#                 Default: $REPO/license/SW-AGILEX-5E.dat (gitignored), then
#                 /workspace/altera_license/SW-AGILEX-5E.dat.
#   QUARTUS_IMAGE Docker image (default alterafpga/quartuspro-v25.3:agilex5).
#   DOCKER_NAME   optional container name.
#
# --net=host is required: FlexLM reads the host-ID from the NIC; without it quartus_syn
# can segfault in the license host-ID lookup. The image is linux/amd64: use a Linux
# x86_64 host (or VM). Apple-silicon Macs cannot run it reliably under emulation.
set -euo pipefail
[ $# -ge 2 ] || { sed -n '2,8p' "$0"; exit 2; }
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WD="$1"; shift
case "$WD" in /*) ;; *) WD="$REPO/$WD" ;; esac
WD="$(cd "$WD" && pwd)"
[ -d /workspace/docker-bin ] && export PATH=/workspace/docker-bin:$PATH
if [ -z "${LIC_HOST:-}" ]; then
  for c in "$REPO/license/SW-AGILEX-5E.dat" /workspace/altera_license/SW-AGILEX-5E.dat; do
    [ -f "$c" ] && { LIC_HOST="$c"; break; }
  done
fi
[ -n "${LIC_HOST:-}" ] && [ -f "$LIC_HOST" ] || {
  echo "error: no Quartus license file; set LIC_HOST=/path/to/SW-AGILEX-5E.dat" >&2; exit 1; }
if [ ! -f "$REPO/external/caliptra-rtl-1x/src/integration/rtl/caliptra_top.sv" ] ||
   [ ! -f "$REPO/external/caliptra-rtl-2x/submodules/adams-bridge/src/abr_top/rtl/abr_ctrl.sv" ]; then
  echo "error: external/caliptra-rtl-* missing; run scripts/fetch_deps.sh first" >&2; exit 1
fi
NAME=(); [ -n "${DOCKER_NAME:-}" ] && NAME=(--name "$DOCKER_NAME")
exec docker run --rm "${NAME[@]+"${NAME[@]}"}" --net=host --platform linux/amd64 \
  -u "$(id -u):$(id -g)" -e HOME=/tmp \
  -e LM_LICENSE_FILE=/licenses/quartus.dat -e ALTERA_LICENSE_FILE=/licenses/quartus.dat \
  -v "$REPO":"$REPO" -v "$LIC_HOST":/licenses/quartus.dat:ro \
  -w "$WD" "${QUARTUS_IMAGE:-alterafpga/quartuspro-v25.3:agilex5}" bash -lc "$*"

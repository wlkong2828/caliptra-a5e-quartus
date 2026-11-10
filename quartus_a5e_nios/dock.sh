#!/bin/bash
# Run a command inside Quartus Pro 25.3 Agilex5 Docker. Usage: ./dock.sh 'cmd'
# License path overridable: LIC_HOST=/path/to/SW-AGILEX-5E.dat ./dock.sh ...
set -euo pipefail
export PATH=/workspace/docker-bin:$PATH
LIC_HOST=${LIC_HOST:-/workspace/altera_license/SW-AGILEX-5E.dat}
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
# If caliptra-rtl/ is a symlink (e.g. into a caliptra-sw checkout), mount its target too.
EXTRA=()
if [ -L "$ROOT/caliptra-rtl" ]; then T="$(readlink -f "$ROOT/caliptra-rtl")"; EXTRA=(-v "$T":"$T":ro); fi
docker run --rm --net=host "${EXTRA[@]}" -u "$(id -u):$(id -g)" -e HOME=/tmp \
  -e LM_LICENSE_FILE=/licenses/SW-AGILEX-5E.dat -e ALTERA_LICENSE_FILE=/licenses/SW-AGILEX-5E.dat \
  -v "$ROOT":"$ROOT" -v "$LIC_HOST":/licenses/SW-AGILEX-5E.dat:ro \
  -w "$HERE" alterafpga/quartuspro-v25.3:agilex5 bash -lc "$1"

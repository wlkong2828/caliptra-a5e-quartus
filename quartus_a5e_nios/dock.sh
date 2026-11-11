#!/bin/bash
# Run a command inside Quartus Pro 25.3 Agilex5 Docker, in this directory. Usage: ./dock.sh 'cmd'
# License: LIC_HOST=/path/to/SW-AGILEX-5E.dat ./dock.sh ...   (see ../scripts/quartus_docker.sh)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
exec "$HERE/../scripts/quartus_docker.sh" "$HERE" "$1"

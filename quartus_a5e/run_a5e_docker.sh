#!/bin/bash
# Caliptra 1.x core-only (caliptra_passive_top) on A5EC065BB32AE6S, Quartus Pro 25.3 in Docker.
# Usage: ./run_a5e_docker.sh [syn|fit]    (fit needs >=32 GB RAM)
# License: LIC_HOST=/path/to/SW-AGILEX-5E.dat (see ../scripts/quartus_docker.sh).
set -uo pipefail
cd "$(dirname "$0")"
CMD="quartus_syn --parallel=${QPAR:-8} caliptra_a5e"
[ "${1:-syn}" = fit ] && CMD="$CMD && quartus_fit --parallel=${QPAR:-8} caliptra_a5e"
../scripts/quartus_docker.sh "$PWD" "$CMD" > flow.log 2>&1
rc=$?
grep -E "Logic utilization|ALMs|Error \(" output_files/caliptra_a5e.syn.summary flow.log 2>/dev/null | head
echo "rc=$rc"

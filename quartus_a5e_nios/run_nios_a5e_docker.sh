#!/bin/bash
# Nios V + Caliptra 1.x on A5EC065BB32AE6S: regenerate PD system, IP generate, synthesize.
# Usage: ./run_nios_a5e_docker.sh [syn|fit]   (fit needs >=32 GB RAM)
# LIC_HOST=/path/to/SW-AGILEX-5E.dat overrides the license path (host-ID = NIC MAC; --net=host).
set -euo pipefail
cd "$(dirname "$0")"
STAGE=${1:-syn}
CMD="cd qsys && rm -rf ip nios_caliptra_sys nios_caliptra_sys.qsys .qsys_edit && qsys-script --script=nios_caliptra_sys.tcl --quartus-project=none && cd .. && quartus_ipgenerate nios_caliptra_a5e && quartus_syn --parallel=${QPAR:-8} nios_caliptra_a5e"
[ "$STAGE" = fit ] && CMD="$CMD && quartus_fit --parallel=${QPAR:-8} nios_caliptra_a5e"
./dock.sh "$CMD" > flow.log 2>&1; rc=$?
grep -E "Logic utilization|ALMs|Error \(" output_files/nios_caliptra_a5e.syn.summary flow.log 2>/dev/null | head
echo "rc=$rc"

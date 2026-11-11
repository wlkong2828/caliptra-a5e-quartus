#!/bin/bash
# Nios V + Caliptra 2.x on A5EC065BB32AE6S: regenerate PD system, IP generate, synthesize.
# Same flow as ../../quartus_a5e_nios/run_nios_a5e_docker.sh (Caliptra 1.1).
# Usage: ./run_nios2x_a5e_docker.sh [syn|fit]
#   syn: ~25-30 min, ~7-8 GB peak RAM. fit: the 2.x design does NOT fit the A5E 065 (Caliptra 2.x
#   alone is ~126 % of the ALMs), so fit is expected to stop with a "not enough ALMs" error.
# LIC_HOST=/path/to/SW-AGILEX-5E.dat overrides the license path (host-ID = NIC MAC; --net=host).
set -uo pipefail
cd "$(dirname "$0")"
STAGE=${1:-syn}
[ -f onchip_mem.hex ] || { echo "error: onchip_mem.hex missing; run sw/build_app.sh first" >&2; exit 1; }
CMD="cd qsys && rm -rf ip nios_caliptra2x_sys nios_caliptra2x_sys.qsys .qsys_edit && qsys-script --script=nios_caliptra2x_sys.tcl --quartus-project=none && cd .. && quartus_ipgenerate nios_caliptra2x_a5e && quartus_syn --parallel=${QPAR:-4} nios_caliptra2x_a5e"
[ "$STAGE" = fit ] && CMD="$CMD && quartus_fit --parallel=${QPAR:-4} nios_caliptra2x_a5e"
start=$(date +%s)
./dock.sh "$CMD" > flow.log 2>&1; rc=$?
grep -E "Logic utilization|registers|DSP|Error \(" output_files/nios_caliptra2x_a5e.syn.summary flow.log 2>/dev/null | head
echo "rc=$rc wall_s=$(( $(date +%s)-start ))"

#!/bin/bash
# Build + run the Caliptra 2.x Nios-glue boot sim (behavioral Nios host, real glue RTL).
# Usage (detached):  nohup setsid ./run_nios2x_top_fw.sh +test=all > run.out 2>&1 &
#   env THREADS (default 4), BUILD=0 to skip rebuild. Log: nios2x_top_fw_run.log
set -eo pipefail
cd "$(dirname "$0")"
VERILATOR_BIN=${VERILATOR_BIN:-}; [ -n "$VERILATOR_BIN" ] && [ -d "$VERILATOR_BIN" ] && export PATH="$VERILATOR_BIN:$PATH"
if [ "${BUILD:-1}" = 1 ]; then
  VCFLAGS=$(../../scripts/verilator_cflags.sh)  # -fcoroutines on GCC 10-12
  verilator --binary $VCFLAGS --threads ${THREADS:-4} -j 8 -O3 -Wno-fatal -Wno-lint -Wno-style -Wno-UNOPTFLAT \
    -Wno-MULTIDRIVEN -Wno-TIMESCALEMOD --top-module tb_nios2x_top_fw -Mdir obj_nios2x -f boot2x.f \
    -o Vtb_nios2x > nios2x_build.log 2>&1
fi
start=$(date +%s); echo "run start $(date)"
stdbuf -oL -eL ./obj_nios2x/Vtb_nios2x "$@" > nios2x_top_fw_run.log 2>&1 || true
echo "wall_time_s=$(( $(date +%s)-start )) end $(date)" | tee -a nios2x_top_fw_run.log

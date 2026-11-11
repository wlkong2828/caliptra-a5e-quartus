#!/bin/bash
# Sim the real nios_caliptra_top glue (fuse ctrl IP + FW store + mailbox FIRMWARE_LOAD,
# 2FF reset sync, PAUSER lock, warm-reset START_DONE, fatal pwrgood recovery)
# with a behavioral Nios.
# Needs verilator >= 5.0 and external/caliptra-rtl-1x (v1.1): run ../scripts/fetch_deps.sh first.
# Plusargs: +test=prod|sync|pauser|warm|fatal|all  (default all)
#           +max_cycles=N  (default 200000000)
set -eo pipefail
cd "$(dirname "$0")"
VERILATOR_BIN=${VERILATOR_BIN:-}; [ -n "$VERILATOR_BIN" ] && [ -d "$VERILATOR_BIN" ] && export PATH="$VERILATOR_BIN:$PATH"
if [ ! -f ../external/caliptra-rtl-1x/src/integration/rtl/caliptra_top.sv ]; then
  echo "error: external/caliptra-rtl-1x missing; run ../scripts/fetch_deps.sh (caliptra-rtl v1.1)" >&2
  exit 1
fi
N=../quartus_a5e_nios/rtl
VCFLAGS=$(../scripts/verilator_cflags.sh)  # -fcoroutines on GCC 10-12
verilator --binary $VCFLAGS -j 8 -O3 -Wno-fatal -Wno-lint -Wno-style -Wno-UNOPTFLAT -Wno-MULTIDRIVEN -Wno-TIMESCALEMOD \
  --timing --top-module tb_nios_top_fw -Mdir obj_nios_top_fw -f boot_apb.f \
  rst_release_stub.sv $N/reset_sync.sv $N/avmm_to_apb.sv $N/soc_fuse_ctrl.sv $N/soc_fw_store.sv $N/nios_caliptra_top.sv tb_nios_top_fw.sv > nios_top_fw_build.log 2>&1
start=$(date +%s)
# Default plusargs if the caller did not pass them
args=("$@")
has_test=0; has_max=0
for a in "${args[@]+"${args[@]}"}"; do
  case "$a" in +test=*) has_test=1;; +max_cycles=*) has_max=1;; esac
done
(( has_test )) || args+=(+test=all)
(( has_max ))  || args+=(+max_cycles=200000000)
./obj_nios_top_fw/Vtb_nios_top_fw "${args[@]}" | tee nios_top_fw_run.log
echo "wall_time_s=$(( $(date +%s)-start ))" | tee -a nios_top_fw_run.log

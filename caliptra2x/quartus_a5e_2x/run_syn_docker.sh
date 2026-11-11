#!/bin/bash
# Caliptra 2.x core-only synthesis (analysis & synthesis only) on A5EC065BB32AE6S.
# Quartus Pro 25.3 Docker + SW-AGILEX-5E fixed license (--net=host: FlexLM host-ID = NIC MAC).
# Usage (detached):  QPAR=4 nohup setsid ./run_syn_docker.sh > run.out 2>&1 &
set -uo pipefail
cd "$(dirname "$0")"
QPAR=${QPAR:-4}
# License: LIC_HOST=/path/to/SW-AGILEX-5E.dat (see ../../scripts/quartus_docker.sh).
# The committed caliptra2x_a5e.qsf is used as-is; REGEN_QSF=1 regenerates it with gen_qsf.py.
[ "${REGEN_QSF:-0}" = 1 ] && python3 gen_qsf.py
start=$(date +%s); echo "start $(date)"
DOCKER_NAME=q2x_syn ../../scripts/quartus_docker.sh "$PWD" "quartus_syn --parallel=$QPAR caliptra2x_a5e" > syn.log 2>&1
rc=$?
echo "rc=$rc wall_s=$(( $(date +%s)-start )) end $(date)"

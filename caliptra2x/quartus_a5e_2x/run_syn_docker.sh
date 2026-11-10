#!/bin/bash
# Caliptra 2.x core-only synthesis (analysis & synthesis only) on A5EC065BB32AE6S.
# Quartus Pro 25.3 Docker + SW-AGILEX-5E fixed license (--net=host: FlexLM host-ID = NIC MAC).
# Usage (detached):  QPAR=4 nohup setsid ./run_syn_docker.sh > run.out 2>&1 &
set -uo pipefail
export PATH=/workspace/docker-bin:$PATH
cd "$(dirname "$0")"
QPAR=${QPAR:-4}
LIC_HOST=${LIC_HOST:-/workspace/altera_license/SW-AGILEX-5E.dat}
python3 gen_qsf.py
start=$(date +%s); echo "start $(date)"
docker run --rm --name q2x_syn --net=host -u "$(id -u):$(id -g)" -e HOME=/tmp \
  -e LM_LICENSE_FILE=/licenses/SW-AGILEX-5E.dat -e ALTERA_LICENSE_FILE=/licenses/SW-AGILEX-5E.dat \
  -v /workspace:/workspace -v "$LIC_HOST":/licenses/SW-AGILEX-5E.dat:ro -w "$PWD" \
  alterafpga/quartuspro-v25.3:agilex5 bash -lc "quartus_syn --parallel=$QPAR caliptra2x_a5e" > syn.log 2>&1
rc=$?
echo "rc=$rc wall_s=$(( $(date +%s)-start )) end $(date)"

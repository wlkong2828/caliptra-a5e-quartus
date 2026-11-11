#!/bin/bash
# Build the Nios V app (Caliptra 2.x host; same flow as quartus_a5e_nios/sw/build_app.sh) on Linux/macOS without RiscFree: any rv32 GCC works.
# Default: xPack riscv-none-elf-gcc (https://github.com/xpack-dev-tools/riscv-none-elf-gcc-xpack)
# RISCV_BIN=<dir with riscv-none-elf-gcc>  ./build_app.sh
set -euo pipefail
cd "$(dirname "$0")"
RISCV_BIN=${RISCV_BIN:-/workspace/tools/xpack-riscv-none-elf-gcc-14.2.0-3/bin}
SHIM=$PWD/.shim; mkdir -p "$SHIM"
for t in gcc g++ ar objdump objcopy size nm ld as ranlib; do
  ln -sf "$RISCV_BIN/riscv-none-elf-$t" "$SHIM/riscv32-unknown-elf-$t"; done
export PATH=$SHIM:$PATH
# GCC >= 12 needs zicsr/zifencei spelled out (Intel RiscFree GCC is older)
sed -i "s/-march=rv32i -mabi/-march=rv32i_zicsr_zifencei -mabi/" bsp/toolchain.cmake
cmake -S app -B app/build -G "${CMAKE_GEN:-Ninja}" -DCMAKE_BUILD_TYPE=Release
cmake --build app/build -j --target caliptra_host.elf
riscv32-unknown-elf-size app/build/caliptra_host.elf
# RAM init image (Intel word-addressed HEX) -> ../onchip_mem.hex (project dir)
if [ "${NO_HEX:-0}" != 1 ]; then
  HEX_OK=0
  if [ "${SKIP_DOCKER:-0}" != 1 ] && command -v docker >/dev/null 2>&1 \
     && docker image inspect alterafpga/quartuspro-v25.3:agilex5 >/dev/null 2>&1; then
    if ../dock.sh 'QUARTUS_ROOTDIR=/opt/altera/quartus elf2hex sw/app/build/caliptra_host.elf -o onchip_mem.hex -b 0x00000000 -w 32 -e 0x0000FFFF -r 4'; then
      HEX_OK=1
    fi
  fi
  if [ "$HEX_OK" != 1 ]; then
    echo "Quartus elf2hex unavailable; using scripts/elf2hex_intel.py fallback"
    "$RISCV_BIN/riscv-none-elf-objcopy" -O binary app/build/caliptra_host.elf /tmp/caliptra2x_host.bin
    python3 ../../../scripts/elf2hex_intel.py /tmp/caliptra2x_host.bin -o ../onchip_mem.hex -b 0x00000000 -w 32 -e 0x0000FFFF -r 4
  fi
fi

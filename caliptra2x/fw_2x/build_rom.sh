#!/bin/bash
# Rebuild Caliptra ROM (with log) + test-key FW bundle for HW rev 2.1, then make $readmemh hex files.
set -e
source ~/.cargo/env
SW=${SW:?set SW=/path/to/caliptra-sw checked out at dd1e79d (tags rom-2.1.3-1, fw-2.1.4)}
OUT=$(cd "$(dirname "$0")" && pwd)
cd $SW
cargo run --release --manifest-path builder/Cargo.toml --bin image -- --hw-revision 2.1 \
  --rom-with-log $OUT/caliptra-rom.bin --fw $OUT/caliptra-fw-bundle.bin
cd $OUT && python3 - <<'PY'
import struct
r=open('caliptra-rom.bin','rb').read(); r+=b'\0'*((-len(r))%8)
open('caliptra-rom.hex','w').write('\n'.join('%016x'%struct.unpack_from('<Q',r,i)[0] for i in range(0,len(r),8))+'\n')
f=open('caliptra-fw-bundle.bin','rb').read(); f+=b'\0'*((-len(f))%4)
open('caliptra-fw-bundle.hex','w').write('\n'.join('%08x'%struct.unpack_from('<I',f,i)[0] for i in range(0,len(f),4))+'\n')
PY
sha256sum *.bin > SHA256SUMS

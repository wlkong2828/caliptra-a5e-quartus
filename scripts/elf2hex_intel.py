#!/usr/bin/env python3
"""Intel word-addressed HEX (Quartus elf2hex -w 32 -r 4 compatible) from a flat binary."""
import argparse, pathlib, struct

def rec(rlen, addr, rtype, data: bytes) -> str:
    payload = bytes([rlen, (addr >> 8) & 0xFF, addr & 0xFF, rtype]) + data
    csum = ((-sum(payload)) & 0xFF)
    return ":" + payload.hex().upper() + f"{csum:02X}"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bindata")
    ap.add_argument("-o", required=True)
    ap.add_argument("-b", dest="base", default="0", help="byte base (ignored; image starts at 0)")
    ap.add_argument("-e", dest="end", default="0xFFFF", help="last byte address inclusive")
    ap.add_argument("-w", dest="width", type=int, default=32)
    ap.add_argument("-r", dest="width_bytes", type=int, default=4)
    args = ap.parse_args()
    blob = pathlib.Path(args.bindata).read_bytes()
    end = int(args.end, 0)
    nwords = (end + 1) // args.width_bytes
    blob = blob + bytes(nwords * args.width_bytes - len(blob))
    lines = [rec(2, 0, 2, b"\x00\x00")]  # extended segment address 0
    for i in range(nwords):
        word = blob[i*4:(i+1)*4]
        # little-endian CPU image already; write bytes in file order
        lines.append(rec(4, i, 0, word))
    lines.append(":00000001FF")
    pathlib.Path(args.o).write_text("\n".join(lines) + "\n")

if __name__ == "__main__":
    main()

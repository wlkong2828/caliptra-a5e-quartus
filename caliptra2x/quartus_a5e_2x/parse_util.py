#!/usr/bin/env python3
"""Extract per-hierarchy ALUT/FF/BRAM/DSP from the synthesis 'Resource Utilization by Entity' table."""
import re, sys
rpt = sys.argv[1] if len(sys.argv) > 1 else "output_files/caliptra2x_a5e.syn.rpt"
maxd = int(sys.argv[2]) if len(sys.argv) > 2 else 3
lines = open(rpt).read().split("\n")
s = next(i for i, l in enumerate(lines) if 'Resource Utilization by Entity' in l and l.startswith('; Partition'))
rows = []
for l in lines[s+4:]:
    if l.startswith('+'): break
    c = [x for x in l.split(';')]
    node = c[1]; d = (len(node) - len(node.lstrip())) // 3
    num = lambda x: int(re.match(r'\s*(\d+)', x).group(1))
    rows.append((d, node.strip().strip('|'), num(c[2]), num(c[3]), num(c[4]), num(c[5]), c[9].strip()))
print(f"{'hierarchy':60s} {'ALUTs':>8s} {'FFs':>8s} {'BRAMbits':>9s} {'DSP':>4s}  entity")
for d, n, a, f, b, p, e in rows:
    if d <= maxd and (a > 1500 or b > 0 or p > 0 or d <= 1):
        print(f"{'  '*d + n:60s} {a:8d} {f:8d} {b:9d} {p:4d}  {e}")

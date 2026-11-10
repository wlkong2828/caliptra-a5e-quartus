# Caliptra 2.x + Nios glue — Simulation Guide

> **Where the files are (published copy).** This guide was written in the local Caliptra 2.x design tree. In this repo, the 2.x sources it names live under [`caliptra2x/`](../../caliptra2x/):
> - `rtl_2x/`, `sim_2x/`, `sim/rst_release_stub.sv`, `fw_2x/`, `scripts/gen_fuse_image_2x.py` and `quartus_a5e_2x/` → `caliptra2x/…`
> - `docs/P1_FIT_RESULT_2X_A5E.md` and `docs/CALIPTRA_2X_INTEGRATION_PLAN.md` → this folder
> - The 1.x guide `docs/NIOS_CALIPTRA_INTEGRATION.md` is [`../NIOS_CALIPTRA_INTEGRATION.md`](../NIOS_CALIPTRA_INTEGRATION.md)
>
> caliptra-rtl and caliptra-sw are not vendored.

- **Scope:** Verilator simulation of the **real** 2.x glue RTL (`rtl_2x/`) around caliptra-rtl v2.1.2 (`49370266`) core-only. It runs the real ROM `rom-2.1.3-1` and the real FW bundle `fw-2.1.4` (FMC + runtime), and boots from cold power-on to `ready_for_runtime`.
- **Result:** **PASS**: `TB_NIOS2X PASS cyc=36617987 trng=217 (prod, debug locked)`.
- **Related:** [NIOS_CALIPTRA_2X_INTEGRATION.md](NIOS_CALIPTRA_2X_INTEGRATION.md) (design), [FIRMWARE_AND_KEYS_2X.md](FIRMWARE_AND_KEYS_2X.md) (ROM, bundle, fuse image). The raw record is in `sim_2x/BOOT_NIOS2X.md` and `sim_2x/nios2x_top_fw_run.log`.

---

## 1. What is simulated

| Part | Real RTL or model |
|---|---|
| `nios_caliptra2x_top` (window decode, `soc_fw_store`, `soc_fuse_ctrl2x`, `avmm_to_axi`, AXI write mux, 2FF reset syncs, straps) | **Real** (`rtl_2x/`) |
| `caliptra_passive_top` + `caliptra_top` v2.1.2 (VeeR, soc_ifc, crypto, Adams-Bridge, memories) | **Real** (`/workspace/caliptra-rtl`, `rtl_2x/caliptra_passive_top.sv`) |
| Caliptra ROM / FMC / runtime | **Real** binaries: `fw_2x/caliptra-rom.hex`, `fw_2x/caliptra-fw-bundle.hex` |
| Fuse image | **Real** generator output: `fw_2x/fuse_image_2x.hex` |
| Agilex Reset Release IP | Stub `sim/rst_release_stub.sv` (`ninit_done` = 1 for 25 ns) |
| Platform Designer system `nios_caliptra2x_sys` (Nios V + PIOs + window) | **Behavioral model** in `tb_nios2x_top_fw.sv`, with the same port names. It issues the Avalon accesses the 2.x Nios firmware is meant to issue |

The Nios V CPU, Platform Designer interconnect and C firmware are **not** in this sim. Compare the 1.x sim, which also used a behavioral host.

---

## 2. Tools and inputs

| Item | Value |
|---|---|
| Simulator | **Verilator 5.054** (2026-11-01, conda-forge build), from `/workspace/mamba/envs/eda/bin` (override with `VERILATOR_BIN`) |
| Build flags (`run_nios2x_top_fw.sh`) | `--binary --threads ${THREADS:-4} -j 8 -O3 -Wno-fatal -Wno-lint -Wno-style -Wno-UNOPTFLAT -Wno-MULTIDRIVEN -Wno-TIMESCALEMOD --top-module tb_nios2x_top_fw -Mdir obj_nios2x -f boot2x.f -o Vtb_nios2x` |
| Caliptra RTL | `/workspace/caliptra-rtl` at v2.1.2 `49370266d12cb0c4a8f71b3a0ff7e54ba7d4866e`, with submodule `adams-bridge`. **Not in git**; clone it with `git clone --recursive --branch v2.1.2 https://github.com/chipsalliance/caliptra-rtl.git` |
| File list | `sim_2x/boot2x.f` (641 lines): `+incdir+` paths and 588 caliptra-rtl source files (absolute `/workspace/caliptra-rtl/...` paths), plus the repo files listed below |
| Repo sources in the file list | `sim_2x/patches/decompress_top.sv`, `rtl_2x/caliptra_veer_sram_export.sv`, `rtl_2x/caliptra_passive_top.sv`, `sim/rst_release_stub.sv`, `rtl_2x/reset_sync.sv`, `rtl_2x/avmm_to_axi.sv`, `rtl_2x/soc_fuse_ctrl2x.sv`, `rtl_2x/soc_fw_store.sv`, `rtl_2x/nios_caliptra2x_top.sv`, `sim_2x/tb_nios2x_top_fw.sv` |
| Verilator patch | `sim_2x/patches/decompress_top.sv` replaces the adams-bridge original. It changes one line: `` `ifdef VERILATOR `` becomes `` `ifdef CLP_OLD_VERILATOR_WORKAROUND `` around the `abr_piso_multi` rate arrays, so Verilator 5.054 uses the normal 4-entry `INPUT_RATES`/`OUTPUT_RATES` instead of the old 5-entry workaround |
| Data files (via RTL parameter defaults, relative to `sim_2x/`) | `../fw_2x/caliptra-rom.hex`, `../fw_2x/caliptra-fw-bundle.hex`, `../fw_2x/fuse_image_2x.hex` |

In the published copy (`caliptra2x/sim_2x/boot2x.f`), the repo files are already relative (`../rtl_2x/…`, which resolve because the run script `cd`s into `sim_2x/`); only the caliptra-rtl paths are absolute. To use a different checkout location, rewrite the absolute paths in `boot2x.f`, for example: `sed -i 's#/workspace/caliptra-rtl#/path/to/caliptra-rtl#g; s#/workspace/exports/caliptra-a5e-2x-quartus-repo#/path/to/repo#g' boot2x.f`.

---

## 3. Build and run

**Run long sims detached.** A full boot takes about 1.4 h of wall time, and a foreground shell or agent session can be interrupted.

```bash
cd sim_2x
# build (~6 min) + run, detached; output in nios2x_top_fw_run.log, wrapper output in run.out
nohup setsid ./run_nios2x_top_fw.sh +test=all > run.out 2>&1 &

# re-run without rebuilding
BUILD=0 nohup setsid ./run_nios2x_top_fw.sh +test=all > run.out 2>&1 &

# watch progress
tail -f nios2x_top_fw_run.log          # LOG lines, TRNG services, heartbeats, milestones
grep -E 'MILESTONE|PASS|FAIL|TIMEOUT' nios2x_top_fw_run.log
```

| Env var | Default | Meaning |
|---|---|---|
| `BUILD` | `1` | `0` skips the Verilator build |
| `THREADS` | `4` | Verilator `--threads` |
| `VERILATOR_BIN` | `/workspace/mamba/envs/eda/bin` | Prepended to `PATH` |

- The script runs the binary under `stdbuf -oL -eL`, so the log is line-buffered and `tail -f` works. When the run ends, it appends `wall_time_s=<s> end <date>`.
- **Measured costs** on this box:
  - Build: Verilator walltime **358 s** (elab 4.9 s, convert 204.8 s, C++ build 143.9 s); 2,185 MB allocated; 134 C++ files.
  - Run: **5,069 s wall (1 h 24 m 29 s)** in the wrapper. Verilator reported walltime 4,452.7 s, cpu 17,793.6 s on 4 threads, 18 MB allocated, about 82 µs of sim time per wall second.

### 3.1 Plusargs

| Plusarg | Default | Effect |
|---|---|---|
| `+test=axiuser` | — | Cold release, `ready_for_fuses`, AxUSER programming, then the AxUSER checks (§4.1), then `$finish`. Takes a few hundred cycles |
| `+test=prod` | — | Cold boot to `ready_for_runtime` **without** the AxUSER checks |
| `+test=all` | **default** | AxUSER checks, then the prod cold boot. **Not** a multi-boot suite: there is no warm or fatal second boot, unlike 1.x `+test=all` |
| `+max_cycles=N` | 300,000,000 | Prints `TB_NIOS2X TIMEOUT magic=… trng=…` and stops |
| `+hb=N` | 1,000,000 | Heartbeat line period: `[cyc] heartbeat status=<pio[7:0]> trng=<n>` |

The TB clock is 100 MHz (`always #5`), so 1 cycle = 10 ns of sim time. `$finish` at 366 ms equals 36.6 M cycles.

---

## 4. What the testbench checks

### 4.1 AxUSER test (`test_axiuser`, run by `axiuser` and `all`)

This runs after the host programs and locks the AxUSERs (fuse = 2, TRNG = 1, mailbox[0] = 1). The TB `force`s `dut.nios_axi_user` and reads the bridge's `err_q` (SLVERR).

| Access | AxUSER | Expected | Result (log) |
|---|---|---|---|
| Write `MBOX_LOCK` | 3 | SLVERR | `[115] MBOX write AxUSER=3 -> SLVERR OK` |
| Write `FUSE_UDS_SEED[0]` | 3 | SLVERR | `[121] fuse write AxUSER=3 -> SLVERR OK` |
| Write `FUSE_UDS_SEED[0]` | 1 (Nios) | SLVERR (only user 2 may touch fuses) | `[127] … SLVERR OK` |
| Read `CPTRA_HW_REV_ID` | 1 | Accepted | `[132] AxUSER=1 HW_REV_ID=00000212 accepted OK` → `TB_AXIUSER PASS` |

### 4.2 Boot checks (`prod`, `all`)

| Check | FAIL message if it fails |
|---|---|
| `generic_input_wires === 0` | `TB_NIOS2X FAIL generic_input_wires` |
| Fuse ctrl ID = `0x46555345` | `FAIL fuse id` |
| Fuse ctrl ends DONE, not ERR | `FAIL fuse ctrl ERR (SLVERR on a fuse write?)` |
| Fuse ctrl `COUNT == 118` (104 fuse + 13 owner hash/lock + WR_DONE) | `FAIL expected COUNT=118 …` |
| `CPTRA_FUSE_WR_DONE[0] == 1` | `FAIL FUSE_WR_DONE not set` |
| `CPTRA_OWNER_PK_HASH_LOCK[0] == 1` | `FAIL owner PK hash not locked` |
| `MBOX_USER == 1` after the lock is acquired | `FAIL MBOX_USER` |
| `MBOX_STATUS == 2` (CMD_COMPLETE) after FIRMWARE_LOAD | `FAIL mbox status` (plus a register dump) |
| No `cptra_error_fatal` at any time | `FAIL unexpected cptra_error_fatal` (plus a dump) |
| `etrng_req` drops within 100,000 cycles after each `DATA_WR_DONE` | `FAIL etrng_req stuck …` |
| `ready_for_runtime` before `max_cycles` | `TIMEOUT` |

The TB also **prints, without checking**: `HW_REV_ID`, `HW_CONFIG`, `CPTRA_SECURITY_STATE`, `FUSE_PQC_KEY_TYPE` readback, `CPTRA_OWNER_PK_HASH[0]`, and a final dump of BOOT/FLOW status and all four error registers.

**PASS criteria:** every check above holds, `ready_for_runtime` is reached, and then 20,000 more cycles run with no fatal error. The TB prints `SUMMARY …` and `TB_NIOS2X PASS cyc=<n> trng=<n> (prod, debug locked)`.

### 4.3 The `FUSE_PQC_KEY_TYPE readback=00000000` quirk

- The image writes `FUSE_PQC_KEY_TYPE = 1` at `0x3038C` (line 91 of the 117-line image, written by the fuse ctrl with AxUSER 2). The TB reads it back **as the Nios (AxUSER 1)** and gets `00000000`.
- **Cause:** in caliptra-rtl `soc_ifc_arb.sv`, `soc_reg_req` for addresses in `SOC_IFC_FUSE_START_ADDR..SOC_IFC_FUSE_END_ADDR` (`0x30200–0x305FF`) requires `valid_fuse_user`. After `CPTRA_FUSE_AXI_USER_LOCK` = 1, that means AxUSER == 2. The Nios read therefore never reaches the register block, and the read data is 0.
- This is the same gate that gives the SLVERR in §4.1. The TB does not check the bridge error flag on this read, so whether that read also returned SLVERR was not recorded.
- **Proof the fuse was effective:** in Production lifecycle, the ROM compares the manifest PQC type with this fuse and would fail with `IMAGE_VERIFIER_ERR_PQC_KEY_TYPE_MISMATCH`. Instead it logged `[fwproc] Img verified ecc=0 MLDSA=0 svn=0 fuse_svn=0` at cycle 17,010,257.
- By contrast, `CPTRA_OWNER_PK_HASH*` (`0x30140`/`0x30170`) and `CPTRA_FUSE_WR_DONE` (`0x300B0`) are outside the fuse range, so the Nios read them back correctly.
- To read the fuse values back for debugging, issue the reads with AxUSER 2 (for example, add a read path to `soc_fuse_ctrl2x`) or before `CPTRA_FUSE_AXI_USER_LOCK` is set.

### 4.4 Log channel

- The ROM, FMC and runtime print through `generic_output_wires[7:0]`, with bit 8 toggling per character.
- The TB top assembles lines and prints them as `[cycle] LOG <text>`.
- It records the first `[fmc` / `[alias rt` line as `rom_to_fmc` and the first `[rt]` line as `fmc_to_rt`.

---

## 5. Measured results (`+test=all`, PID 227528, 2026-11-10)

Environment:
- Start 13:53:45 CST, end 15:18:14 CST.
- `HW_REV_ID = 00000212`.
- `HW_CONFIG = 00000010` (`iTRNG_en=0`, `SUBSYSTEM_MODE_en=0`).
- `CPTRA_SECURITY_STATE = 00000007` (lifecycle 3 = Production, debug_locked = 1).

| Cycle | Event (from `nios2x_top_fw_run.log`) |
|---:|---|
| 40 | `MILESTONE ready_for_fuses` |
| 132 | `TB_AXIUSER PASS` |
| 136 | `FUSE_CTRL NUM_FUSES=117` (START follows) |
| 614 | `FUSE_CTRL STATUS=00000002 COUNT=118` |
| 619 | `FUSE_WR_DONE=00000001`; `FUSE_PQC_KEY_TYPE readback=00000000` (§4.3); `OWNER_PK_HASH_LOCK=00000001`; `OWNER_PK_HASH[0]=48afdb07` |
| 634 | `MILESTONE fuses done via soc_fuse_ctrl2x (COUNT=118)` |
| 378,838 | `Running Caliptra ROM ...` |
| 379,157 | First TRNG request serviced |
| 384,577 | `[state] Starting the WD Timer 100000000 cycles` |
| 442,177 / 445,304 | `LifecycleState = Production` / `DebugLocked = Yes` |
| 794,349 | `ROM Digest: AB0AEDDBE4F660DC3CDB6F3221DCE2ADA1F6D0593A403B0B12D9EB5CC5C632EB` |
| 5,524,388 | `[kat] --` (ROM KATs done) |
| 5,542,288 | `MILESTONE ready_for_mb_processing trng=21` |
| 6,049,774 | `MILESTONE FIRMWARE_LOAD issued, 253440 bytes from soc_fw_store` |
| 14,288,568 | `[fwproc] Recv command 0x46574c44` |
| 17,010,257 | `[fwproc] Img verified ecc=0 MLDSA=0 svn=0 fuse_svn=0` |
| 17,085,903 | `Load FMC at address 0x40000000 len 30760` |
| 17,304,364 | `Load Runtime at address 0x40008000 len 205516` |
| 21,319,080 | `MILESTONE MBOX_STATUS=2 (2=CMD_COMPLETE)` |
| 27,820,645 | `[exit] Launching FMC @ 0x40000000` |
| 27,875,426 | `Running Caliptra FMC ...` |
| 30,035,513 | First FMC log line (ROM → FMC) |
| 36,003,133 | `Caliptra RT` (RT KATs incl. MLKEM1024 follow) |
| 36,217,560 | First RT log line `[rt] OCP LOCK Unsupported` (FMC → RT) |
| 36,596,602 | `[rt] Disable entropy source` |
| 36,597,923 | `[rt] RT listening for mailbox commands...` |
| **36,597,957** | **`MILESTONE ready_for_runtime`** |
| 36,617,987 | `TB_NIOS2X PASS cyc=36617987 trng=217 (prod, debug locked)` |

**Summary line:** `SUMMARY ready_for_fuses=40 fuses_done=614 first_trng=379157 ready_for_mb_processing=5542288 fw_load_issued=6049774 mbox_complete=21319080 rom_to_fmc=30035513 fmc_to_rt=36217560 ready_for_runtime=36597957 trng_fills=217 fuse_writes=118`

**Final dump:** `CPTRA_BOOT_STATUS=00000000`, `CPTRA_FLOW_STATUS=b8000000`, `HW_ERROR_FATAL = FW_ERROR_FATAL = HW_ERROR_NON_FATAL = FW_ERROR_NON_FATAL = 00000000`.

**Not covered by this run:** warm reset (START_DONE), fatal-error pwrgood recovery, mailbox commands after runtime, the real Nios V / PD interconnect, and the A5E Reset Release IP model.

---

## 6. Waveforms

**The 2.x TB does not dump waveforms as built.** `boot2x.f` / `run_nios2x_top_fw.sh` do not pass `--trace`/`--trace-fst` (the build log shows `-DVM_TRACE=0 -DVM_TRACE_FST=0`), and `tb_nios2x_top_fw.sv` has no `$dumpfile`/`$dumpvars`.

To get waves (untested for 2.x; a full 36.6 M-cycle dump of the whole design would be very large and much slower):

1. Add `--trace-fst --trace-structs` (optionally `--trace-depth 3`) to the `verilator` line in `run_nios2x_top_fw.sh`.
2. In `module tb_nios2x_top_fw`, add a windowed dump so only the interesting part is recorded, for example around the fuse push:
   ```systemverilog
   initial begin
     $dumpfile("nios2x.fst");
     $dumpvars(2, tb_nios2x_top_fw.dut);   // glue level; raise depth for Caliptra internals
     #20us $dumpoff;                         // fuses + start of ROM; move/extend as needed
   end
   ```
3. Rebuild (`BUILD=1`) and run with a smaller `+max_cycles` if you only need the beginning.
4. View with GTKWave: `gtkwave sim_2x/nios2x.fst`. Useful signals:
   - `dut.status_in[7:0]`, `dut.ctrl_out[2:0]`, `dut.cptra_pwrgood`, `dut.cptra_rst_b`
   - `dut.fuse_busy`, `dut.u_fuse_ctrl.st`, `dut.u_fuse_ctrl.idx`
   - `dut.awaddr`, `dut.awuser`, `dut.awvalid`/`awready`, `dut.bresp`, `dut.u_bridge.st`, `dut.u_bridge.err_q`
   - `dut.etrng_req`, `dut.generic_output_wires[8:0]`

The 1.x project's waveform flow (FST + GTKWave screenshots) is in the 1.x repo history; this guide makes no claim that it has been redone for 2.x.

---

## 7. Troubleshooting

| Symptom | Likely cause |
|---|---|
| `FAIL fuse ctrl ERR` / `COUNT` < 118 | A fuse write got SLVERR: fuse AxUSER not programmed/locked to 2 before START, or a bad address in the image |
| `FAIL etrng_req stuck` | TRNG AxUSER not 1/locked, or `DATA_WR_DONE` (2) not written |
| ROM fatal around image verification | Fuse image doesn't match the bundle: regenerate with `scripts/gen_fuse_image_2x.py` after every bundle rebuild ([FIRMWARE_AND_KEYS_2X.md §5](FIRMWARE_AND_KEYS_2X.md)) |
| Mailbox command rejected / `0x01020009` | Mailbox used with the reserved AxUSER `0xFFFFFFFF` or an unlocked user (see the integration plan) |
| `TIMEOUT` with no progress | Check heartbeats (`status=` bits) and `trng=` count; the run is long (≈ 36.6 M cycles) |

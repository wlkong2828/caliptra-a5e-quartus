# nios_caliptra2x_top — Caliptra 2.x passive boot (Verilator)

Production-lifecycle **mimic** using STUDY UDS / field entropy and the
caliptra-sw test-signed firmware bundle (not real production secrets).
Behavioral Nios mailbox host; real 2.x glue (`soc_fuse_ctrl2x`, `avmm_to_axi`,
2FF reset syncs) plus Caliptra 2.x core-only RTL.

## Command and versions

Detached run (do not rebuild if `obj_nios2x/Vtb_nios2x` is already current):

```bash
cd sim_2x
# Usage noted in run_nios2x_top_fw.sh:
#   nohup setsid ./run_nios2x_top_fw.sh +test=all > run.out 2>&1 &
# env BUILD=0 skips the Verilator rebuild. Log: nios2x_top_fw_run.log
```

This result is from PID 227528, `./obj_nios2x/Vtb_nios2x +test=all`
(default `max_cycles=300000000`), launched by `sim_2x/run_nios2x_top_fw.sh`.
TB clock is 100 MHz (`#5` half-period). Log: `sim_2x/nios2x_top_fw_run.log`.

| Item | Value |
|---|---|
| Caliptra RTL | v2.1.2 (`49370266`) |
| ROM | rom-2.1.3-1 (`dd1e79d`, `--hw-revision 2.1`) |
| Firmware bundle | fw-2.1.4, same commit; `fw_2x/caliptra-fw-bundle.bin` 253,440 B, SHA-256 `361bdf44…24f2` |
| ROM image | `fw_2x/caliptra-rom.bin` 96 KiB, SHA-256 `26d505a7…cef2` |
| Verilator | 5.054 (2026-11-01), `--threads 4` |
| HW_REV_ID | `00000212` (2.1.2) |
| HW_CONFIG | `00000010` (`iTRNG_en=0`, `SUBSYSTEM_MODE_en=0`) — external ETRNG, core-only passive |
| Straps | lifecycle = 3 (Production), `debug_locked=1` (`CPTRA_SECURITY_STATE=00000007`) |

In this 2.x testbench, `+test=all` is the AxUSER access check plus one cold
boot through `ready_for_runtime`. It does **not** include a second boot
(warm or fatal), unlike the 1.x `+test=all` suite.

## Fuse image

`fw_2x/fuse_image_2x.hex` from `scripts/gen_fuse_image_2x.py` (117 image
entries). `soc_fuse_ctrl2x` replays them over AXI with AxUSER 2 (fuse
controller) after `ready_for_fuses`, then writes `FUSE_WR_DONE` (118 AXI
writes total, `FUSE_CTRL STATUS=00000002 COUNT=118`).

- **STUDY UDS seed** (512-bit, `FUSE_UDS_SEED[0..15]`, not a real secret):
  `811944f5 2340ce3e c5885067 67f3dba8 083b5dd1 aa62e71a 4caa6943 ee95f084`
  `90dd7acd 3104fc76 d34c07bf 75b789e0 17ff1329 b8269552 5a6e1c9b fc59a6dc`
- **STUDY field entropy** (256-bit, `FUSE_FIELD_ENTROPY[0..7]`):
  `22282f72 ac1471cf 3600ba58 b06cccb5 3a59110e 84455b9b 0eb16df4 889db641`
- **FUSE_VENDOR_PK_HASH** = SHA-384 of the bundle preamble vendor key
  descriptors (12 big-endian words):
  `30399676 a17e3e97 3677b3ff 862f4bf2 d1932d88 4778453c 376fe00d c93fb8aa`
  `0770f3eb f3411a08 53e9c57e ce8a2980`
- **CPTRA_OWNER_PK_HASH** = SHA-384 of the bundle `owner_pub_keys` block
  (ECC P-384 + ML-DSA-87, 12 big-endian words), then
  **CPTRA_OWNER_PK_HASH_LOCK = 1** (pwrgood-domain register, not a 2.x fuse):
  `48afdb07 3c5e0d4e e4649046 8ef81f2c f57249b6 e76a28f5 fca4de69 6a7d3e2e`
  `d3efc4e6 77431854 3e95307a 54988bd7`
- **FUSE_PQC_KEY_TYPE = 1** (ML-DSA) is written in the image at `0x3038C`.
  TB readback of `FUSE_PQC_KEY_TYPE` showed `00000000`, but the ROM verified
  the ML-DSA image (`Img verified ecc=0 MLDSA=0 svn=0 fuse_svn=0`), so the
  fuse was effective.
- TB also read back `CPTRA_OWNER_PK_HASH_LOCK=00000001` and
  `CPTRA_OWNER_PK_HASH[0]=48afdb07`.
- Other programmed values: SVN / revocation / anti-rollback fuses = 0
  (bundle FW SVN = 0), `FUSE_SOC_STEPPING_ID=1`. Unused 2.x fields
  (manuf debug unlock token, SoC manifest SVNs, HEK seed, IDevID attrs)
  are 0.

## TRNG

External ETRNG is serviced the same way as the 1.x project: the Nios host
model fills 12 words of `CPTRA_TRNG_DATA` and writes `STATUS=2` on each
`etrng_req`. **217 TRNG requests** were serviced (first fill at cycle
379,157; last before `ready_for_runtime`).

## Cycle-stamped milestones

| Cycle | Event |
|---:|---|
| 40 | `ready_for_fuses` |
| 132 | `TB_AXIUSER PASS` (wrong AxUSER writes rejected; Nios user 1 accepted on `HW_REV_ID`) |
| 614 / 619 | Fuse controller `COUNT=118`, `FUSE_WR_DONE=1` |
| 634 | Milestone: fuses done via `soc_fuse_ctrl2x` |
| 378,838 | `Running Caliptra ROM ...` |
| 379,157 | First TRNG fill |
| 442,177 / 445,304 | ROM: `LifecycleState = Production`, `DebugLocked = Yes` |
| 794,349 | ROM digest `AB0AEDDB…C632EB` |
| 5,524,388 | ROM KATs complete (`[kat] --`) |
| 5,542,288 | `ready_for_mb_processing` (trng=21) |
| 6,049,774 | `FIRMWARE_LOAD` issued, 253,440 bytes from `soc_fw_store` |
| 14,288,568 | ROM `[fwproc] Recv command 0x46574c44` |
| 17,010,257 | `Img verified ecc=0 MLDSA=0 svn=0 fuse_svn=0` |
| 17,085,903 | Load FMC at `0x40000000` len 30,760 |
| 17,304,364 | Load Runtime at `0x40008000` len 205,516 |
| 21,319,080 | `MBOX_STATUS=2` (`CMD_COMPLETE`) |
| 27,820,645 | `Launching FMC @ 0x40000000` |
| 27,875,426 | `Running Caliptra FMC ...` |
| 30,035,513 | First FMC log line (ROM → FMC handoff) |
| 36,003,133 | `Caliptra RT`; RT KATs (AES-ECB/CBC/CTR/CMAC, MLKEM1024) |
| 36,217,560 | First RT log line (FMC → RT handoff); `[rt] OCP LOCK Unsupported` |
| 36,596,602 / 36,597,923 | `[rt] Disable entropy source` / `RT listening for mailbox commands...` |
| **36,597,957** | **`ready_for_runtime`** |
| 36,617,987 | `TB_NIOS2X PASS` after magic `0xCA11F00D` and 20,000 extra cycles |

At `ready_for_runtime` the TB dumped `CPTRA_FLOW_STATUS=b8000000`,
`CPTRA_BOOT_STATUS=00000000`, and all HW/FW fatal and non-fatal error
registers = 0.

## Result

**PASS.** `TB_NIOS2X PASS cyc=36617987 trng=217 (prod, debug locked)`.

- Wrapper wall time: **5069 s** (1 h 24 m 29 s), start
  Tue Nov 10 13:53:45 CST, end Tue Nov 10 15:18:14 CST (America/Chicago).
- Verilator reported walltime 4452.674 s, `$finish` at 366 ms of TB time,
  cpu 17793.551 s on 4 threads, 18 MB allocated.

The full PD Nios V + interconnect is not in this sim; the TB's behavioral
host issues the same class of accesses as the 2.x Nios glue is meant to
perform (fuse start, mailbox `FIRMWARE_LOAD`, TRNG service, AxUSER).

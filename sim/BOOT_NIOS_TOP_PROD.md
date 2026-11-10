# nios_caliptra_top — DEVICE_PRODUCTION (debug locked) boot, Verilator

Production-flow **mimic** using STUDY keys/entropy (not real production secrets).

- Straps: lifecycle `2'b11` (Production), `debug_locked=1`, STUDY `cptra_obf_key`.
- Fuses: `fw/fuse_image.hex` from `scripts/gen_fuse_image.py`: LIFE_CYCLE=3,
  KEY_MANIFEST_PK_HASH / OWNER_PK_HASH = SHA-384 of the bundle's vendor/owner pub-key
  descriptors (12 BE words), PK_HASH_MASK=0, SVN fuses 0 (bundle FMC/RT SVN = 0), STUDY UDS/FE.
- SoC host programs, after `ready_for_fuses`:
  - fuse / TRNG / mailbox PAUSER valid+lock = 1 (Nios APB user ID)
  - `CPTRA_TIMER_CONFIG` (0x300B4) = 20000 (50 MHz period in ps)
  - `CPTRA_WDT_CFG` (0x30110/0x30114) = 100,000,000 (debug-locked ROM arms WDT1; 0 means a 1-cycle timeout)
- Glue: 2FF async-assert / sync-deassert on `cptra_pwrgood` and `cptra_rst_b`;
  `generic_input_wires` tied 0; `soc_fuse_ctrl` CTRL bit 2 = START_DONE (warm-reset path).

Run (needs `caliptra-rtl/` at the repo root and Verilator ≥ 5.0):

```bash
./run_nios_top_fw.sh                          # default +test=all +max_cycles=200000000
./run_nios_top_fw.sh +test=prod               # cold boot through ready_for_runtime only
./run_nios_top_fw.sh +test=sync               # 2FF synchronizer behavior
./run_nios_top_fw.sh +test=pauser             # wrong-user write → PSLVERR
./run_nios_top_fw.sh +test=warm               # prod + warm reset (rst_b only) + START_DONE
./run_nios_top_fw.sh +test=fatal              # prod + forced fatal + pwrgood recovery
```

Results (revision 3; launched 2026-11-10 10:17 CST, Verilator 5.054, 100 MHz TB clock; all `exit=0`):

| Test | Result | Key cycles | Wall | Log |
|---|---|---|---|---|
| `+test=sync` | **PASS** — pwrgood async assert / sync deassert after 2 clocks; rst_b sync deassert after 2 clocks / async assert | 305 ns | <1 s | `nios_top_fw_sync.log` |
| `+test=pauser` | **PASS** — mailbox and fuse writes with PAUSER=2 → PSLVERR; PAUSER=1 accepted | ~1 µs | <1 s | `nios_top_fw_pauser.log` |
| `+test=prod` | **PASS** — fuses (84 words) at 355; `ready_for_fw_push` 3,449,128; FIRMWARE_LOAD 109,000 B; `MBOX_STATUS=2` 14,362,328; `ready_for_runtime` **24,064,900**; 32 TRNG fills | 24,064,900 | 2,668 s | `nios_top_fw_prod.log` |
| `+test=warm` | **PASS** — rst_b-only reset; warm `ready_for_fuses` 31 cycles later; START_DONE COUNT=1; `ready_for_runtime` again **32,845,182** with no FIRMWARE_LOAD; 49 TRNG fills total | 32,845,182 | 3,550 s | `nios_top_fw_warm.log` |
| `+test=fatal` | **PASS** — forced `cptra_error_fatal` at 24,064,904; pwrgood cycle; `ready_for_fuses` 24,064,956; full fuse push COUNT=84 + `FUSE_WR_DONE=1` at **24,065,266** | 24,065,266 | 2,682 s | `nios_top_fw_fatal.log` |
| `+test=all` | **PASS** — sync → pauser → prod (24,064,936) → warm (32,845,218) → fatal (32,845,584) | 32,845,584 | 3,542 s | `nios_top_fw_all.log` |

Notes:
- The fatal test forces the `cptra_error_fatal` pin (it does not create an internal Caliptra fatal) and stops after the full fuse push; the rest of the re-boot is the prod path.
- prod/warm/fatal logs come from a TB build that also printed a trailing `TB_ALL PASS` line in single-test runs; the TB now prints it only for `+test=all` (sync/pauser re-run with that build). Results are unchanged.
- Prior production-only result (2026-11-03, pre-rev-3 glue): PASS at cycle 24,064,873 after 32 TRNG fills.
- Full PD Nios V + interconnect is not simulated; this TB uses a behavioral Nios host that issues the same accesses as `quartus_a5e_nios/sw/app/main.c`.

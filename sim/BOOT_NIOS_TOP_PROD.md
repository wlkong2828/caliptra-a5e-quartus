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

Standalone results (2026-11-10, America/Chicago):

| Test | Result | Log |
|---|---|---|
| `+test=sync` | **PASS** (pwrgood async assert / 2-cycle sync deassert; rst_b 2-cycle sync deassert / async assert) | `nios_top_fw_sync.log` |
| `+test=pauser` | **PASS** (MBOX and fuse writes with PAUSER=2 → PSLVERR; PAUSER=1 accepted) | `nios_top_fw_pauser.log` |
| `+test=all` (sync + pauser + prod + warm + fatal) | *see `nios_top_fw_all.log` / `nios_top_fw_run.log` after the full run* | `nios_top_fw_all.log` |

Prior production-only result (2026-11-03, pre-rev-3 glue): **PASS** at cycle 24,064,873 after 32 TRNG fills; `MBOX_STATUS=2`; wall ~2103 s. Full PD Nios V + interconnect is not simulated; this TB uses a behavioral Nios host.

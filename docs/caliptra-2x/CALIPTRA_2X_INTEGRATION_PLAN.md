# Caliptra 2.x passive (core-only) + Nios V on Agilex 5E A5E065: integration delta and plan

Status: **plan only**. No RTL, firmware, or Platform Designer changes yet. This repo is a copy of
`caliptra-a5e-quartus` at `02e5cd6` (Caliptra 1.x v1.1, rev 3 integration, all Verilator tests PASS,
synthesis 138,715 / 222,400 ALMs). Date: 2026-11-10.

## 0. Baseline versions and sources

| Item | Version used | Commit | Notes |
|---|---|---|---|
| caliptra-rtl (2.x target) | **v2.1.2** (latest release tag; tags after it: none) | `49370266d12cb0c4a8f71b3a0ff7e54ba7d4866e` (2026-03-19) | Local checkout `/workspace/caliptra-rtl`. `main` is post-2.1 dev. adams-bridge submodule `b77e3d8` (pinned by v2.1.2). |
| caliptra-sw ROM | **rom-2.1.3-1** (latest `rom-*` tag) | `dd1e79d5bf55a9bd5bdb05915757eaf34844145d` (same commit as `fw-2.1.4`) | Local checkout `/workspace/caliptra-sw-rom`; built with `--hw-revision 2.1`. |
| caliptra-sw FW (FMC+RT) | fw-2.1.4 built from the same commit; **fw-2.1.5** is the newest tag | — | Decide whether to rebuild RT from fw-2.1.5 (open question Q7). |
| caliptra-rtl (1.x baseline) | v1.1 | `5f85fb4` | Unchanged copy of the 1.x design is the starting point of this repo. |

Spec documents read (all at the v2.1.2 tag unless stated):
- `docs/CaliptraIntegrationSpecification.md` (v2.1.2) — "IS" below. Section names are cited as IS §name / Table N.
- `docs/CaliptraHardwareSpecification.md` (v2.1.2) — "HS".
- adams-bridge `docs/AdamsBridgeHardwareSpecification.md`, `AdamsBridge_MLDSA.md` — "ABR".
- caliptra-sw `rom/dev/README.md` "Caliptra - ROM Specification v2.1" — "ROM".
- RTL register sources: `src/soc_ifc/rtl/soc_ifc_external_reg.rdl`, `soc_ifc_fuse_reg.rdl`, `soc_ifc_subsystem_reg.rdl`,
  generated `caliptra_top_reg/caliptra_top_reg.h`; `src/integration/rtl/caliptra_top.sv`, `config_defines.svh`, `soc_ifc_pkg.sv`.

Existing 2.x work reused (copied unchanged to `ref/agilex7-2x-phaseA/`, see its README):
2.x core-only wrapper for Agilex 7, Verilator lint and smoke test, ROM/FW build script, and an AXI-BFM boot TB
whose run reached `ready_for_mb_processing` (5.54 M cycles, all ROM KATs incl. MLDSA87/LMS/AES/SHAKE pass)
but then got SLVERR on every mailbox access (AxUSER not a valid mailbox user, §1 row "Bus/AXI user").
**A 2.x passive boot to `ready_for_runtime` has not been demonstrated yet.**

Check run in this repo: Verilator 5.054 `--lint-only` of the 2.x core-only top (`ref/agilex7-2x-phaseA`)
against v2.1.2: **0 errors, 0 warnings** (lint/style classes suppressed), 766 modules, 70 s
(`sim/2x_ref/lint_v2.1.2_core_passive.log`). The port list in §1 is taken from `caliptra_top.sv` at v2.1.2.

## 1. Does "passive mode" still exist in 2.x? — Yes

- 2.x has two integration modes chosen at build time: **Subsystem mode** (`CALIPTRA_MODE_SUBSYSTEM` defined; Caliptra
  core + MCU + I3C recovery + fuse controller + lifecycle controller, from caliptra-ss) and **passive / core-only**
  (define absent, the repo default) (IS Table 3 Integration Defines; `soc_ifc_pkg.sv` line 39).
- The IS uses the term "Passive mode" explicitly, e.g. every `strap_ss_*`, `ss_debug_intent`, `cptra_obf_uds_seed*`,
  `cptra_obf_field_entropy*` row: *"Used in Subsystem mode only. In Passive mode, integrators shall tie this input to 0"*
  (IS Table 11, Table 12). Mailbox is *"256 KiB when in passive mode and 16 KiB when in subsystem mode"* (IS §Mailbox).
  The DMA assist block *"is not available"* in passive mode and its AXI manager *"must be tied to 0"* (IS §DMA Assist Engine, §AXI Arbitration).
- ROM: in passive mode the SoC loads firmware with mailbox command `FIRMWARE_LOAD` (0x46574C44); in subsystem mode the
  same command fails with `FW_PROC_MAILBOX_FW_LOAD_CMD_IN_SUBSYSTEM_MODE` and firmware comes over the recovery interface
  (`rom/dev/src/flow/cold_reset/fw_processor/mod.rs`, `process_mailbox_commands`). FW reads mode from `CPTRA_HW_CONFIG.SUBSYSTEM_MODE_en`.
- So the 1.x model (SoC host pushes fuses, then loads the FW bundle through the mailbox) carries over unchanged in concept.
  What changes is the bus, the fuse map, the bundle format, the memories, and above all the size.

## 2. Interface delta 1.x (v1.1) → 2.x (v2.1.2) and what changes in this design

Legend for "Our change": **R** = RTL glue (`quartus_a5e_nios/rtl/*`, `rtl/caliptra_passive_top.sv`), **PD** = Platform
Designer, **FW** = Nios `sw/app/main.c`, **SIM** = Verilator TB, **TOOL** = fuse image / bundle / ROM scripts.

| # | Interface | 1.x v1.1 (current design) | 2.x v2.1.2 core-only | Our change |
|---|---|---|---|---|
| 1 | SoC bus | APB subordinate, 18-bit `PADDR`, 32-bit data, `PAUSER[31:0]` | **AXI4 subordinate** (HS §Key Caliptra Core 2.0 Changes; IS Table 5). AW = 19 bits (`CALIPTRA_SLAVE_ADDR_WIDTH(SOC_IFC)`, 0x0_0000–0x7_FFFF), DW 32, IW 8, UW 32 (`config_defines.svh`). Single outstanding transaction, in-order, AxLOCK=0, no narrow access to mbox_datain/dataout/TRNG_DATA, bursts only FIXED to datain/dataout, AxCACHE/PROT/REGION/QOS ignored (IS §Unsupported features). Undefined address / invalid user → SLVERR. | **R**: replace `avmm_to_apb.sv` with a new `avmm_to_axi.sv` (single-beat, AxLEN=0, AxSIZE=2, AxBURST=INCR, WSTRB=0xF, AxUSER from a per-agent constant, maps BRESP/RRESP≠0 to Avalon `response`). Keeps the PD system unchanged (still an exported Avalon `mm_bridge`). **PD**: window must grow to cover 19-bit Caliptra space; move `soc_fw_store`/`soc_fuse_ctrl` out of 0x0_0000–0x1_FFFF overlap (see #16). Alternative: PD "AXI Bridge" export with 32-bit user — rejected for now because Nios V/m's AXI4-Lite manager carries no AxUSER and we'd still need glue to drive it. |
| 2 | Requester ID | `PAUSER`; regs `CPTRA_MBOX_VALID_PAUSER[5]`/`_LOCK`, `CPTRA_TRNG_VALID_PAUSER`/`_LOCK`, `CPTRA_FUSE_VALID_PAUSER`/`_LOCK` | Same function on **AxUSER** (ARUSER/AWUSER). Registers renamed `*_AXI_USER*` at the **same offsets** (0x30048, 0x3005C, 0x30070, 0x30074, 0x30108, 0x3010C). Integration params `CPTRA_DEF_MBOX_VALID_AXI_USER` (default **0xFFFF_FFFF = reserved, must not be used**), `CPTRA_SET_MBOX_AXI_USER_INTEG`, `CPTRA_SET_FUSE_AXI_USER_INTEG` in `soc_ifc_pkg.sv` (IS Table 2, §MAILBOX AXI USER attribute register, Table 19 rows "AXI USER", "MAILBOX/FUSE/TRNG AXI USER programming rules"). ROM fatals with `FW_PROC_MAILBOX_RESERVED_PAUSER` (0x01020009) if a mailbox command arrives with user 0xFFFF_FFFF. AxUSER values must be unique per agent and non-zero recommended. | **FW**: keep rev-3 ordering — program and lock `MBOX_VALID_AXI_USER[0]`, `TRNG_VALID_AXI_USER`, `FUSE_VALID_AXI_USER` **before** any mailbox use (this is exactly what the Agilex-7 TB missed). **R**: give the fuse controller its own AxUSER (proposed Nios = 0x1, fuse ctrl = 0x2) instead of the 1.x shared ID 1 to satisfy the uniqueness rule. Optional hardening: set `CPTRA_SET_FUSE_AXI_USER_INTEG=1`, `CPTRA_FUSE_VALID_AXI_USER=0x2` in an integrator copy of `soc_ifc_pkg.sv` (IS Table 21). |
| 3 | Mailbox | 128 KiB SRAM + 7-bit ECC (32768×39); SoC map mbox_csr @0x2_0000 | **256 KiB** in passive (65536×39, `CPTRA_MBOX_SIZE_KB=256`), SECDED ECC unchanged, exported SRAM port (IS §Mailbox, §SRAM implementation). SoC map unchanged: `mbox_csr` @0x2_0000, `soc_ifc` @0x3_0000 (`caliptra_top_reg.rdl`). SHA512 accelerator is no longer SoC-accessible (Caliptra-only, HS §2.0 changes; IS §SoC SHA acceleration block). New: `mbox_status` ECC bits, TAP mailbox mode. | **R**: mailbox RAM depth doubles (ref wrapper already does this). Quartus `syn_src/caliptra_sram.sv` zero-init override must cover 65536 entries (raise `VERILOG_CONSTANT_LOOP_LIMIT`). **FW**: register offsets for LOCK/CMD/DLEN/DATAIN/EXECUTE/STATUS unchanged. |
| 4 | Caliptra-internal SRAMs | ROM 48 KiB (6144×64); ICCM 128 KiB, DCCM 128 KiB (4 banks ×39b each) | ROM (imem) **96 KiB** (12288×64, `CALIPTRA_IMEM_BYTE_SIZE=98304`); ICCM **256 KiB**, DCCM **256 KiB** (HS §RISC-V core Configuration; `common_defines.sv`). Same `el2_mem_if` export, same timing rules (IS §SRAM timing behavior). | **R**: new ROM init `fw/caliptra-rom.hex` (12288 lines); VeeR export module from caliptra-sw (already in `ref/.../caliptra_veer_sram_export.sv`). |
| 5 | Adams-Bridge (ML-DSA-87 / ML-KEM-1024) SRAMs | n/a | New `abr_mem_if abr_memory_export` (IS Table 8): 10 instances, 1R1W, flopped read, no ECC (ABR §Memory requirement): sk_bank0/1 596×32, w1 512×4, inst0_bank0/1 832×96, inst1 576×96, inst2 1472×96, inst3 64×384, sig_z 224×160 (BE), pk 64×320 (BE). ≈ 0.48 Mbit. | **R**: instantiate `abr_mem_top` (ref wrapper). Check Quartus M20K vs MLAB inference for the wide/shallow ones. |
| 6 | TRNG | `etrng_req` / `CPTRA_TRNG_DATA[12]` / `CPTRA_TRNG_STATUS`; internal TRNG off | Same external-TRNG HW API, same offsets (0x30078, 0x300AC) (IS §TRNG REQ HW API). Internal option `CALIPTRA_INTERNAL_TRNG` = entropy_src + CSRNG with `itrng_data[3:0]`/`itrng_valid`; ROM reads entropy config from `CPTRA_iTRNG_ENTROPY_CONFIG_0/1` and `SS_STRAP_GENERIC[2]` (ROM §Entropy Source Configuration). IS still says external TRNG gives weaker guarantees and that TRNG_REQ must be served by **hardware gasket logic, not SoC firmware**, for FIPS. ROM/FW timeout: 250,000 DONE-bit polls. | Keep external TRNG first (same as 1.x; Nios FW xorshift stays TEST-ONLY). CSRNG/entropy_src are `ifdef`-ed out without `CALIPTRA_INTERNAL_TRNG`, so no area. Later option: hardware TRNG gasket (ring-oscillator PTRNG → `itrng_*` with internal TRNG, or a HW etrng responder). |
| 7 | Fuses | 83 words 0x200–0x348 (UDS 384b, FE 256b, KEY_MANIFEST_PK_HASH+MASK, OWNER_PK_HASH fuse, FMC/RT SVN, anti-rollback, IDEVID attr/HSM id, LIFE_CYCLE, LMS_VERIFY, LMS_REVOCATION, SOC_STEPPING_ID) | New layout (`soc_ifc_fuse_reg.rdl`, ROM §Fuse Registers): `FUSE_UDS_SEED[16]` **512b** @0x200, `FIELD_ENTROPY[8]` @0x240, `VENDOR_PK_HASH[12]` @0x260 (= SHA-384 of ECC + PQC key descriptors), `ECC_REVOCATION` @0x290, `FMC_KEY_MANIFEST_SVN` @0x2B4, `RUNTIME_SVN[4]` (= FW SVN 128b) @0x2B8, `ANTI_ROLLBACK_DISABLE` @0x2C8, `IDEVID_CERT_ATTR[24]` @0x2CC (layout adds MLDSA key-id fields), `IDEVID_MANUF_HSM_ID[4]` @0x32C, `LMS_REVOCATION` @0x340, `MLDSA_REVOCATION` @0x344, `SOC_STEPPING_ID` @0x348, **`MANUF_DBG_UNLOCK_TOKEN[16]`** @0x34C, **`PQC_KEY_TYPE`** @0x38C (one-hot: bit0 MLDSA, bit1 LMS), **`SOC_MANIFEST_SVN[4]`** @0x390, **`SOC_MANIFEST_MAX_SVN`** @0x3A0, **`HEK_SEED[8]`** @0x3C0 (OCP LOCK). **Removed**: `FUSE_LIFE_CYCLE` (lifecycle now only from the `security_state` strap), `FUSE_LMS_VERIFY` (replaced by PQC_KEY_TYPE), `KEY_MANIFEST_PK_HASH_MASK` (→ ECC_REVOCATION), `FUSE_OWNER_PK_HASH` (→ **architectural register `CPTRA_OWNER_PK_HASH[12]` @0x30140 + `CPTRA_OWNER_PK_HASH_LOCK` @0x30170**, pwrgood-reset, write-once lock). Total = **104 fuse words** with holes (0x294–0x2B0, 0x3A4–0x3BC), + 13 owner-hash/lock writes, + `FUSE_WR_DONE`. Warm-reset rule unchanged (IS §Fuses). | **R**: `soc_fuse_ctrl` v2 — image becomes (address, data) pairs (holes), ~118 writes, uses fuse AxUSER, START / START_DONE / CLEAR semantics kept. **TOOL**: rewrite `scripts/gen_fuse_image.py` for the 2.x manifest (offsets below, row 13), dword-reversed hash ordering (ROM §Public key hash byte ordering), PQC_KEY_TYPE=1 (MLDSA) by default. Passive mode: MANUF_DBG_UNLOCK_TOKEN, HEK_SEED, SOC_MANIFEST_* written as 0 (study). |
| 8 | Security state / lifecycle / debug unlock | `security_state` 3b strap {debug_locked, lifecycle[1:0]}; plus `FUSE_LIFE_CYCLE` | Same 3-bit strap, same encodings (UNPROVISIONED 00, MANUFACTURING 01, PRODUCTION 11) (`soc_ifc_pkg.sv`, HS §Security state). Manufacturing / production **debug-unlock flows, UDS programming, `ss_debug_intent`, TAP-mailbox unlock are subsystem-only** (HS §2.0 changes "Subsystem mode support"; IS Table 11). New `cptra_csr_hmac_key[511:0]` strap, latched only in MANUFACTURING (IS Table 12). | **R**: keep Production + debug-locked straps; add `cptra_csr_hmac_key` port driven by a STUDY constant (ignored in Production). Debug unlock in passive mode = drive `debug_locked=0` strap only (as 1.x). |
| 9 | Straps | `cptra_obf_key` (256b), `BootFSM_BrkPoint`, `scan_mode` | Plus 15 `strap_ss_*` inputs (64b/32b/16b), `ss_debug_intent`, `ss_ocp_lock_en` — **all tie to 0 in passive** (IS Table 11). Note: RTL `strap_ss_key_release_key_size` is 16 bits, IS table says 64. SS straps are mirrored into `SS_*` regs @0x30500.. writable by SoC until FUSE_WR_DONE (IS §Straps); in passive we never write them. `SS_STRAP_GENERIC[2]` (entropy config) and `[3]` are consumed by ROM — 0 selects defaults. | **R**: tie-offs as in ref wrapper. `ss_ocp_lock_en` must be a constant (spec) → `1'b0`. |
| 10 | Generic wires | 64-in/64-out; bit0 in = zeroization status | Unchanged binding (IS Table 13). New `strap_ss_strap_generic_0..3` (Table 14) — tie 0. | No change (rev-3 tie-off of `generic_input_wires=0` carries over). |
| 11 | Reset / pwrgood | ≥10 clk before pwrgood, ≥10 clk pwrgood→rst_b; async assert / sync deassert; 2FF syncs (rev 3) | Same rules (IS §Boot FSM, Table 19 "Resets and Clocks", §Reset constraints and assumptions). **New RDC waiver #5**: SoC must ensure **no active AXI transaction while asserting `cptra_rst_b`** (IS Table 25). | **R**: keep 2FF syncs + Reset Release IP gating. **R/FW**: warm-reset routine must quiesce the bridge (drain outstanding Avalon/AXI access, then drop `ctrl_pio[1]`); add a `bridge_idle` status bit. |
| 12 | Watchdog | 2-stage WDT, `CPTRA_WDT_CFG[2]` @0x30110 used by ROM when debug-locked | Same (HS §Watchdog timer); `CPTRA_WDT_CFG` same offset. Timer-2 timeout → NMI + `cptra_error_fatal`. | No change beyond re-checking the timeout margin for the longer 2.x boot (MLDSA keygen). |
| 13 | FW bundle / load | Manifest marker `CMAN` 0x4E414D43, ECC + LMS keys, ~109,000 B; FIRMWARE_LOAD | Manifest marker **`CMN2` 0x434D4E32**, type byte 0x1 = ECC+MLDSA, 0x3 = ECC+LMS; preamble carries ECC + PQC key descriptors (196 B + 1540 B), active MLDSA-87 key (2592 B) and signatures (4628 B) for vendor and owner; header adds PL0 PAUSER and flags (ROM §Firmware image bundle). Test bundle = **253,440 B** (fits 256 KiB mailbox). Command `FIRMWARE_LOAD` unchanged. | **TOOL**: `fw/build_rom.sh` from ref (caliptra-sw `builder --bin image --hw-revision 2.1 --rom-with-log --fw`). **R**: `soc_fw_store` 28,672 → **63,360 words (≈248 KiB)**; `FW_BYTES` param 253440. **FW**: DLEN/loop size from `FC_FW_BYTES`. |
| 14 | Status outputs | `ready_for_fuses`, **`ready_for_fw_push`**, `ready_for_runtime`, `mailbox_data_avail`, `mailbox_flow_done` | `ready_for_fw_push` renamed **`ready_for_mb_processing`**; `mailbox_flow_done` deprecated (IS Table 6). | **R**: rename in `status_pio` packing (bit1). **FW**: rename macro. |
| 15 | Errors | `cptra_error_fatal/non_fatal`; HW_ERROR_FATAL bits iccm/dccm ECC, nmi_pin | Same pins; `CPTRA_HW_ERROR_FATAL` adds `crypto_err` (parallel-crypto error) (`soc_ifc_external_reg.rdl`). Fatal recovery still only via pwrgood (IS Table 19 "Error reporting"). | **FW**: decode new bit in the error log; recovery path unchanged. |
| 16 | Address window / ID regs | Nios window 256 KiB @0x0004_0000; Caliptra decodes 0x2xxxx/0x3xxxx; `CPTRA_HW_REV_ID`=0x0001_0011 | Caliptra AXI AW = 19 → 0x0_0000–0x7_FFFF claimed (reads of unused space return 0/SLVERR). `CPTRA_HW_REV_ID` = **0x0001_0212** with stepping 1 (CPTRA_GENERATION 0x0212). New `CPTRA_HW_CONFIG` @0x300E0 (iTRNG_en, SUBSYSTEM_MODE_en, OCP_LOCK_MODE_en, LMS_acc_en), `CPTRA_HW/FW_CAPABILITIES`, `CPTRA_CAP_LOCK`. | **R/PD**: keep 18-bit Caliptra decode (0x2_0000–0x3_FFFF is all the SoC needs) and leave `fw_store`/`fuse_ctrl` in 0x0_0000–0x1_FFFF, *or* grow the PD window to 1 MiB with Caliptra at 0x8_0000. Prefer the first (zero PD change). **FW**: HW_REV_ID check 0x00010212; assert `HW_CONFIG.SUBSYSTEM_MODE_en==0`, `iTRNG_en==0` at boot. |
| 17 | Clocks / clock gating | single 50 MHz clk; `CPTRA_CLK_GATING_EN`; behavioural ICG | Same single `clk` (validated at 400 MHz in ASIC); same `CPTRA_CLK_GATING_EN` @0x300BC; clocks: clk, clk_cg, rdc_clk_cg, soc_ifc_clk_cg (HS §Clock gating). ABR has its own ICG macro `ABR_ICG`. Integrator overrides `USER_ICG`/`TECH_SPECIFIC_ICG`, `USER_EC_RV_ICG` (IS Table 3, Table 21). | Keep clock gating disabled (reset default). Map `caliptra_icg`/`abr_clk_gate` to an FPGA-safe enable-style gate or Agilex clock-control block; check Quartus gated-clock warnings. Expect ≤50 MHz to close timing with ABR. |
| 18 | DMA / AXI manager | n/a | New `m_axi_w_if`/`m_axi_r_if` (AW 48, `CALIPTRA_AXI_DMA_ADDR_WIDTH`). Passive: **tie to 0, do not connect** (IS §DMA Assist Engine). The `axi_dma_top` logic still synthesizes inside `soc_ifc_top`. | **R**: ref wrapper ties ready/valid/data to 0. |
| 19 | Recovery interface (OCP streaming boot / I3C) | n/a | `recovery_data_avail`, `recovery_image_activated` inputs — subsystem-only; tie 0 (IS Table 11). | **R**: tie 0. |
| 20 | JTAG | tied off (rev 3 open item) | Same pins, TAP endpoint (IS Table 9, Table 19 DFT). | No change (still tied off). |
| 21 | OCP LOCK / key vault | KV/PCR/DV vaults | 2.1 adds OCP LOCK (KV16 MDK, KV23 MEK, HEK seed, DOE HEK flow, AES-to-KV), AES, SHA3, ML-KEM, HMAC512, ECDH, PMP (HS §Key 2.0/2.1 changes; IS §OCP LOCK ROM & FW Requirements). OCP LOCK needs `ss_ocp_lock_en=1` + subsystem DMA → **not usable in passive**. ROM still runs HEK DOE flow to lock it. | Tie `ss_ocp_lock_en=0`; HEK seed fuses 0. Nothing for the SoC to do, but the logic is present and costs area. |
| 22 | `ss_*` outputs, trace | n/a | `ss_dbg_manuf_enable`, `ss_soc_dbg_unlock_level[63:0]`, `ss_generic_fw_exec_ctrl[127:0]`, `trace_rv_*` | Leave unconnected. |
| 23 | Obf UDS / FE wires | n/a | `cptra_obf_uds_seed[511:0]`/`_vld`, `cptra_obf_field_entropy[255:0]`/`_vld` — subsystem fuse-controller path; **tie 0** in passive (IS Table 12). UDS/FE come from fuse registers. | **R**: tie 0. |
| 24 | Synthesis integrity | n/a in 1.x | New generic FI/SCA primitives `caliptra_prim_generic_{and2,buf,clock_mux2,xnor2,xor2,flop,flop_en}`; instances tagged `u__size_only__` must not be optimized (IS §Synthesis Constraints / Primitive Instantiation; `CALIPTRA_PRIM_ROOT`, `CALIPTRA_PRIM_MODULE_PREFIX`). | **R**: add an FPGA prim library (`caliptra_prim_fpga_*`) with Quartus `preserve`/`keep`/`dont_merge` attributes, or QSF `PRESERVE_REGISTER`/`DONT_MERGE_REGISTER` on `*u__size_only__*`; verify in the post-synth netlist. |

### 2.1 Nios firmware boot sequence (2.x) — delta from rev-3 `main.c`

1. Same: wait Reset Release → raise `cptra_pwrgood` → ≥10 clk → release `cptra_rst_b` (2FF-synced in glue).
2. Same offsets, renamed: program + lock `CPTRA_MBOX_VALID_AXI_USER[0]=0x1`, `CPTRA_TRNG_VALID_AXI_USER=0x1`,
   `CPTRA_FUSE_VALID_AXI_USER=0x2` (fuse ctrl), `CPTRA_TIMER_CONFIG=20000` ps, `CPTRA_WDT_CFG[0/1]`.
3. Read `CPTRA_HW_REV_ID` → expect 0x00010212 (after fuse) / `CPTRA_HW_CONFIG` passive bits.
4. Wait `ready_for_fuses` → kick `soc_fuse_ctrl` START (now ~118 writes incl. `CPTRA_OWNER_PK_HASH[12]` + lock) → DONE.
5. Serve `etrng_req` (unchanged API) throughout the ROM (KATs now include AES-GCM, SHAKE-256, LMS, MLDSA87, ECDH, HMAC-512).
6. Wait **`ready_for_mb_processing`** → MBOX_LOCK → CMD `FIRMWARE_LOAD` → DLEN 253,440 → DATAIN×63,360 → EXECUTE → poll STATUS → clear EXECUTE.
7. Wait `ready_for_runtime`. Warm reset: quiesce bridge, `rst_b` only, fuse ctrl START_DONE, wait `ready_for_runtime`.
   Fatal: log `HW/FW_ERROR_*`, pwrgood cycle, full fuse push, retry ≤3 (unchanged).

### 2.2 Simulation delta

- `sim/run_nios_top_fw.sh` compiles the real glue against `caliptra-rtl/` at the repo root (gitignored).
  For 2.x: point it at `/workspace/caliptra-rtl` (v2.1.2) and build from a new `sim/boot_axi.f` derived from
  `ref/agilex7-2x-phaseA/caliptra_passive_top.f` (+ adams-bridge Verilator patch).
- Behavioural `nios_caliptra_sys` stand-in keeps the Avalon side, so only the expected values/sequence change
  (renamed ready signal, AXI user test instead of PAUSER test, bigger bundle, new fuse image).
- Tests to port: `sync`, `axiuser` (was `pauser`: wrong AxUSER → SLVERR), `prod`, `warm`, `fatal`, `all`.
- Runtime: 2.x ROM reached `ready_for_mb_processing` at 5.54 M cycles; full ROM+FMC+RT boot is expected in the
  25–60 M-cycle range (1.x: 24.06 M). At the observed 0.5–8.7 kHz (Verilator 5.054, 4 threads, box load dependent)
  a single prod boot is **1–30 h wall time**; `+test=all` (two boots) correspondingly more. Use caliptra-sw
  `sw-emulator` for fast functional checks of fuse/bundle content before RTL runs.

## 3. Resource estimate for A5EC065 (222,400 ALMs, 1,611 M20K, 846 DSP blocks, 889,600 ALM regs)

### 3.1 Measured 1.x (this design, Quartus Pro 25.3 synthesis, `quartus_a5e_nios/output_files/nios_caliptra_a5e.syn.rpt` at 02e5cd6)

| Block | ALUTs | Registers | Notes |
|---|---:|---:|---|
| Whole design | 223,708 | 145,696 | **138,715 ALMs (62%)**, 5.67 Mbit block RAM, 49 DSP |
| caliptra_top (1.x) | 218,761 | 141,933 | |
| — ecc_top1 (ECC P-384) | 81,331 | 51,594 | 46 DSP |
| — rvtop (VeeR) | 34,711 | 20,845 | |
| — key_vault1 | 32,734 | 12,912 | |
| — hmac (HMAC-384) | 22,266 | 14,008 | |
| — pcr_vault1 | 16,126 | 12,559 | |
| — soc_ifc_top1 | 11,988 | 9,782 | |
| — sha512 / doe / sha256 / data_vault | 7,225 / 3,544 / 2,699 / 5,593 | | |
| Nios V system + glue | ~4,200 | ~3,700 | |

### 3.2 2.x additions (no Quartus run yet — estimates)

| 2.x addition | Estimate | Source / basis |
|---|---|---|
| Adams-Bridge (ML-DSA-87 + ML-KEM, masked + shuffled NTT) | **210,251 LUTs, 234,180 FFs, 268 DSPs** on Xilinx Virtex UltraScale+ → ≈ **130–170 k ALMs** on Agilex 5 | Karabulut & Azarderakhsh, *Drop-In Masked Modular Reduction for ML-DSA*, IACR ePrint 2026/711, Table I. Cross-check: Caliptra ABR SCA presentation (chipsalliance caliptra-web `adamsbridge-sca-presentation.pdf`): "ABR area … around **3.4× ECC P384**; masking = 6× area overhead" → 3.4 × 81.3 k ALUTs ≈ 276 k ALUTs. ASIC: ABR 0.1096 mm² @5 nm (ABR §Area Results). |
| AES (masked, OpenTitan-derived) + AES-to-KV/OCP LOCK | ~10–20 k ALMs | Engineering estimate; ROM KAT requires it |
| SHA3 / SHAKE | ~4–8 k ALMs | Estimate; ROM SHAKE-256 KAT |
| HMAC-384 → HMAC-512 + DRBG, ECC + ECDH, KV/PCR changes | ~+5–15 k ALMs | Estimate vs 1.x blocks above |
| AXI sub + AXI DMA (+ AES path) + SHA-acc save/restore, VeeR PMP | ~+5–12 k ALMs | Estimate; DMA is synthesized even when tied off |
| CSRNG + entropy_src | 0 (ext TRNG; `ifdef`-ed out) / +15–25 k if internal TRNG | `caliptra_top.sv` `ifdef CALIPTRA_INTERNAL_TRNG` |

**Projected total (2.x core + Nios/glue): ≈ 136 k (1.x core) + 130–170 k (ABR) + 25–55 k (rest) + 4 k ≈ 295–365 k ALMs
= 133–164 % of A5E065.** Even an optimistic 100 k-ALM ABR gives ≈ 265 k ALMs (≈119 %).
Registers (~410–430 k of 889,600) and memory are not the binding constraint:

| Memory | Size | Est. M20K |
|---|---|---:|
| Mailbox 65536×39 | 2.56 Mbit | 128 |
| ICCM 256 KiB + ECC | 2.56 Mbit | 128 |
| DCCM 256 KiB + ECC | 2.56 Mbit | 128 |
| ROM 12288×64 | 0.79 Mbit | ~48 |
| ABR 10 memories | 0.48 Mbit | ~50–60 (some may go to MLAB) |
| SoC FW store 63,360×32 | 2.03 Mbit | ~100–124 |
| Nios OCM 64 KiB + misc | 0.53 Mbit | ~30 |
| **Total** | **≈ 11.5 Mbit (37 %)** | **≈ 610–680 (38–42 % of 1,611)** |

DSP: 49 (1.x) + ~270 (ABR) ≈ 320 blocks of 846 — fits.

**Verdict: a full Caliptra 2.x core (passive) is very unlikely to fit A5E065 on logic (ALMs).** Memory and DSP fit.
Confidence: medium — the ABR number is from Xilinx LUT6s and a third-party build; it must be confirmed with a
Quartus synthesis of the 2.x core-only wrapper on A5EC065 (Phase 1 gate below). A5E065 is already the largest
Agilex 5 E-series device, so there is no in-family upsize.

### 3.3 Options if Phase 1 confirms it does not fit

| Option | Fit | Spec-conformant | Effort | Comment |
|---|---|---|---|---|
| A. Move the 2.x build to **Agilex 7** (e.g. AGF/AGI 014 ≈ 487 k ALMs, or 022/027) | Yes, with margin | Yes | Low–medium (same RTL, new QSF/pins/PD) | Earlier Phase-A 2.x work already targeted Agilex 7. Needs the board/license. |
| B. Keep A5E on Caliptra 1.x for hardware; develop 2.x integration in **Verilator + sw-emulator only** | n/a | Yes | Low | Get the glue/FW/tooling right now, retarget to bigger silicon later. |
| C. Unmasked / reduced ABR (study fork) | Maybe | **No** (removes SCA countermeasures; upstream `MLDSA_MASKING` define only zeroes the randomness, it does not remove the masked datapath — real savings need an RTL fork) | High | Research only; would diverge from v2.1.2. |
| D. Stub out ABR / AES / SHA3 | — | No | — | **Not viable**: 2.x ROM runs MLDSA87, LMS, AES-GCM, SHAKE-256 KATs and MLDSA IDevID/LDevID keygen; a stub causes a fatal error. |
| E. Partition across two FPGAs | — | — | Very high | Not recommended. |

## 4. Phased implementation plan

Effort is engineer-days of focused work (compute time noted separately). Each phase ends with a local commit.

| Phase | Work | Success criteria | Effort |
|---|---|---|---|
| **P0 (done)** | Copy 1.x design, fresh repo, this plan, import 2.x Phase-A reference, Verilator lint of the 2.x core-only top | Repo + plan committed; lint 0 errors | — |
| **P1 — Fit gate** | Quartus Pro 25.3 synthesis of the 2.x core-only wrapper (no Nios) on A5EC065: new `quartus_a5e_2x/` project from `ref/.../caliptra_passive_top.f`, SV-2017, FPGA ICG/prim/SRAM overrides. Record ALMs/M20K/DSP per hierarchy (especially `abr_top`, `aes`, `sha3`). | Synthesis completes; numbers in `docs/`; **go / no-go decision on A5E065** | 1–2 d + 4–10 h compute (risk: box has 15 GB RAM; 1.x synth fit, 2.x may need ≥32 GB) |
| **P2 — Fuse / bundle / ROM tooling** | Rebuild ROM + test-signed bundle (rom-2.1.3-1, decide fw tag), new `gen_fuse_image.py` (2.x offsets, vendor/owner hash per ROM spec, PQC_KEY_TYPE, address/data image), optional check in sw-emulator | sw-emulator (or caliptra-sw hw-model) boots the bundle with our fuse/owner-hash values in Production + debug-locked | 1–2 d |
| **P3 — RTL glue port** | `avmm_to_axi.sv`; `nios_caliptra_top.sv` rewire (AXI, new ports, tie-offs, rename ready signal, separate fuse AxUSER, bridge-idle for warm reset); `soc_fuse_ctrl` v2; `soc_fw_store` 248 KiB; 2.x wrapper moved into `rtl/` | Verilator lint of the full top clean; elaboration of glue + 2.x core | 3–5 d |
| **P4 — Nios FW port** | `main.c` register map/sequence per §2.1, HW_REV_ID/HW_CONFIG checks, AXI-user programming before mailbox use, bigger bundle, warm-reset quiesce, error decode | Builds with the Nios V BSP; behavioural TB executes the same sequence | 2–3 d |
| **P5 — Verilator regression** | Port `tb_nios_top_fw.sv` (+`boot_axi.f`); tests sync / axiuser / prod / warm / fatal / all | All PASS; prod reaches `ready_for_runtime` with FW loaded (no reload on warm reset) | 3–5 d + 1–2 days of sim wall time |
| **P6 — Implementation on chosen device** | If P1 = go: full A5E065 compile (PD regen, SDC, timing at 50 MHz). If no-go: Agilex 7 project (option A) or stop at P5 (option B). | Fit + timing met; SOF needs programming-file license | 3–5 d + compute (route likely needs ≥64 GB RAM) |
| **P7 — Integration guide 2.x** | `docs/NIOS_CALIPTRA_2X_INTEGRATION.md` with signal table, memory map, sequence, compliance checklist vs IS v2.1.2 Table 19 | Checklist 0 FAIL (TEST-ONLY items listed) | 1–2 d |

**Total: ≈ 14–24 engineer-days** to a passing 2.x passive simulation + guide (P1–P5, P7), plus P6 depending on the device decision.
P2–P5 are device-independent and can proceed in parallel with the P1 synthesis run.

## 5. Risks

1. **Logic fit on A5E065** (high likelihood, high impact) — §3. Mitigation: P1 gate before any Quartus/PD work; options A/B.
2. **Build machine**: 1.x route already needs ≥32 GB; 2.x synth/route of ~300 k ALMs likely needs ≥64 GB. The box has 15 GB.
3. **Quartus compatibility of 2.x RTL** (interfaces, packed structs, adams-bridge constructs, gated clocks); Verilator-only so far.
4. **Timing**: ABR NTT/masked reduction paths are deep; 50 MHz is probably fine, higher may not be.
5. **Sim wall time**: hours per boot; regressions need overnight runs. Mitigate with sw-emulator and `+test=` granularity.
6. **Fuse/hash byte ordering** (dword reversal, owner hash now a register) — wrong ordering = ROM image-verify fatal in Production. Validate in sw-emulator first.
7. **AxUSER handling** — default valid user 0xFFFF_FFFF is reserved; forgetting to program/lock valid users reproduces the SLVERR / 0x01020009 failures already seen.
8. **Spec items still TEST-ONLY** carry over: FPGA-RAM fuses, study UDS/FE/obf key/CSR-HMAC key, firmware-driven etrng (spec wants HW gasket), no pwrgood SRAM zeroization FSM (now 2× larger SRAMs), JTAG tied off.

## 6. Open questions (need your input)

- **Q1 Target device** if P1 confirms no fit: move 2.x to Agilex 7 (which part/kit do you have?), or keep A5E on 1.x and do 2.x in simulation only?
- **Q2 PQC signature type** for FW validation: ML-DSA-87 (default, `PQC_KEY_TYPE=1`) or LMS (`=2`)?
- **Q3 Lifecycle mimic** for first bring-up: Production + debug-locked (as 1.x rev 3; needs correct vendor/owner hashes) or Unprovisioned first?
- **Q4 FW bundle source**: on-chip M20K store (≈248 KiB) as today, or add QSPI flash now?
- **Q5 AxUSER IDs**: Nios = 0x1, fuse controller = 0x2 OK? Harden fuse user via integration parameter?
- **Q6 Build host**: OK to run the P1 2.x synthesis on this 15 GB box (may OOM), or is a ≥64 GB machine available?
- **Q7 FW version**: keep the matched rom-2.1.3-1 / fw-2.1.4 commit, or rebuild runtime from the newest fw-2.1.5?
- **Q8** Stay strictly upstream v2.1.2 (no ABR masking surgery), as recommended?

## 7. File map (this repo)

| Path | Status |
|---|---|
| `quartus_a5e_nios/`, `rtl/`, `sim/`, `fw/`, `scripts/`, `docs/NIOS_CALIPTRA_INTEGRATION.md` | 1.x baseline, unchanged from 02e5cd6 (Quartus `output_files/` not copied) |
| `ref/agilex7-2x-phaseA/` | 2.x core-only reference wrapper, TB, ROM build script, run excerpts (unchanged copies) |
| `sim/2x_ref/lint_v2.1.2_core_passive.log` | Verilator lint of the 2.x core-only top (this plan) |
| `docs/CALIPTRA_2X_INTEGRATION_PLAN.md` | This document |

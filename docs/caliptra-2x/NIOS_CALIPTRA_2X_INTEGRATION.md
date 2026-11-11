# Nios V ↔ Caliptra 2.x Integration Guide (passive / core-only)

> **Where the files are.** All paths in this guide are repo-relative ([pwilliam282/caliptra-a5e-quartus](https://github.com/pwilliam282/caliptra-a5e-quartus)):
> - 2.x glue RTL, sim, firmware, fuse script and Quartus project: [`caliptra2x/`](../../caliptra2x/) (`caliptra2x/rtl_2x/`, `caliptra2x/sim_2x/`, `caliptra2x/sim/`, `caliptra2x/fw_2x/`, `caliptra2x/scripts/`, `caliptra2x/quartus_a5e_2x/`)
> - Upstream RTL: `external/caliptra-rtl-2x/` = chipsalliance/caliptra-rtl v2.1.2 (`49370266`) with `submodules/adams-bridge` (`b77e3d8`), a pinned git submodule, unmodified. Fetch it with `scripts/get_caliptra_a5e.sh` or `git clone --recursive` + `scripts/fetch_deps.sh`. See [NIOS_CALIPTRA_2X_INTEGRATION.md §16](NIOS_CALIPTRA_2X_INTEGRATION.md#16-getting-the-sources).
> - Companion docs `P1_FIT_RESULT_2X_A5E.md` and `CALIPTRA_2X_INTEGRATION_PLAN.md`: this folder (`docs/caliptra-2x/`). The 1.x guide is [`docs/NIOS_CALIPTRA_INTEGRATION.md`](../NIOS_CALIPTRA_INTEGRATION.md).
>
> caliptra-sw is not vendored (only the built ROM/bundle in `caliptra2x/fw_2x/`).

- **Project:** Caliptra 2.x in passive (core-only) mode on Intel Agilex 5 E **A5EC065BB32AE6S**, with a Nios V/m mailbox host (Avalon → AXI4).
- **RTL:** chipsalliance/caliptra-rtl **v2.1.2**, commit `49370266d12cb0c4a8f71b3a0ff7e54ba7d4866e`. `CALIPTRA_MODE_SUBSYSTEM` is **not** defined (core-only), and `CALIPTRA_INTERNAL_TRNG` is **not** defined (external TRNG).
- **Firmware:** caliptra-sw `dd1e79d5bf55a9bd5bdb05915757eaf34844145d`, which carries tags `rom-2.1.3-1` and `fw-2.1.4`. See [FIRMWARE_AND_KEYS_2X.md](FIRMWARE_AND_KEYS_2X.md).
- **Simulation:** Verilator 5.054, one cold boot to `ready_for_runtime`, **PASS**. See [SIMULATION_2X.md](SIMULATION_2X.md).
- **Companion docs:** [docs/caliptra-2x/P1_FIT_RESULT_2X_A5E.md](P1_FIT_RESULT_2X_A5E.md) (Quartus fit gate), [docs/caliptra-2x/CALIPTRA_2X_INTEGRATION_PLAN.md](CALIPTRA_2X_INTEGRATION_PLAN.md) (1.x → 2.x delta and phased plan). The 1.x guide this one is modelled on is `docs/NIOS_CALIPTRA_INTEGRATION.md` (rev 3).
- **Getting the sources / building:** §16 (clone with submodules; upstream RTL in `external/caliptra-rtl-2x/`) and §17 (Quartus Pro 25.3 build, Docker, license, measured results, known issues).
- **Date:** 2026-11-10 (America/Chicago).

> **Status.** This is a *design study*. The 2.x glue RTL and the boot flow are verified in Verilator. The design **does not fit** the A5E 065: synthesis estimates 279,685 / 222,400 ALMs (126 %) (§14). Every key, seed and entropy value is a **TEST/STUDY value**: the obfuscation key, CSR HMAC key, UDS, field entropy, the test-signed firmware, and the simulated TRNG data. The firmware is signed with caliptra-sw's **public fake keys**. See [FIRMWARE_AND_KEYS_2X.md §6](FIRMWARE_AND_KEYS_2X.md).

**What exists and what doesn't (2.x tree):**

| Item | State |
|---|---|
| `caliptra2x/rtl_2x/nios_caliptra2x_top.sv`, `avmm_to_axi.sv`, `soc_fuse_ctrl2x.sv`, `soc_fw_store.sv`, `reset_sync.sv`, `caliptra_passive_top.sv` | Written; simulated (Verilator) |
| `caliptra2x/scripts/gen_fuse_image_2x.py` → `caliptra2x/fw_2x/fuse_image_2x.hex` | Written; output used in the PASS run (regeneration is byte-identical) |
| `caliptra2x/fw_2x/` ROM + FW bundle (+ `build_rom.sh`, `SHA256SUMS`) | Built from caliptra-sw `dd1e79d` |
| Platform Designer system `nios_caliptra2x_sys` (Nios V + PIOs + 1 MiB window) | **Not created yet.** The TB uses a behavioral stand-in module `nios_caliptra2x_sys` with the ports the top instantiates: `clk_clk`, `reset_reset_n`, `caliptra_axi_address[19:0]`, `_read`, `_write`, `_writedata[31:0]`, `_byteenable[3:0]`, `_readdata[31:0]`, `_readdatavalid`, `_waitrequest`, `_burstcount`, `_debugaccess`, `ctrl_pio_export[31:0]` (out), `status_pio_export[31:0]` (in), `magic_pio_export[31:0]` (out) |
| Nios C firmware for 2.x (`main.c` port) | **Not ported yet.** The 1.x `quartus_a5e_nios/sw/app/main.c` is unchanged. The TB host model defines the 2.x sequence (§11) |
| Quartus project for the full Nios + 2.x top | **Not created.** `caliptra2x/quartus_a5e_2x/` synthesizes only the Caliptra core wrapper (fit gate) |

---

## 1. Source files

| File | Role |
|---|---|
| `caliptra2x/rtl_2x/nios_caliptra2x_top.sv` | FPGA top: Reset Release gate, PD system, SoC window decode, Avalon→AXI bridge, fuse controller, AXI write-channel mux, 2FF reset syncs, straps, status PIO |
| `caliptra2x/rtl_2x/caliptra_passive_top.sv` | Core-only wrapper around `caliptra_top`: flattens the AXI subordinate to ports, ties off the AXI manager (DMA) and all `ss_*` straps, instantiates the mailbox SRAM, ROM, VeeR ICCM/DCCM and Adams-Bridge memories |
| `caliptra2x/rtl_2x/avmm_to_axi.sv` | Avalon-MM agent → AXI4 manager, single beat, 1 outstanding, AxUSER = `user_i` |
| `caliptra2x/rtl_2x/soc_fuse_ctrl2x.sv` | SoC fuse sequencer (stand-in for OTP + fuse controller); replays `caliptra2x/fw_2x/fuse_image_2x.hex` over AXI with AxUSER 2 |
| `caliptra2x/rtl_2x/soc_fw_store.sv` | Read-only M20K store holding `caliptra2x/fw_2x/caliptra-fw-bundle.hex` (stand-in for boot flash) |
| `caliptra2x/rtl_2x/reset_sync.sv` | `rst_sync_async_assert` / `pwrgood_sync_async_assert` (async assert, 2FF sync deassert) |
| `caliptra2x/rtl_2x/caliptra_veer_sram_export.sv` | VeeR ICCM/DCCM SRAM export |
| `caliptra2x/sim/rst_release_stub.sv` | Verilator stand-in for the Agilex 5 Reset Release IP (`ninit_done` high for 25 ns) |
| `caliptra2x/scripts/gen_fuse_image_2x.py` | Builds the fuse image from the FW bundle |
| `caliptra2x/fw_2x/` | ROM, FW bundle, hex files, `SHA256SUMS`, `build_rom.sh`, `fuse_image_2x.hex` |
| `caliptra2x/sim_2x/` | `boot2x.f`, `tb_nios2x_top_fw.sv`, `run_nios2x_top_fw.sh`, `BOOT_NIOS2X.md`, `nios2x_top_fw_run.log` |

---

## 2. Block diagram

```mermaid
flowchart TB
  clk["clk (single clock)"]
  rstn["reset_n (board)"]
  rr["Reset Release IP<br/>u_rst_release.ninit_done"]
  gate["sys_reset_n =<br/>reset_n & ~ninit_done"]
  rstn --> gate
  rr --> gate

  subgraph pd ["nios_caliptra2x_sys (Platform Designer, NOT YET CREATED — TB stand-in)"]
    cpu["Nios V/m"]
    ctrl["ctrl_pio out"]
    stpio["status_pio in"]
    magic["magic_pio out"]
    win["caliptra_axi<br/>exported Avalon window 1 MiB, 20-bit"]
    cpu --> ctrl
    cpu --> stpio
    cpu --> magic
    cpu --> win
  end
  clk --> pd
  gate --> pd
  gate -->|"2FF u_sync_glue"| glue["glue_rst_n"]
  magic -->|"[7:0]"| led["led[7:0]"]

  win --> dec["window decode"]
  dec -->|"0x00000–0x3FFFF"| fw["soc_fw_store<br/>caliptra-fw-bundle.hex (253,440 B)"]
  dec -->|"0x7F000–0x7FFFF"| fuse["soc_fuse_ctrl2x<br/>fuse_image_2x.hex (117 entries)"]
  dec -->|"0x80000–0xFFFFF<br/>AXI addr = a[18:0]"| br["avmm_to_axi<br/>AxUSER = 1 (Nios)"]
  fuse -->|"AW/W/B while busy<br/>AxUSER = 2"| mux["AXI write-channel mux"]
  br --> mux
  br -->|"AR/R always"| ctop

  ctrl -->|"[0] pwrgood, [1] rst_b"| sync["2FF sync<br/>async assert, sync deassert"]
  sync -->|"cptra_pwrgood, cptra_rst_b"| ctop
  ctrl -->|"[2] BootFSM_BrkPoint"| ctop
  mux --> ctop

  subgraph wrap ["caliptra_passive_top"]
    ctop["caliptra_top v2.1.2<br/>(core-only, AXI4 subordinate)"]
    msram["mailbox SRAM 256 KiB + ECC<br/>65536 × 39"]
    rom["ROM 96 KiB<br/>12288 × 64, caliptra-rom.hex"]
    veer["VeeR ICCM / DCCM<br/>256 KiB each"]
    abr["Adams-Bridge memories<br/>abr_mem_top"]
    ctop --> msram
    ctop --> rom
    ctop --> veer
    ctop --> abr
  end
  ctop -->|"ready_for_*, mailbox_*, errors,<br/>etrng_req, generic_out[23:0]"| stpio
```

---

## 3. Port and signal tables

### 3.1 `nios_caliptra2x_top` parameters and ports

| Parameter | Default | Meaning |
|---|---|---|
| `ROM_INIT_FILE` | `"../fw_2x/caliptra-rom.hex"` | Caliptra ROM image (`$readmemh`, 64-bit words) |
| `FW_INIT_FILE` | `"../fw_2x/caliptra-fw-bundle.hex"` | FW bundle for `soc_fw_store` (32-bit LE words) |
| `FUSE_IMAGE` | `"../fw_2x/fuse_image_2x.hex"` | Fuse image for `soc_fuse_ctrl2x` |
| `FW_BYTES` | `253440` | Bundle size reported by fuse ctrl MMIO `0x10` (used as `MBOX_DLEN`) |
| `NUM_FUSES` | `117` | Image entries (104 fuse words + 12 owner-hash words + 1 lock) |
| `NIOS_AXI_USER` | `32'h1` | AxUSER driven on every Nios access |
| `FUSE_AXI_USER` | `32'h2` | AxUSER driven by the fuse controller |

| Port | Dir | Width | Connection |
|---|---|---|---|
| `clk` | in | 1 | Single clock (rising edge) for the PD system, glue and Caliptra. It is the only clock domain in the top, and both 2FF reset synchronizers run on it |
| `reset_n` | in | 1 | Board reset, **active-low**, asynchronous: it is ANDed with `~ninit_done` (`sys_reset_n = reset_n & ~ninit_done`) without being synchronized first |
| `led` | out | 8 | `magic_out[7:0]` (`magic_pio_export`), active-high, 1 = bit set; driven by the magic PIO (TB model initializes it to 0) |

### 3.2 Internal glue signals

| Signal | Source → sink | Notes |
|---|---|---|
| `ninit_done` | `rst_release` → gate | Agilex 5 Reset Release IP output, **active-high**: 1 = device still initializing, 0 = user logic may run. Sim stub `caliptra2x/sim/rst_release_stub.sv`: 1 at time 0, 0 after 25 ns |
| `sys_reset_n` | `reset_n & ~ninit_done` | **Active-low**, combinational and asynchronous (not synchronized in this top). It drives the PD `reset_reset_n`, feeds `u_sync_glue`, and is ANDed into `raw_pwrgood` / `raw_rst_b` |
| `glue_rst_n` | `u_sync_glue` = `rst_sync_async_assert #(.STAGES(2))` on `sys_reset_n` | **Active-low**. Assertion (1→0) is asynchronous; deassertion (0→1) comes 2 `clk` edges after `sys_reset_n` rises. It resets the read-valid flops of the window decode, `avmm_to_axi`, `soc_fuse_ctrl2x` and `nios_axi_user` |
| `ctrl_out[0]` | ctrl PIO → `raw_pwrgood = ctrl_out[0] & sys_reset_n` → `u_sync_pwrgood` = `pwrgood_sync_async_assert #(.STAGES(2))` → `cptra_pwrgood` | **Active-high** (1 = power good). The cell sets `cptra_pwrgood` = 1 asynchronously as soon as `raw_pwrgood` rises, and drops it 2 `clk` edges after `raw_pwrgood` falls (see §10.1 note). The PIO reset value must be 0 (the TB model initializes `ctrl` = 0), so Caliptra starts unpowered |
| `ctrl_out[1]` | ctrl PIO → `raw_rst_b = ctrl_out[1] & sys_reset_n` → `u_sync_rst_b` = `rst_sync_async_assert #(.STAGES(2))` → `cptra_rst_b` | **Active-low** reset (0 = Caliptra in reset). Assertion (1→0) is asynchronous; deassertion (0→1) comes 2 `clk` edges after `raw_rst_b` rises. Reset value 0. A warm reset drops only this bit |
| `ctrl_out[2]` | ctrl PIO → `BootFSM_BrkPoint` (direct, no synchronizer) | **Active-high**, reset value 0. `soc_ifc_top.sv` latches it once after `cptra_noncore_rst_b` deasserts. It only takes effect if debug is unlocked or the lifecycle is MANUFACTURING (or `ss_debug_intent` = 1). With the straps here (PRODUCTION, `debug_locked` = 1, `ss_debug_intent` = 0) it is **ignored** |
| `status_in[31:0]` | Caliptra outputs → `status_pio_export` (PIO input) | Bit map, polarity and reset values in §3.3 |
| `fuse_busy` | `soc_fuse_ctrl2x.busy` | Active-high, combinational from the FSM state (0 in reset/IDLE). It is 1 in NEXT/SEND/RESP, when the fuse ctrl owns AW/W/B |
| `bridge_idle` | `avmm_to_axi.idle` | Active-high, 1 in bridge state `IDLE` (1 in reset). Meant for a warm-reset quiesce; **not yet used** in the top |
| `nios_axi_user[31:0]` | Flop on `clk` / `glue_rst_n`, reset and load value `NIOS_AXI_USER` = `32'h1` | A register (not an assign) so the TB can `force` a wrong ID |
| `generic_input_wires[63:0]` | Constant `64'b0` → `caliptra_top` input | IS Table 13: bit 0 = zeroization status; with no source it is tied to 0 |

### 3.3 `status_pio` bits (32-bit input PIO, `status_in`)

`nios_caliptra2x_top.sv`: `status_in = {generic_output_wires[23:0], etrng_req, cptra_error_non_fatal, cptra_error_fatal, mailbox_flow_done, mailbox_data_avail, ready_for_runtime, ready_for_mb_processing, ready_for_fuses}`.

Common to every bit:
- **Direction:** `caliptra_top` **output** → `caliptra_passive_top` output → `status_in` → `status_pio_export` (PIO **input**, Nios reads it).
- **Polarity:** all **active-high**: 1 = condition true.
- **Clock domain:** Caliptra's `clk`. Each bit comes from a flop clocked by `clk` or by one of the clock-gated copies of `clk` that `clk_gate.sv` makes (`rdc_clk_cg`, `soc_ifc_clk_cg`):
  - bit 0: the boot FSM on `clk`;
  - bits 1, 2, 4, 7 and 31:8: `soc_ifc_reg` on `rdc_clk_cg`;
  - bits 5 and 6: `soc_ifc_top` flops on `rdc_clk_cg`;
  - bit 3: decoded combinationally from the mailbox FSM state register, which runs on `soc_ifc_clk_cg`. Nios, glue and Caliptra all run on the single top-level `clk`, so there is **no synchronizer**: the bits are wired straight to the PIO.
- **Reset value:** all **0**. Bits 0, 3, 5 and 6 reset on `cptra_noncore_rst_b`, the internal reset derived from `cptra_rst_b`. The register-backed bits (1, 2, 4, 7 and 31:8) have `resetsignal = cptra_rst_b`. So they all read 0 while `ctrl` = 0 after power-up.
- **Bit positions:** identical to the 1.x `quartus_a5e_nios/rtl/nios_caliptra_top.sv` status PIO. Only bit 1 changed name.

| Bit | Signal (1-bit unless noted) | Driver inside caliptra-rtl v2.1.2 | Reset | Meaning when 1 / host use | 1.x bit |
|---|---|---|---|---|---|
| 0 | `ready_for_fuses` | `soc_ifc_boot_fsm.sv` flop on `clk`: `(boot_fsm_ps == BOOT_FUSE) && !fuse_wr_done_observed` | 0 | The boot FSM is in `BOOT_FUSE` and `CPTRA_FUSE_WR_DONE` has not been written yet, so fuses may be written. It is also wired to `soc_fuse_ctrl2x.ready_for_fuses`: START/START_DONE without it gives ERR, and it reads back as fuse ctrl STATUS bit 3. The host polls it at §11 step 3 | bit 0 `ready_for_fuses` |
| 1 | `ready_for_mb_processing` | `CPTRA_FLOW_STATUS.ready_for_mb_processing` (bit 28), written by ROM/FW (`soc_ifc_reg`, `rdc_clk_cg`) | 0 | The ROM is ready for a mailbox command (FW_LOAD). The host polls it at step 7 | bit 1 `ready_for_fw_push` |
| 2 | `ready_for_runtime` | `CPTRA_FLOW_STATUS.ready_for_runtime` (bit 29), written by FW | 0 | Runtime firmware is up. The host polls it at step 10 | bit 2 `ready_for_runtime` |
| 3 | `mailbox_data_avail` | `mbox.sv` (`soc_ifc_clk_cg`) `soc_mbox_data_avail` = 1 while the mailbox FSM is in `MBOX_EXECUTE_SOC` | 0 (FSM resets to `MBOX_IDLE`) | The Caliptra uC has set EXECUTE with data or a response for the SoC. The TB host does not poll it; it uses `MBOX_STATUS` | bit 3 `mailbox_data_avail` |
| 4 | `mailbox_flow_done` | `CPTRA_FLOW_STATUS.mailbox_flow_done` (bit 31), written by FW | 0 | FW reports that the mailbox flow is complete. The TB does not poll it. The final `CPTRA_FLOW_STATUS = b8000000` has it set | bit 4 `mailbox_flow_done` |
| 5 | `cptra_error_fatal` | `soc_ifc_top.sv` flop on `rdc_clk_cg`, set by a new unmasked bit in `CPTRA_HW_ERROR_FATAL` / `CPTRA_FW_ERROR_FATAL` | 0 | Fatal error. It is **sticky**: the RTL has no clear path except reset (the RTL comment says the platform must apply `cptra_rst_b`). The IS recovery rule is a pwrgood cycle (§10.3). The TB treats it as FAIL | bit 5 `cptra_error_fatal` |
| 6 | `cptra_error_non_fatal` | `soc_ifc_top.sv` flop on `rdc_clk_cg`, set like bit 5 from the `*_NON_FATAL` registers | 0 | Non-fatal error. It deasserts once every unmasked non-fatal bit is cleared; the host clears them with RW1C | bit 6 `cptra_error_non_fatal` |
| 7 | `etrng_req` | `soc_ifc_top.sv` `trng_req = CPTRA_TRNG_STATUS.DATA_REQ` (no `CALIPTRA_INTERNAL_TRNG`) | 0 | ROM/FW requests TRNG data. The host writes `CPTRA_TRNG_DATA[0..11]`, then `DATA_WR_DONE` (§9) | bit 7 `etrng_req` |
| 31:8 | `generic_output_wires[23:0]` (24 of 64 bits) | `CPTRA_GENERIC_OUTPUT_WIRES[0][23:0]`, written by ROM/FW (`[63:24]` not wired to the PIO) | 0 | ROM/FMC/RT console: `[7:0]` = ASCII character, and `[8]` toggles once per character (the TB decoder in `tb_nios2x_top_fw.sv` prints lines from these). `[23:9]` are not decoded | bits 31:8 `generic_output_wires[23:0]` |

### 3.4 `caliptra_passive_top` / `caliptra_top` connections

Widths come from `config_defines.svh`: `CALIPTRA_AXI_DATA_WIDTH` = 32, `CALIPTRA_AXI_USER_WIDTH` = 32, `CALIPTRA_AXI_ID_WIDTH` = 8. The SoC-interface address width is `CALIPTRA_SLAVE_ADDR_WIDTH(SOC_IFC)` = **19** bits (base `0x3000_0000`, mask `0x3007_FFFF`).

**Clocks, resets, straps, keys**

| `caliptra_top` port | Width | Driven by (`nios_caliptra2x_top` → wrapper) | Status |
|---|---|---|---|
| `clk` | 1 | Top-level `clk`, direct | Caliptra input; same clock as Nios and glue, so there is no CDC |
| `cptra_pwrgood` | 1 | `u_sync_pwrgood` output (from `ctrl_out[0] & sys_reset_n`) | Input, **active-high**; 0 = Caliptra powered off (cold reset of all pwrgood-domain state). Reset value 0 |
| `cptra_rst_b` | 1 | `u_sync_rst_b` output (from `ctrl_out[1] & sys_reset_n`) | Input, **active-low**; 0 = Caliptra in (warm) reset. Async assert, 2FF sync deassert. Reset value 0 |
| `cptra_obf_key` | 256 | `STUDY_PROD_MIMIC_OBF_KEY` = `31358e8a_f34d6a45_…_b2c3b8d5` (localparam) | **TEST-ONLY** |
| `cptra_csr_hmac_key` | 16 × 32 (`CLP_CSR_HMAC_KEY_DWORDS` = 16) | `{16{32'h5A3C_96E1}}` | **TEST-ONLY** |
| `security_state.device_lifecycle` | 2 | `2'b11` = DEVICE_PRODUCTION | **TEST-ONLY** (hardwired) |
| `security_state.debug_locked` | 1 | `1'b1` | **TEST-ONLY** (hardwired) |
| `cptra_obf_field_entropy_vld` / `cptra_obf_field_entropy` | 1 / 256 | `0` / `'0` | Passive: tie 0 (IS Table 12) |
| `cptra_obf_uds_seed_vld` / `cptra_obf_uds_seed` | 1 / 512 | `0` / `'0` | Passive: tie 0 |
| `BootFSM_BrkPoint` | 1 | `ctrl_out[2]`, direct | Input, active-high, reset 0. Ignored with the PRODUCTION + debug-locked straps (§3.2) |
| `scan_mode` | 1 | `1'b0` | |
| `jtag_tck/tms/tdi/trst_n` | 1 each | `0` (TAP held in reset) | OPEN (no TAP endpoint) |
| `jtag_tdo`, `jtag_tdoEn` | 1 each | unconnected | |

**AXI4 subordinate (`s_axi_w_if`, `s_axi_r_if`), flattened in the wrapper**

| Channel | Signals | Driven by |
|---|---|---|
| AW | `awaddr[18:0]`, `awburst`, `awsize`, `awlen`, `awuser[31:0]`, `awid[7:0]`, `awlock`, `awvalid` / `awready` | Mux: fuse ctrl while `fuse_busy`, else bridge. `awburst/awsize/awlen/awid/awlock` always come from the bridge (constants INCR / 2 / 0 / 0 / 0) |
| W | `wdata[31:0]`, `wstrb`, `wuser`, `wvalid` / `wready`, `wlast` | Mux for `wdata/wvalid/wuser`; `wstrb=4'hF`, `wlast=1` from bridge |
| B | `bresp`, `bid`, `buser`, `bvalid` / `bready` | `bresp/bvalid` to both; `bready` muxed; `bid/buser` unconnected |
| AR | `araddr`, `arburst`, `arsize`, `arlen`, `aruser`, `arid`, `arlock`, `arvalid` / `arready` | Bridge only |
| R | `rdata`, `rresp`, `rid`, `ruser`, `rlast`, `rvalid` / `rready` | Bridge only; `rid/ruser/rlast` unconnected |

**AXI manager (DMA), subsystem straps and other ports, all tied off in the wrapper**

| Port group | Tie-off | Reason |
|---|---|---|
| `m_axi_w_if`, `m_axi_r_if` | `awready/wready/arready/bvalid/rvalid = 0`, data/resp/id/user = 0 | Passive: DMA AXI manager must not reach the SoC |
| `strap_ss_caliptra_base_addr`, `strap_ss_mci_base_addr`, `strap_ss_recovery_ifc_base_addr`, `strap_ss_external_staging_area_base_addr`, `strap_ss_otp_fc_base_addr`, `strap_ss_uds_seed_base_addr`, `strap_ss_key_release_base_addr`, `strap_ss_key_release_key_size`, `strap_ss_prod_debug_unlock_auth_pk_hash_reg_bank_offset`, `strap_ss_num_of_prod_debug_unlock_auth_pk_hashes`, `strap_ss_caliptra_dma_axi_user`, `strap_ss_strap_generic_0..3` | `'0` | IS Table 11: subsystem only; tie 0 in passive |
| `ss_debug_intent` | `1'b0` | Subsystem only |
| `ss_ocp_lock_en` | `1'b0` (constant) | OCP LOCK needs subsystem; the runtime log confirms `[rt] OCP LOCK Unsupported` |
| `recovery_data_avail`, `recovery_image_activated` | `1'b0` | Subsystem recovery interface |
| `ss_dbg_manuf_enable`, `ss_soc_dbg_unlock_level`, `ss_generic_fw_exec_ctrl` | unconnected outputs | |
| `trace_rv_*` | unconnected | |
| `itrng_data[3:0]`, `itrng_valid` | `4'h0`, `1'b0` | Internal TRNG not compiled in |
| `generic_input_wires[63:0]` | `64'b0` | |
| `generic_output_wires[63:0]` | `[23:0]` → `status_pio[31:8]` | Log channel |

**Status and interrupts**

| Port | Width | To |
|---|---|---|
| `ready_for_fuses`, `ready_for_mb_processing`, `ready_for_runtime` | 1 each | `status_pio[0..2]`; `ready_for_fuses` also to the fuse ctrl |
| `mailbox_data_avail`, `mailbox_flow_done` | 1 each | `status_pio[3..4]` (polled, no IRQ) |
| `cptra_error_fatal`, `cptra_error_non_fatal` | 1 each | `status_pio[5..6]` (polled, no IRQ) |
| `etrng_req` | 1 | `status_pio[7]` |

**Memories (instantiated inside `caliptra_passive_top`)**

| Memory | Shape | Module |
|---|---|---|
| Mailbox SRAM | `CPTRA_MBOX_DEPTH` × `CPTRA_MBOX_DATA_AND_ECC_W` = 65536 × 39 (256 KiB data + 7-bit ECC; passive size) | `caliptra_sram` |
| ROM (imem) | `CALIPTRA_IMEM_DEPTH` × 64 = 12288 × 64 (96 KiB, `CALIPTRA_IMEM_BYTE_SIZE` = 98304) | `caliptra_rom_m20k`, `$readmemh(ROM_INIT_FILE)` |
| VeeR ICCM / DCCM | 256 KiB each | `caliptra_veer_sram_export` |
| Adams-Bridge (ML-DSA / ML-KEM) | 10 memories via `abr_mem_if` | `abr_mem_top` |

---

## 4. AXI user IDs (AxUSER)

| Agent | AxUSER | Where set | Programmed into |
|---|---|---|---|
| Nios (bridge) | `0x0000_0001` | `NIOS_AXI_USER` → `nios_axi_user` → `avmm_to_axi.user_i` (AWUSER, WUSER, ARUSER) | `CPTRA_MBOX_VALID_AXI_USER[0]` + lock; `CPTRA_TRNG_VALID_AXI_USER` + lock |
| Fuse controller | `0x0000_0002` | `FUSE_AXI_USER` → `soc_fuse_ctrl2x.axi_user` (AWUSER, WUSER) | `CPTRA_FUSE_VALID_AXI_USER` + lock |
| *(reserved)* | `0xFFFF_FFFF` | never driven | IS Table 19: "CANNOT use value 0xFFFFFFFF". It is also the RTL default `CPTRA_DEF_MBOX_VALID_AXI_USER` |

- The IDs are unique per agent and non-zero, as IS Table 19 recommends.
- The RTL integration parameters are left at upstream defaults: `CPTRA_SET_MBOX_AXI_USER_INTEG = 0`, `CPTRA_SET_FUSE_AXI_USER_INTEG = 0`. The IDs are therefore *programmed and locked* by the host on every cold boot (§11, step 4), not hardened at compile time.
- **Fuse range gating.** In `soc_ifc_arb.sv`, SoC requests to `0x30200–0x305FF` (`SOC_IFC_FUSE_START_ADDR`..`_END_ADDR`) are routed only if `valid_fuse_user` is set. Once `CPTRA_FUSE_AXI_USER_LOCK` = 1, that means AxUSER == `CPTRA_FUSE_VALID_AXI_USER` (= 2). So **the Nios (user 1) can neither write nor read fuse registers**. This explains the `FUSE_PQC_KEY_TYPE readback=00000000` seen in the sim ([SIMULATION_2X.md §4.3](SIMULATION_2X.md)).
- `CPTRA_OWNER_PK_HASH[12]` (`0x30140`) and `CPTRA_OWNER_PK_HASH_LOCK` (`0x30170`) are **outside** the fuse range. Any SoC requester can write them until the lock is set. In this design the fuse controller writes and locks them. Note that the Nios could also write them before the lock (see checklist, §13).
- The sim's `+test=axiuser` checks: a mailbox write with AxUSER 3 gives SLVERR; a fuse write with AxUSER 3 gives SLVERR; a fuse write with AxUSER 1 (Nios) gives SLVERR; a `HW_REV_ID` read with AxUSER 1 is accepted (`TB_AXIUSER PASS`).

---

## 5. Memory map

### 5.1 Nios SoC window (20-bit, 1 MiB) — decode in `nios_caliptra2x_top`

The window base in the Nios address space is set by the (not yet created) Platform Designer system. Offsets below are **window offsets** (`cl_address[19:0]`).

| Window offset | Decode (RTL) | Target |
|---|---|---|
| `0x00000–0x3FFFF` | `!a[19] && !a[18]` | `soc_fw_store`: 65536 × 32-bit words (256 KiB), read-only, 1-cycle read. The 2.x bundle uses 63,360 words (253,440 B) |
| `0x40000–0x7EFFF` | — | Unmapped: no waitrequest; read data is not meaningful |
| `0x7F000–0x7FFFF` | `!a[19] && a[18:12]==7'h7F` | `soc_fuse_ctrl2x` MMIO (§7.2) |
| `0x80000–0xFFFFF` | `a[19]` | Caliptra AXI subordinate; **AXI address = `a[18:0]`** |

> The RTL comment in `nios_caliptra2x_top.sv` says "0x80000-0xBFFFF … AXI addr = cl_address[17:0]". The actual decode is `sel_cptra = cl_address[19]`, and the bridge takes `cl_address[AXI_AW-1:0]` with `AXI_AW` = 19. So the whole upper half maps through. Caliptra's targets all sit below AXI `0x40000` for the SoC (see 5.2), so the narrower comment is harmless, but this table follows the RTL.

### 5.2 Caliptra 2.x SoC AXI map (from `caliptra_reg_defines.svh` / `soc_ifc_pkg.sv`, v2.1.2)

Internal addresses are `0x3000_0000 + AXI address` (`SOC_IFC_REG_OFFSET`).

| AXI address | Nios window offset | Block | SoC access |
|---|---|---|---|
| `0x20000–0x20FFF` | `0xA0000` | `mbox_csr` | Valid mailbox AxUSERs |
| `0x21000–0x21FFF` | `0xA1000` | SHA512 accelerator CSR | Only the `SS_CALIPTRA_DMA_AXI_USER` → not usable by the Nios in passive mode |
| `0x22000–0x22FFF` | `0xA2000` | AXI DMA registers | Present in RTL; DMA unused in passive mode |
| `0x30000–0x3FFFF` | `0xB0000` | `soc_ifc` registers | Any requester except the fuse range |
| `0x30200–0x305FF` | `0xB0200` | Fuse registers (subset of `soc_ifc`) | Only `CPTRA_FUSE_VALID_AXI_USER` once locked |

### 5.3 Registers used by the host (verified against `caliptra_reg_defines.svh`)

| Register | AXI | Window | Use |
|---|---|---|---|
| `MBOX_LOCK` | `0x20000` | `0xA0000` | Read to acquire (bit 0 = 0 → acquired) |
| `MBOX_USER` | `0x20004` | `0xA0004` | Expect `0x1` |
| `MBOX_CMD` | `0x20008` | `0xA0008` | `0x46574C44` = FIRMWARE_LOAD |
| `MBOX_DLEN` | `0x2000C` | `0xA000C` | 253,440 |
| `MBOX_DATAIN` | `0x20010` | `0xA0010` | Full-word writes only |
| `MBOX_DATAOUT` | `0x20014` | `0xA0014` | (not used for FW load) |
| `MBOX_EXECUTE` | `0x20018` | `0xA0018` | 1 = execute, 0 = release |
| `MBOX_STATUS` | `0x2001C` | `0xA001C` | `[3:0]` 2 = CMD_COMPLETE |
| `CPTRA_HW_ERROR_FATAL` / `_NON_FATAL` | `0x30000` / `0x30004` | `0xB0000` / `0xB0004` | RW1C |
| `CPTRA_FW_ERROR_FATAL` / `_NON_FATAL` | `0x30008` / `0x3000C` | `0xB0008` / `0xB000C` | RW1C |
| `CPTRA_BOOT_STATUS` | `0x30038` | `0xB0038` | |
| `CPTRA_FLOW_STATUS` | `0x3003C` | `0xB003C` | |
| `CPTRA_SECURITY_STATE` | `0x30044` | `0xB0044` | Sim read `0x00000007` = Production + debug locked |
| `CPTRA_MBOX_VALID_AXI_USER[0]` / `CPTRA_MBOX_AXI_USER_LOCK[0]` | `0x30048` / `0x3005C` | `0xB0048` / `0xB005C` | 1 / 1 |
| `CPTRA_TRNG_VALID_AXI_USER` / `CPTRA_TRNG_AXI_USER_LOCK` | `0x30070` / `0x30074` | `0xB0070` / `0xB0074` | 1 / 1 |
| `CPTRA_TRNG_DATA[0..11]` | `0x30078–0x300A4` | `0xB0078–0xB00A4` | 12 entropy words |
| `CPTRA_TRNG_CTRL` | `0x300A8` | `0xB00A8` | (not used) |
| `CPTRA_TRNG_STATUS` | `0x300AC` | `0xB00AC` | Write 2 = `DATA_WR_DONE` |
| `CPTRA_FUSE_WR_DONE` | `0x300B0` | `0xB00B0` | Written 1 by the fuse ctrl (its `FUSE_WR_DONE` parameter `32'h0003_00B0`) |
| `CPTRA_TIMER_CONFIG` | `0x300B4` | `0xB00B4` | 20000 (ps period for 50 MHz) |
| `CPTRA_BOOTFSM_GO` | `0x300B8` | `0xB00B8` | (only with `BootFSM_BrkPoint`=1) |
| `CPTRA_HW_REV_ID` | `0x300D4` | `0xB00D4` | Sim read `0x00000212` |
| `CPTRA_HW_CONFIG` | `0x300E0` | `0xB00E0` | Sim read `0x00000010` (`iTRNG_en`=0, `SUBSYSTEM_MODE_en`=0) |
| `CPTRA_FUSE_VALID_AXI_USER` / `CPTRA_FUSE_AXI_USER_LOCK` | `0x30108` / `0x3010C` | `0xB0108` / `0xB010C` | 2 / 1 |
| `CPTRA_WDT_CFG[0]` / `[1]` | `0x30110` / `0x30114` | `0xB0110` / `0xB0114` | 100,000,000 / 0 |
| `CPTRA_OWNER_PK_HASH[0..11]` | `0x30140–0x3016C` | — | Written by the fuse ctrl |
| `CPTRA_OWNER_PK_HASH_LOCK` | `0x30170` | `0xB0170` | Written 1 by the fuse ctrl |

---

## 6. `avmm_to_axi` bridge

- **Avalon side:** waitrequest + readdatavalid agent, with no bursts and no pipelining. `avs_byteenable` is ignored because Caliptra SoC registers are 32-bit.
- **AXI side:** single beat, `AxLEN=0`, `AxSIZE=2` (32-bit), `AxBURST=INCR` (`2'b01`), `AxLOCK=0`, `AxID=0`, `WSTRB=4'hF`, `WLAST=1`. `AWUSER = WUSER = ARUSER = user_i`. The address is word-aligned (`{a[AW-1:2],2'b00}`).
- **One outstanding transaction.** States: `IDLE → WADDR → WRESP → DONE` for writes and `IDLE → RADDR → RDATA → DONE → RESP` for reads. AW and W are issued together, and each drops on its own handshake.
- **Avalon handshake:** `avs_waitrequest` is low for exactly one cycle (`DONE`) to accept. Read data comes one cycle later with `avs_readdatavalid` (`RESP`).
- **Errors:** `BRESP`/`RRESP` ≠ OKAY sets `err_q`, so `avs_response = 2'b10` (SLVERR) for the last transaction. The TB reads `u_bridge.err_q` directly for the AxUSER test. **In `nios_caliptra2x_top.sv` the bridge's `avs_response` drives `cl_response`, but `cl_response` is not connected to any `nios_caliptra2x_sys` port.** So SLVERR does not reach the Nios today. Adding a `caliptra_axi_response` port to the PD window is an open item (§15).
- **Spec fit (IS "Unsupported features"):** single outstanding, in order, no narrow writes to `mbox_datain` / `TRNG_DATA`. AxCACHE/PROT/REGION/QOS are not driven.
- **`idle` output:** high in `IDLE`, intended for warm-reset quiescing. It is not yet used by the top.

---

## 7. `soc_fuse_ctrl2x` — fuse sequencer

### 7.1 Image format (`caliptra2x/fw_2x/fuse_image_2x.hex`)

- Each line is one `$readmemh` 64-bit word, `{AXI byte address[31:0], data[31:0]}`, for example the first line `00030200811944f5` (`FUSE_UDS_SEED[0]`) and the last line `0003017000000001` (`CPTRA_OWNER_PK_HASH_LOCK` = 1). Addresses are explicit because the 2.x fuse map has holes.
- The controller truncates the address to `AW` = 19 bits.
- 117 entries: 104 fuse words, then 12 `CPTRA_OWNER_PK_HASH` words, then `CPTRA_OWNER_PK_HASH_LOCK = 1`. The controller then appends `CPTRA_FUSE_WR_DONE = 1` itself (`addr = FUSE_WR_DONE = 0x300B0`). That makes **118 AXI writes**.

### 7.2 MMIO (window `0x7F000`, 4 KiB, word registers)

| Offset | Name | Access | Bits |
|---|---|---|---|
| `0x00` | ID | RO | `0x4655_5345` ("FUSE") |
| `0x04` | CTRL | WO | bit0 **START**, bit1 **CLEAR** (clears DONE/ERR), bit2 **START_DONE** |
| `0x08` | STATUS | RO | bit0 BUSY, bit1 DONE, bit2 ERR, bit3 READY_FOR_FUSES |
| `0x0C` | COUNT | RO | AXI writes completed (118 after a full START) |
| `0x10` | FW_BYTES | RO | `FW_BYTES` parameter (253,440) |
| `0x14` | NUM_FUSES | RO | `NUM_FUSES` parameter (117) |

### 7.3 Behaviour

- **START** (cold boot) replays entries 0..116, then `FUSE_WR_DONE`.
- **START_DONE** (warm reset) starts with `idx = NUM_FUSES`, which is "last", so it writes **only** `FUSE_WR_DONE = 1`. Fuse registers and `CPTRA_OWNER_PK_HASH*` are pwrgood-domain and persist across a warm reset. START wins if both bits are set.
- START or START_DONE while `ready_for_fuses` = 0 leads to `ERR`, with no writes.
- Any write with `BRESP` ≠ OKAY leads to `ERR`, and the sequence stops (`COUNT` shows how far it got).
- While `busy` is set (NEXT/SEND/RESP), the top muxes AW/W/B to the fuse controller. The Nios only polls the fuse ctrl STATUS (a local slave) meanwhile, so the bridge is idle. The read channels always belong to the bridge.
- Measured in sim: START issued just after cycle 136, `STATUS=00000002 COUNT=118` at cycle 614, so about 4 cycles per write.

---

## 8. Fuse map decode (what `gen_fuse_image_2x.py` writes)

Offsets are verified against `caliptra_reg_defines.svh` (`CLP_SOC_IFC_REG_*`, minus `0x3000_0000`). The access column is from `soc_ifc_fuse_reg.rdl` / `soc_ifc_external_reg.rdl`.

| AXI addr | Register | Words | Value written | Notes |
|---|---|---:|---|---|
| `0x30200` | `FUSE_UDS_SEED[0..15]` | 16 | STUDY: `0x1F2E3D4C ^ (0x9E3779B9·(i+1))` → `811944f5 2340ce3e … fc59a6dc` | **512-bit** in 2.x (384 in 1.x). Caliptra: no access; SoC: WL-S (write-only). **TEST-ONLY** |
| `0x30240` | `FUSE_FIELD_ENTROPY[0..7]` | 8 | STUDY: `0xA7C3E519 ^ (0x85EBCA6B·(i+1))` → `22282f72 ac1471cf … 889db641` | 256-bit. **TEST-ONLY** |
| `0x30260` | `FUSE_VENDOR_PK_HASH[0..11]` | 12 | SHA-384(`preamble.vendor_pub_key_info`) as 12 big-endian words → `30399676 a17e3e97 3677b3ff 862f4bf2 d1932d88 4778453c 376fe00d c93fb8aa 0770f3eb f3411a08 53e9c57e ce8a2980` | Hash of the ECC + PQC key *descriptors* (1,736 B). ROM rejects an all-zero value |
| `0x30290` | `FUSE_ECC_REVOCATION` | 1 | 0 | 4-bit field |
| `0x302B4` | `FUSE_FMC_KEY_MANIFEST_SVN` | 1 | 0 | |
| `0x302B8` | `FUSE_RUNTIME_SVN[0..3]` | 4 | 0 | Bundle header SVN must be ≥ fuse SVN; the bundle SVN is 0 |
| `0x302C8` | `FUSE_ANTI_ROLLBACK_DISABLE` | 1 | 0 | |
| `0x302CC` | `FUSE_IDEVID_CERT_ATTR[0..23]` | 24 | 0 | |
| `0x3032C` | `FUSE_IDEVID_MANUF_HSM_ID[0..3]` | 4 | 0 | |
| `0x30340` | `FUSE_LMS_REVOCATION` | 1 | 0 | |
| `0x30344` | `FUSE_MLDSA_REVOCATION` | 1 | 0 | |
| `0x30348` | `FUSE_SOC_STEPPING_ID` | 1 | 1 | Test value |
| `0x3034C` | `FUSE_MANUF_DBG_UNLOCK_TOKEN[0..15]` | 16 | 0 | Debug unlock is subsystem-only |
| `0x3038C` | `FUSE_PQC_KEY_TYPE` | 1 | **1** = manifest `pqc_key_type` | RDL: 2-bit, "one-hot", bit0 = MLDSA, bit1 = LMS. The ROM compares it with `FwVerificationPqcKeyType::from_u8()` (MLDSA = 1, LMS = 3). Skipped only when Unprovisioned |
| `0x30390` | `FUSE_SOC_MANIFEST_SVN[0..3]` | 4 | 0 | Unused in passive |
| `0x303A0` | `FUSE_SOC_MANIFEST_MAX_SVN` | 1 | 0 | |
| `0x303C0` | `FUSE_HEK_SEED[0..7]` | 8 | 0 | OCP LOCK; unused (`ss_ocp_lock_en`=0) |
| | **Fuse words subtotal** | **104** | | Holes at `0x294–0x2B0` and `0x3A4–0x3BC` are skipped |
| `0x30140` | `CPTRA_OWNER_PK_HASH[0..11]` | 12 | SHA-384(`preamble.owner_pub_keys`) → `48afdb07 3c5e0d4e e4649046 8ef81f2c f57249b6 e76a28f5 fca4de69 6a7d3e2e d3efc4e6 77431854 3e95307a 54988bd7` | **Not a fuse in 2.x.** Architectural register, `resetsignal = cptra_pwrgood`, SoC RWL-S |
| `0x30170` | `CPTRA_OWNER_PK_HASH_LOCK` | 1 | 1 | RW1-S; reset only by power cycle |
| `0x300B0` | `CPTRA_FUSE_WR_DONE` | (1) | 1 | Appended by the controller, not in the image |

**Owner key and entropy, in plain words:**
- The **owner key hash is provisioned**, written to `CPTRA_OWNER_PK_HASH` and locked. The sim read back `[0]=48afdb07` and `LOCK=1`. The ROM then verified the image against it.
- **UDS and field entropy are provisioned** with STUDY values (not secrets). The SoC cannot read them back (write-only), and the Nios can't access the fuse range anyway.
- There is no `FUSE_LIFE_CYCLE` in 2.x. Lifecycle comes only from the `security_state` straps (Production, debug locked).

---

## 9. TRNG (external, serviced by the host)

### 9.1 Hardware path

- `CALIPTRA_INTERNAL_TRNG` is not defined. `CPTRA_HW_CONFIG.iTRNG_en` = 0. `itrng_*` are tied 0.
- When Caliptra firmware wants entropy, it raises `etrng_req` (`status_pio[7]`).
- The host writes 12 words to `CPTRA_TRNG_DATA[0..11]` (`0x30078–0x300A4`), then writes `CPTRA_TRNG_STATUS = 2` (`DATA_WR_DONE`, `0x300AC`).
- Writes must come from `CPTRA_TRNG_VALID_AXI_USER` (= 1, locked). `DATA_WR_DONE` is hardware-cleared when Caliptra FW clears `DATA_REQ` (`soc_ifc_top.sv`).

### 9.2 Entropy source — **TEST-ONLY**

- **Sim:** the TB host model writes `$urandom` values. In the 1.x Nios firmware, `main.c` uses `xorshift32` seeded `0x1234ABCD`. The 2.x Nios firmware port would keep that (it isn't ported yet).
- Neither source is a real entropy source. IS §TRNG: *"It is a requirement for FIPS compliance that this TRNG HW API is always handled by SoC hardware gasket logic (and not some SoC ROM or firmware code)."*
- **Production options:** a hardware ETRNG gasket fed by a physical noise source, or `CALIPTRA_INTERNAL_TRNG` with a PTRNG on `itrng_data/itrng_valid`.

### 9.3 Sim numbers

- **217** requests serviced in one boot.
- The first was at cycle 379,157.
- 21 had been serviced by `ready_for_mb_processing`.
- The TB fails if `etrng_req` stays high for 100,000 cycles after `DATA_WR_DONE`; that never happened.

---

## 10. Reset, power-good, watchdog, errors

### 10.1 Resets

| Event | How | Effect |
|---|---|---|
| FPGA configuration | Reset Release IP holds `ninit_done`=1 → `sys_reset_n`=0 | PD system in reset (`reset_reset_n`=0). `glue_rst_n`=0 (async). `raw_pwrgood`=`raw_rst_b`=0, so `cptra_rst_b`=0 (async) and `cptra_pwrgood`=0 (2 `clk` after; it was never raised) |
| Board reset | `reset_n`=0 → `sys_reset_n`=0 | PD system reset; the ctrl PIO returns to 0. `glue_rst_n`=0 (async). `cptra_rst_b`=0 (async), and `cptra_pwrgood` falls 2 `clk` edges later (needs `clk` running). The result is a Caliptra **cold** reset |
| Caliptra cold reset | Host clears `ctrl[0]` (and `[1]`), then sets `ctrl=1` → wait → `ctrl=3` | pwrgood-domain state cleared (fuses, owner hash + lock, AxUSER locks) → full fuse push needed |
| Caliptra warm reset | Host clears only `ctrl[1]`, then sets it again | Fuses/owner hash persist; host must issue fuse ctrl **START_DONE** in `BOOT_FUSE`. **Not simulated in 2.x** |

- Both Caliptra resets use `reset_sync.sv` cells (2 stages, `SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS`):
  - `cptra_rst_b` (active-low): 1→0 is asynchronous, and 0→1 is synchronized (2 `clk`).
  - `cptra_pwrgood` (active-high): 0→1 is asynchronous, and 1→0 is synchronized (2 `clk`). This follows IS Table 4 literally ("Asynchronous Assertion, Synchronous deassertion to clk").
- **Note on pwrgood.** The IS RDC table also lists `CPTRA_PWRGD` as an async, active-low reset. Seen that way, the 0→1 edge of `cptra_pwrgood` is the reset *release*, and this cell does not synchronize it. Here that edge always comes from the ctrl PIO flop, which is clocked by `clk` (`sys_reset_n` cannot raise it, because the PIO is 0 when `sys_reset_n` rises), so it is already synchronous. Keep that property if the source changes.
- In the sim, pwrgood is raised and then `rst_b` follows 20 cycles later (`cold_release()`). That is above IS Table 19's 10-clock minimum.

### 10.2 Watchdog

- The host writes `CPTRA_WDT_CFG[0] = 100,000,000` and `CPTRA_WDT_CFG[1] = 0` before fuses.
- The debug-locked ROM uses them: the log shows `[state] Starting the WD Timer 100000000 cycles` at cycles 384,577 and 450,858.
- There are no WDT pins. A cascaded timeout shows up as `cptra_error_fatal`.

### 10.3 Errors

- `cptra_error_fatal` / `_non_fatal` are polled on `status_pio[5:6]`.
- The TB host clears non-fatal errors by RW1C (`HW/FW_ERROR_NON_FATAL`), and treats any fatal as a test FAIL. It dumps BOOT/FLOW status and the error registers.
- **The spec rule is to recover from a fatal error only by a pwrgood cycle.** The 1.x firmware does this (≤3 retries). The 2.x TB does **not** exercise fatal recovery.
- At `ready_for_runtime`, every HW/FW fatal and non-fatal register was 0, and `CPTRA_FLOW_STATUS = b8000000`.

---

## 11. Boot sequence

```mermaid
sequenceDiagram
  participant N as Nios host
  participant F as soc_fuse_ctrl2x (AxUSER 2)
  participant C as Caliptra 2.x
  N->>C: ctrl=1 (pwrgood), 20 clk, ctrl=3 (rst_b)
  C-->>N: ready_for_fuses (cycle 40)
  N->>C: read HW_REV_ID, HW_CONFIG, SECURITY_STATE
  N->>C: FUSE_VALID_AXI_USER=2 + lock, TRNG_VALID_AXI_USER=1 + lock, MBOX_VALID_AXI_USER[0]=1 + lock
  N->>C: TIMER_CONFIG=20000, WDT_CFG0=100000000, WDT_CFG1=0
  N->>F: CTRL.START
  F->>C: 104 fuse words, OWNER_PK_HASH[12], OWNER_PK_HASH_LOCK, FUSE_WR_DONE (118 writes)
  N->>F: poll STATUS until DONE (COUNT=118, cycle 614)
  loop ROM KATs and FW
    C-->>N: etrng_req
    N->>C: TRNG_DATA[0..11], TRNG_STATUS=2
  end
  C-->>N: ready_for_mb_processing (5,542,288)
  N->>C: MBOX_LOCK, CMD=0x46574C44, DLEN=253440, DATAIN x 63360, EXECUTE=1 (6,049,774)
  C-->>N: MBOX_STATUS=2 CMD_COMPLETE (21,319,080), then N writes EXECUTE=0
  Note over C: image verified 17,010,257, FMC 27,820,645, RT 36,217,560
  C-->>N: ready_for_runtime (36,597,957)
```

**Host sequence, step by step.** This is the TB behavioral host `nios_caliptra2x_sys`, which is the reference for the future `main.c` port.

1. Wait until the Reset Release IP releases `sys_reset_n`.
2. `ctrl = 1` (pwrgood), wait 20 clk, `ctrl = 3` (rst_b).
3. Poll `status[0]` (`ready_for_fuses`). Read `HW_REV_ID` (expect `0x212`), `HW_CONFIG` (expect `iTRNG_en=0`, `SUBSYSTEM_MODE_en=0`) and `CPTRA_SECURITY_STATE` (expect `7`).
4. Program and lock the AxUSERs: `FUSE_VALID_AXI_USER=2` + lock, `TRNG_VALID_AXI_USER=1` + lock, `MBOX_VALID_AXI_USER[0]=1` + lock. Then `TIMER_CONFIG=20000` and `WDT_CFG0=100,000,000`, `WDT_CFG1=0`.
5. Fuse ctrl: check ID `0x46555345`, write `CTRL=1` (START), poll `STATUS` until !BUSY and (DONE|ERR). Expect `COUNT=118`, then confirm `FUSE_WR_DONE=1` and `OWNER_PK_HASH_LOCK=1`.
6. Throughout steps 6–9: service `etrng_req` (§9), RW1C-clear non-fatal errors, and stop on fatal.
7. Poll `status[1]` (`ready_for_mb_processing`). Read `FW_BYTES` from fuse ctrl `0x10`.
8. Poll `MBOX_LOCK` until bit 0 = 0, and check `MBOX_USER = 1`. Write `MBOX_CMD=0x46574C44` and `MBOX_DLEN=253440`. Then for each of 63,360 words: read `soc_fw_store[i]` and write `MBOX_DATAIN`. Then write `MBOX_EXECUTE=1`.
9. Poll `MBOX_STATUS[3:0]` until non-zero, expect 2 (CMD_COMPLETE), then write `MBOX_EXECUTE=0`.
10. Poll `status[2]` (`ready_for_runtime`), then write magic `0xCA11F00D` (on the LEDs: `0x0D`).

The magic/LED codes the TB uses are 1 = start, 2 = ready_for_fuses, 3 = AxUSER programmed, 4 = fuses done, 5 = ready_for_mb_processing, 6 = FW_LOAD issued, 7 = mailbox complete, `0xCA11F00D` = runtime.

**Note on clocks.** The TB clock is 100 MHz (`#5`), but `TIMER_CONFIG=20000` ps assumes 50 MHz. This only affects Caliptra's MTIME scaling, not the boot result. Set `TIMER_CONFIG` to match the real board clock.

---

## 12. Changes vs. the 1.x design

| Area | 1.x (rev 3) | 2.x (this design) |
|---|---|---|
| Bus | APB, 18-bit, PAUSER | AXI4, 19-bit, AxUSER (32-bit) |
| Bridge | `avmm_to_apb` | `avmm_to_axi` |
| Window | 256 KiB (18-bit) | 1 MiB (20-bit) |
| Requester IDs | One shared PAUSER = 1 | Nios = 1, fuse ctrl = 2 (unique) |
| Fuses | 83 words, data-only image | 104 words + 12 owner hash + lock, address/data image, 117 entries |
| Owner PK hash | Fuse `FUSE_OWNER_PK_HASH` | Register `CPTRA_OWNER_PK_HASH[12]` + `_LOCK` (pwrgood) |
| Lifecycle | `FUSE_LIFE_CYCLE` + straps | Straps only |
| Ready signal | `ready_for_fw_push` | `ready_for_mb_processing`; both on `status_pio` bit 1, active-high |
| Mailbox | 128 KiB | 256 KiB |
| ROM / ICCM / DCCM | 48 / 128 / 128 KiB | 96 / 256 / 256 KiB |
| PQC | LMS optional | ML-DSA-87 (Adams-Bridge) or LMS, selected by `FUSE_PQC_KEY_TYPE` |
| New tie-offs | — | `strap_ss_*`, `ss_debug_intent`, `ss_ocp_lock_en`, obf UDS/FE, recovery, DMA AXI manager, `cptra_csr_hmac_key` (new strap) |
| FW bundle | 109,000 B | 253,440 B |

---

## 13. Compliance checklist vs. caliptra-rtl v2.1.2 Integration Specification

References: IS Table 4 (clocks/resets), Table 5 (AXI), Tables 11–13 (straps, generic wires), §TRNG, Table 19 (SoC integration requirements), and `soc_ifc` RDL. The status reflects the **2.x RTL glue plus the TB host sequence**. The Nios firmware for 2.x is not ported yet.

| Requirement | Spec ref | Implementation | Status |
|---|---|---|---|
| Clock running before / ≥10 clk around `cptra_pwrgood` | Table 19 Resets and Clocks | Free-running clk; TB 20 clk pwrgood→rst_b | **PASS** (sim) |
| Async assert / sync deassert of pwrgood, rst_b | Table 4 / RDC | `reset_sync.sv` 2FF cells: `rst_b` 1→0 async, 0→1 sync; `pwrgood` 0→1 async, 1→0 sync (literal Table 4; the 0→1 source is a `clk` flop, §10.1) | **PASS** |
| Agilex Reset Release before user logic | Intel A5E | `rst_release` gates `sys_reset_n` | **PASS** (stub in sim) |
| AXI single outstanding, in order, no narrow `mbox_datain`/`TRNG_DATA` | IS Unsupported features | `avmm_to_axi` single-beat, `WSTRB=F` | **PASS** |
| Drive AxUSER on all requests; never `0xFFFFFFFF` | Table 19 AXI USER | Nios 1, fuse 2 | **PASS** |
| AxUSER unique per agent, non-zero | Table 19 AXI USER | 1 vs 2 | **PASS** |
| Mailbox AxUSER programmed + locked before use | Table 19 MAILBOX rules | Step 4, before any mailbox access | **PASS** (sim; ideally done by immutable SoC ROM) |
| TRNG AxUSER programmed + locked | Table 19 TRNG rules | Step 4 | **PASS** |
| Fuse AxUSER locked or hardened | Table 19 FUSE rules | Programmed + locked to 2; `CPTRA_SET_FUSE_AXI_USER_INTEG=0` | **PASS** (programmable; hardening optional) |
| Fuse writes + `FUSE_WR_DONE` by immutable logic or ROM | Table 19 Fuses | `soc_fuse_ctrl2x` FSM, but the image is a rebuildable hex in FPGA RAM | **TEST-ONLY** |
| UDS/FE from OTP, no debug inject path | Table 19 Fuses | STUDY values in a hex image | **TEST-ONLY** |
| Debug read paths for fuses disabled in Production | Table 19 Fuses | Fuse range gated to user 2; UDS/FE write-only; but the hex image is readable in the bitstream | **TEST-ONLY** |
| Owner PK hash written + locked before mutable code | `soc_ifc_external_reg.rdl` | Fuse ctrl writes + locks (pwrgood-sticky); Nios could write it in the window before START | **PASS** (study); production: write from immutable logic before the host CPU can reach AXI |
| Warm reset: SoC re-writes `FUSE_WR_DONE` only | IS Fuses / Boot FSM | `START_DONE` implemented | **OPEN** (not simulated in 2.x) |
| Security state from the SoC's security state | Table 19 Security State | Hardwired Production + debug locked | **TEST-ONLY** |
| Obfuscation key: NIST-generated, not software, off scan, stable before reset | Table 19 Obfuscation Key | Fixed study localparam | **TEST-ONLY** |
| CSR HMAC key generated/rotated per project | Table 19 CSR HMAC Key | Fixed study constant (latched only in MANUFACTURING) | **TEST-ONLY** |
| Subsystem straps / `ss_*` / obf UDS/FE / recovery tied 0 in passive | Tables 11–12 | Tied in `caliptra_passive_top` | **PASS** |
| `ss_ocp_lock_en` constant | Table 11 | `1'b0` | **PASS** |
| DMA AXI manager not connected in passive | IS DMA / AXI arbitration | Ready/valid tied 0 | **PASS** |
| `generic_input_wires` bit 0 = zeroization status; others 0 | Table 13 | `64'b0` | **PASS** |
| TRNG serviced by a hardware gasket (FIPS) | IS §TRNG | Host firmware/TB model, pseudo-random data | **TEST-ONLY** |
| Report Caliptra error outputs | Table 19 Error reporting | Polled on `status_pio[5:6]`; not a Nios IRQ | **OPEN** (IRQ) |
| Recover fatal only via pwrgood reset | Table 19 Error reporting | Planned: clear `ctrl[0]`/`[1]`, re-raise, full fuse push (the 1.x `main.c` does this with ≤3 retries); not in the 2.x TB | **OPEN** |
| SoC programs WDT before debug-locked ROM | HW spec WDT | `WDT_CFG` written before fuses; ROM log confirms | **PASS** |
| `TIMER_CONFIG` programmed | `soc_ifc` RDL | 20000 ps (50 MHz) | **PASS** (TB clock is 100 MHz; set per board) |
| `scan_mode` 0 functional; 1 for 5,000 clk before scan | Table 19 DFT | Tied 0, no scan | **PASS** (FPGA) |
| Caliptra TAP as a TAP endpoint | Table 19 DFT | Tied off | **OPEN** |
| Input clock from an on-die oscillator; clock-attack defence | Table 19 Resets and Clocks | Board clock | **OPEN** |
| No independent power-gating; clock gating via Caliptra FW | Table 19 Power saving | Clock ungated | **PASS** |
| SRAM zeroization on pwrgood | IS SRAM | Not implemented (bitstream-time zero only) | **OPEN** |
| Synthesis integrity (`u__size_only__` prims preserved) | IS Synthesis constraints | Not yet addressed in the Quartus flow | **OPEN** |
| Device fits | — | 126 % ALMs on A5E 065 | **FAIL** (§14) |

**Summary:** 32 rows: 17 PASS, 7 OPEN, 7 TEST-ONLY, 1 FAIL (fit). Every TEST-ONLY item is intentional for a study and must be replaced for a product.

---

## 14. A5E 065 fit result and options

From [`docs/caliptra-2x/P1_FIT_RESULT_2X_A5E.md`](P1_FIT_RESULT_2X_A5E.md). Quartus Prime Pro 25.3.0 b109, Analysis & Synthesis only. The top is `caliptra2x/rtl_2x/caliptra_passive_top.sv` (Caliptra core only, **no Nios**). `MLDSA_MASKING` is on (upstream default).

| Resource | 2.x synth | A5EC065 | % | 1.x (Nios project†) |
|---|---:|---:|---:|---:|
| **ALMs needed (pre-fit estimate)** | **279,685** | **222,400** | **125.8 %** | 138,715 |
| Combinational ALUTs | 395,094 | — | — | 218,761 |
| Dedicated logic registers | 411,569 | 889,600 | 46.3 % | 141,933 |
| Block memory bits | 9,005,696 | 31.46 Mb | ≈ 28.6 % | ≈ 5.67 Mb |
| M20K (estimate) | ≈ 484 | 1,611 | ≈ 30 % | — |
| DSP (synth / est. post-merge) | 213 / 199 | 846 | 25.2 % / 23.5 % | 49 |

† The 1.x column is the `quartus_a5e_nios/` project: Nios V plus Caliptra 1.x, synthesized with Quartus Prime Pro 25.3.0 b109 (Analysis & Synthesis only; source: `CALIPTRA_2X_INTEGRATION_PLAN.md` §3.1). Its scope differs by row:
- **ALMs and block memory:** the whole design (`nios_caliptra_a5e.syn.summary`: 138,715 ALMs).
- **ALUTs and registers:** the `caliptra_top` hierarchy row only.
- **DSP:** 49 in synthesis (47 post-merge).

So this column is **not** the same top as the 2.x column, which is the core-only `caliptra_passive_top`. For a like-for-like comparison, the 1.x core-only wrapper (`quartus_a5e/`, `caliptra_a5e.syn.summary`) estimates 141,256 / 222,400 ALMs (64 %), 142,373 registers and 47 DSP post-merge.

- **Biggest consumer: Adams-Bridge** (`abr_inst`): 101,640 ALUTs, 244,925 FFs, 164 DSP. The masked NTT `hybrid_bf2x2` alone has 218,303 FFs.
- **Next:** `ecc_top1` (79,991 ALUTs), VeeR (55,132), key vault (51,019).
- **Over by 57,285 ALMs.** Even a 20 % packing gain leaves the design at ≥ 100 %. The Nios system would add more.

**Options**

| Option | Fits | Spec-conformant | Comment |
|---|---|---|---|
| **A. Agilex 7** (e.g. AGF/AGI 014 ≈ 487k ALMs, ~57 % on this estimate; 022/027 for margin) | Yes | Yes | Unmodified `caliptra2x/rtl_2x/` + caliptra-rtl v2.1.2 RTL; change FAMILY/DEVICE in `caliptra2x/quartus_a5e_2x/caliptra2x_a5e.qsf` (and `gen_qsf.py` if you regenerate it); new PD/pins |
| **B. Simulation-only 2.x** (keep Caliptra 1.x in A5E hardware) | n/a | Yes | Develop the glue, firmware and tooling in Verilator / sw-emulator now |
| **C. Unmasked / reduced test build** (`MLDSA_MASKING` undefined and/or `RV_FPGA_OPTIMIZE`) | Unknown, untested | **No**: removes side-channel countermeasures | Per the plan, upstream `MLDSA_MASKING` mainly zeroes the randomness; real savings may need an RTL fork. Research only |

---

## 15. Open items

1. Create the Platform Designer system `nios_caliptra2x_sys`: Nios V/m, on-chip RAM, JTAG UART, ctrl/status/magic PIOs, and an exported 20-bit Avalon `mm_bridge` named `caliptra_axi`.
2. Port `main.c` to the §11 sequence: 2.x register names, AxUSER programming, `ready_for_mb_processing`, 253,440-byte load, warm-reset START_DONE with bridge quiesce, and fatal pwrgood recovery.
3. Add 2.x `warm` and `fatal` Verilator tests, as in the 1.x suite.
4. Choose the hardware target (Agilex 7 vs. sim-only), then do a full fit, timing, and synthesis-integrity constraints.
5. Production replacements for every TEST-ONLY row: OTP fuses, a real lifecycle, an HSM-generated obfuscation and CSR HMAC key, a hardware TRNG, and own signing keys ([FIRMWARE_AND_KEYS_2X.md](FIRMWARE_AND_KEYS_2X.md)).
6. Export the bridge's Avalon `response` (`cl_response`, 2'b10 = SLVERR) as a `caliptra_axi_response` port of `nios_caliptra2x_sys`. Today it is left unconnected in `nios_caliptra2x_top.sv`, so the Nios cannot see AXI errors.

---

## 16. Getting the sources

The upstream Caliptra RTL is **not copied into this repo**. It comes in as pinned git submodules under `external/`, used unmodified. Every FPGA-specific change lives in this repo.

| Path | What | Version / commit |
|---|---|---|
| `external/caliptra-rtl-1x/` | chipsalliance/caliptra-rtl (submodule) | **v1.1**, `5f85fb4bc95b753a2f7d042db7dc2644ca1e8c49` |
| `external/caliptra-rtl-2x/` | chipsalliance/caliptra-rtl (submodule) | **v2.1.2**, `49370266d12cb0c4a8f71b3a0ff7e54ba7d4866e` |
| `external/caliptra-rtl-2x/submodules/adams-bridge/` | chipsalliance/adams-bridge (nested submodule) | v2.0.3, `b77e3d899e828d626cfc2a0d26a6b5704cc121e0` |
| `rtl/`, `quartus/syn_src/` | 1.x passive wrapper + synthesis overrides (`caliptra_sram`, `caliptra_top_tb_pkg`, `caliptra_veer_sram_export`) | this repo |
| `quartus_a5e_nios/` | Nios V + Caliptra 1.x Quartus project: `rtl/` glue, `qsys/` Platform Designer system (generated output committed), `ip/rst_release.ip`, `sw/` BSP + app, `onchip_mem.hex` | this repo |
| `quartus_a5e/` | Caliptra 1.x core-only Quartus project (size study) | this repo |
| `fw/` | 1.x ROM (rom-1.1.1), signed FW bundle, fuse image | this repo |
| `sim/` | Verilator TB for the 1.x Nios glue | this repo |
| `caliptra2x/` | 2.x glue (`rtl_2x/`), sim (`sim_2x/`, `sim/`), firmware (`fw_2x/`), fuse script (`scripts/`), core-only Quartus project (`quartus_a5e_2x/`) | this repo |
| `scripts/get_caliptra_a5e.sh` | Clone or update this repo with all submodules, then verify the pins | this repo |
| `scripts/fetch_deps.sh` | `git submodule update --init --recursive` (or clone the pinned commits if there is no `.git`), then verify; `--check` verifies only | this repo |
| `scripts/quartus_docker.sh` | Run any Quartus command in the Quartus Pro 25.3 Docker image with the repo and license mounted | this repo |

All paths in the `.qsf`, `.f` and run scripts are **relative to the file's own directory**, so the checkout can be anywhere. If Quartus reports `caliptra_passive_top` or `caliptra_top` as undefined, the submodules are missing: run `scripts/fetch_deps.sh`.

**Download** (macOS or Linux; needs git; about 1 GB with both RTL trees):

```bash
# Option A: one script (clones, or updates an existing clone with pull + submodule update, then checks pins)
curl -fsSLO https://raw.githubusercontent.com/pwilliam282/caliptra-a5e-quartus/main/scripts/get_caliptra_a5e.sh
bash get_caliptra_a5e.sh ~/work/caliptra-a5e-quartus

# Option B: plain git
git clone --recursive https://github.com/pwilliam282/caliptra-a5e-quartus.git
cd caliptra-a5e-quartus
scripts/fetch_deps.sh            # expect: ok ... x3, "deps OK"
```

If you cloned without `--recursive`, or downloaded a ZIP, run `scripts/fetch_deps.sh` anyway.

---

## 17. Quartus build

**Tools and host.**
- Quartus Prime **Pro 25.3.0 Build 109** with Agilex 5 device support. All results in this guide come from that version.
- Quartus Pro runs only on **Linux or Windows x86-64**. On a Mac (including Apple-silicon MacBooks), use the Mac for git and editing, and run Quartus on a Linux x86-64 PC, VM or server. The Docker image is `linux/amd64` and is not usable under emulation on Apple-silicon Docker Desktop.
- Docker option: the official image `alterafpga/quartuspro-v25.3:agilex5`, wrapped by `scripts/quartus_docker.sh <dir> '<command>'`. The wrapper mounts the whole repo (including `external/`) at the same path, mounts your license read-only, runs as your UID, and uses `--net=host`.

**License.** The A5EC065 needs the no-cost **SW-AGILEX-5E** license from Altera's Self-Service Licensing Center. It is node-locked to the NIC MAC address of the machine that runs Quartus. In Docker this works because of `--net=host`: FlexLM reads the host NIC, and without it `quartus_syn` can segfault in the host-ID lookup. Point the tools at the file:
- Native: `export LM_LICENSE_FILE=/path/to/SW-AGILEX-5E.dat`
- Docker: `export LIC_HOST=/path/to/SW-AGILEX-5E.dat`, or put the file at `license/SW-AGILEX-5E.dat` in the repo (gitignored)

Never commit license `.dat` files.

**Projects.**

| Project | Directory | `.qpf` / revision | Top |
|---|---|---|---|
| Nios V + Caliptra 1.x (the 1.x design; the full Nios + 2.x Quartus project does not exist yet, see the status table) | `quartus_a5e_nios/` | `nios_caliptra_a5e` | `nios_caliptra_top` |
| Caliptra 1.x core only (size study) | `quartus_a5e/` | `caliptra_a5e` | `caliptra_passive_top` |
| Caliptra 2.x core only (fit gate; 126 %, does not fit) | `caliptra2x/quartus_a5e_2x/` | `caliptra2x_a5e` | `caliptra_passive_top` |

**Step 1: generate IP (Nios project only).** The Platform Designer output (`qsys/nios_caliptra_sys/`, `qsys/ip/nios_caliptra_sys/`) is committed. The Reset Release IP output (`ip/rst_release/`) is gitignored. Run `quartus_ipgenerate` once after cloning (and after any `.qsys`/`.ip` change). It regenerates every `QSYS_FILE`/`IP_FILE` in the project:

```bash
cd quartus_a5e_nios
quartus_ipgenerate nios_caliptra_a5e
# Optional, only if you changed the PD system: rebuild it from Tcl first
#   cd qsys && qsys-script --script=nios_caliptra_sys.tcl --quartus-project=none && cd ..
#   (or: qsys-generate qsys/nios_caliptra_sys.qsys --synthesis=VERILOG --quartus-project=nios_caliptra_a5e)
```

`run_nios_a5e_docker.sh [syn|fit]` does the full regeneration (Tcl → PD → ipgenerate → synthesis) in one go. The Nios program memory is initialised from the committed `quartus_a5e_nios/onchip_mem.hex`. Rebuild it with `quartus_a5e_nios/sw/build_app.sh` (needs `RISCV_BIN=<dir with riscv-none-elf-gcc>`) only if you change `sw/app/main.c`.

**Step 2: compile.** Native Quartus on Linux:

```bash
cd quartus_a5e_nios
quartus_syn --analysis_and_elaboration nios_caliptra_a5e   # quick check: all files found, hierarchy elaborates
quartus_syn nios_caliptra_a5e                              # Analysis & Synthesis
quartus_fit nios_caliptra_a5e                              # place + route (needs >= 32 GB RAM)
quartus_sta nios_caliptra_a5e                              # timing
quartus_asm nios_caliptra_a5e                              # .sof (only with real pins and a license that enables it)
# or all stages:  quartus_sh --flow compile nios_caliptra_a5e
```

Same thing with Docker, from the repo root:

```bash
export LIC_HOST=$HOME/licenses/SW-AGILEX-5E.dat
scripts/quartus_docker.sh quartus_a5e_nios 'quartus_ipgenerate nios_caliptra_a5e && quartus_syn nios_caliptra_a5e'
scripts/quartus_docker.sh quartus_a5e_nios 'quartus_fit nios_caliptra_a5e && quartus_sta nios_caliptra_a5e'
scripts/quartus_docker.sh quartus_a5e 'quartus_syn caliptra_a5e'
scripts/quartus_docker.sh caliptra2x/quartus_a5e_2x 'quartus_syn caliptra2x_a5e'
```

**GUI alternative.**
1. *File → Open Project* → `quartus_a5e_nios/nios_caliptra_a5e.qpf`.
2. *Tools → Generate IP* (or accept the prompt to generate IP).
3. *Processing → Start → Start Analysis & Synthesis* (or *Start Compilation* for the full flow).

**Outputs.** Reports go to `<project>/output_files/`:
- `<rev>.syn.summary`: ALMs, registers, DSP
- `<rev>.syn.rpt`: hierarchy, resource usage by entity, messages
- `<rev>.syn.ae.rpt`: Analysis & Elaboration
- `<rev>.fit.*`, `<rev>.sta.*`, `<rev>.sof` after fit, timing and assembler

The `qdb/`, `dni/` and `tmp-clearbox/` work directories are gitignored.

**Measured results** (Quartus Pro 25.3.0 b109, A5EC065BB32AE6S, from a fresh `git clone --recursive` of commit `28951ad` on a 16 GB / 8-core Linux box, Docker image above):

| Project | Analysis & Elaboration | Full Analysis & Synthesis |
|---|---|---|
| `quartus_a5e_nios` (`nios_caliptra_top`) | **OK**, 0 errors, 1 min 19 s, 3.3 GB peak; `quartus_ipgenerate` OK, 0 errors, 9 s | **Successful**, 0 errors: **138,715 / 222,400 ALMs (62 %)**, 145,784 registers, 47 DSP post-merge, 5,671,936 block-memory bits; 6 min 50 s at `--parallel=4`, 4.0 GB peak. This matches the earlier build exactly |
| `quartus_a5e` (`caliptra_passive_top` 1.x) | **OK**, 0 errors, 44 s, 2.8 GB peak | 141,256 / 222,400 ALMs (**64 %**), 142,373 registers, 47 DSP (committed `syn.summary`; 6 min 30 s, 3.6 GB) |
| `caliptra2x_a5e` (`caliptra_passive_top` 2.x) | **OK**, 0 errors, 1 min 41 s, 4.4 GB peak | 279,685 / 222,400 ALMs (**126 %, does not fit**), 411,569 registers, 199 DSP (committed report; 22 min, 6.8 GB) |

All three hierarchies elaborate with no missing-file or undefined-entity messages. The ROM, FW-bundle and fuse hex files are read by `$readmemh` from their repo-relative paths (`../fw/…`, `../fw_2x/…`).

Expected warnings (harmless):
- Critical Warning 16668: MFCU turns off auto-discovery. MFCU is intentional, because Caliptra relies on macros persisting across files.
- Critical Warning 20759 on the core-only projects: no Reset Release IP. That IP is only in the Nios top.
- Critical Warning 127004 (Nios project, ×2): Quartus pads the internal MIFs for the ROM (6144 → 8192 words) and the FW store (28672 → 32768 words) to a power of two. This is expected.
- Critical Warning 18061/18010: power-up-level notes on the security-state latch.
- Verilog truncation and parameter warnings from upstream RTL.

**Known issues.**
- **Intermittent Quartus start-up crash in Docker:** `Error (22912): Unhandled exception … DDM_T::verify_token(token) : Cannot identify the client` within the first second. It is not a design problem. Simply rerun the same command; on the build box it took up to 3 tries.
- **Synthesis hangs with no CPU use.** Quartus can stop progressing, usually during the SLD/JTAG-hub `ip-deploy` step or right after RAM inference when it starts its parallel helper processes. Signs: the log stops growing, `quartus_syn` sits at about 0 % CPU, and defunct `quartus_sh` children remain. Most likely the same start-up crash, hitting a helper process. Kill the container (`docker kill <id>`; with `DOCKER_NAME=<name>` set for `scripts/quartus_docker.sh` you can `docker kill <name>`) and rerun. A healthy Nios synthesis shows 4 busy `quartus_syn` helpers with `--parallel=4`. The run then finishes normally; the earlier note recorded about 7 min at `--parallel=8`.
- **Memory.** A&E needs about 3–4.5 GB, and full synthesis about 4 GB (1.x) or 7 GB (2.x). **Fit/route needs ≥ 32 GB**: placement passed on a 16 GB VM but routing ran out of memory, so fit, timing and `.sof` have not been produced yet.
- **Pins.** All top-level I/O except `clk` (and `reset_n` in the Nios project) are `VIRTUAL_PIN ON`. Assign real pins and I/O standards for your board before `quartus_asm`.

# Nios V ↔ Caliptra 1.x Integration Note

- **Project:** Caliptra 1.x (passive) on Intel Agilex 5 E **A5EC065BB32AE6S**, Nios V/m mailbox host (AXI4-lite → Avalon → APB).
- **Repo:** [pwilliam282/caliptra-a5e-quartus](https://github.com/pwilliam282/caliptra-a5e-quartus)
- **This document:** [`docs/NIOS_CALIPTRA_INTEGRATION.md`](https://github.com/pwilliam282/caliptra-a5e-quartus/blob/main/docs/NIOS_CALIPTRA_INTEGRATION.md)
- **RTL / spec version:** chipsalliance/caliptra-rtl **v1.1**, commit `5f85fb4bc95b753a2f7d042db7dc2644ca1e8c49` (same tree as release [rtl-20261101](https://github.com/pwilliam282/caliptra-a5e-quartus/releases/tag/rtl-20261101)). Official sources used for this audit: `docs/CaliptraIntegrationSpecification.md` and `docs/CaliptraHardwareSpecification.md` at that commit. **1.x has no `strap_ss_*` / AXI DMA / Caliptra-SS straps** — those belong to 2.x / Caliptra SS.
- **Glue RTL reviewed at:** `32924ba` (production-lifecycle mimic). This note was first added in `7ba4ce5` and revised in the commit that lands this text. No RTL was changed for this note.
- **Date:** 2026-11-10 (America/Chicago), revision 2 (reset, watchdog, full spec checklist).
- **Scope:** FPGA study / production-flow *mimic*. STUDY keys, UDS, field entropy, and TRNG are **not** production secrets or a FIPS entropy source.

This is the complete connection map and bring-up note for the Nios host design. It is based on the *actual* FPGA glue RTL, Platform Designer system, and Nios firmware, audited against the official v1.1 Integration and Hardware specifications.

### Corrections vs. the first revision (`7ba4ce5`)

| Item | What changed |
|---|---|
| `CPTRA_HW_REV_ID` | Not a flat `0x0000_0011`. It is `{SOC_STEPPING_ID[15:0], CPTRA_GENERATION[15:0]}` with generation reset value `0x0011` (major 1, minor 1, patch 0). The host reads it *before* fuses, so `0x0000_0011` is correct at that moment. RTL continuously copies `FUSE_SOC_STEPPING_ID` into the stepping field, so after the image's stepping fuse (`0x1`) is written a later read can be `0x0001_0011`. |
| Reset synchronizers | The v1.1 Integration Spec RDC section *requires* the integrator to add external synchronizers: `cptra_pwrgood` and `cptra_rst_b` must already be synchronized to `clk` at the Caliptra boundary. The first revision treated this as a milder CDC note on `reset_n`. It is a **FAIL**. |
| Warm reset vs fuses | First revision correctly said the host always does a cold-style fuse push, but did not audit `soc_fuse_ctrl` against the required warm-reset path (fuses persist; SoC must still **write `FUSE_WR_DONE` again** without re-writing locked fuses). The IP has no done-only mode. |
| Watchdog / fatal | Added a full WDT / NMI / `cptra_error_fatal` section. The fatal *output pin* clears on `cptra_rst_b` (internal `cptra_noncore_rst_b`); sticky logs and `CPTRA_WDT_CFG` persist across warm reset; the integration requirement to *recover* from a fatal is a power-good reset. WDT t2 specifically needs a **warm reset** to restart the timers. |
| `CPTRA_TIMER_CONFIG` | Was omitted. SoC-writable clock period in picoseconds (sticky on pwrgood, default 0). Nios never programs it. |
| 2.x names | There is no `cptra_bootfsm_bp` or `strap_ss` in 1.x. The breakpoint pin is `BootFSM_BrkPoint`. The NMI vector is an *internal register*, not a strap. |

---

## 1. Where the earlier connection-map docs live

There was **no** `docs/` tree and no single integration note in the repo before the first revision of this file. The Nios ↔ Caliptra map was spread across these documents (all still present):

| Document | What it covers | Status vs RTL at `32924ba` |
|---|---|---|
| [`quartus_a5e_nios/README.md`](https://github.com/pwilliam282/caliptra-a5e-quartus/blob/main/quartus_a5e_nios/README.md) | Closest earlier connection map: ASCII block diagram, Nios address map, straps, fuse-image summary | **Architecture / address-map / strap sections are mostly accurate.** The **Firmware** and **Not done** sections are stale (see §10). |
| [`README.md`](https://github.com/pwilliam282/caliptra-a5e-quartus/blob/main/README.md) | Top-level overview: fuse controller, ETRNG service, FIRMWARE_LOAD, MAGIC `0xCA11F00D` | Accurate at a high level. |
| [`sim/BOOT_NIOS_TOP_PROD.md`](https://github.com/pwilliam282/caliptra-a5e-quartus/blob/main/sim/BOOT_NIOS_TOP_PROD.md) | Verilator production-mimic boot (PASS at cycle 24,064,873, 32 TRNG fills) | Accurate for the behavioral-Nios TB. |
| [`STUDY.md`](https://github.com/pwilliam282/caliptra-a5e-quartus/blob/main/STUDY.md) | C10 GX / A5E fit study (ALMs, routing OOM) | Not a signal map. Notes a Quartus critical warning for a **missing Reset Release IP** on the related A5E build — still missing in this Nios project. |

Official SoC-interface rules are in caliptra-rtl v1.1 `docs/CaliptraIntegrationSpecification.md` and `docs/CaliptraHardwareSpecification.md` at `5f85fb4`. Those files are *not* vendored in this git repo; get them with the RTL from release [rtl-20261101](https://github.com/pwilliam282/caliptra-a5e-quartus/releases/tag/rtl-20261101).

---

## 2. Block diagram

```mermaid
flowchart TB
  clk["clk 50 MHz"]
  rstn["reset_n"]
  led["led[7:0]"]

  subgraph pd ["nios_caliptra_sys (Platform Designer)"]
    cpu["Nios V/m"]
    ram["on-chip RAM 64 KiB<br/>reset vector 0x0"]
    juart["jtag_uart irq0"]
    ctrl["ctrl_pio out"]
    stpio["status_pio in"]
    magic["magic_pio out"]
    win["caliptra_win<br/>Avalon mm_bridge 256 KiB, AW=18"]
    cpu -->|data master| ram
    cpu --> juart
    cpu --> ctrl
    cpu --> stpio
    cpu --> magic
    cpu --> win
  end

  clk --> pd
  rstn --> pd
  magic --> led

  win -->|"exported Avalon master"| dec["window decode in nios_caliptra_top"]
  dec -->|"0x00000–0x1BFFF"| fw["soc_fw_store M20K<br/>caliptra-fw-bundle.hex"]
  dec -->|"0x1F000–0x1FFFF"| fuse["soc_fuse_ctrl<br/>fuse_image.hex"]
  dec -->|"0x20000–0x3FFFF"| br["avmm_to_apb<br/>PAUSER = 1, PPROT = 0"]

  fuse -->|"APB while busy"| mux["APB mux"]
  br --> mux

  ctrl -->|"[0] cptra_pwrgood<br/>[1] cptra_rst_b<br/>[2] BootFSM_BrkPoint"| ctop
  mux --> ctop
  magic -->|"generic_input_wires[31:0]<br/>SPEC ISSUE: see M1"| ctop

  subgraph wrap ["caliptra_passive_top"]
    ctop["caliptra_top v1.1"]
    msram["mailbox SRAM 128 KiB + ECC<br/>32768 × 39"]
    rom["ROM 48 KiB M20K<br/>fw/caliptra-rom.hex"]
    veer["VeeR ICCM / DCCM / ICache<br/>caliptra_veer_sram_export"]
    ctop --> msram
    ctop --> rom
    ctop --> veer
  end

  ctop -->|"ready_for_* , mailbox_* , errors,<br/>etrng_req, gen_out[23:0]"| stpio

  qspi["QSPI ports tied off"]
  jtag["Caliptra JTAG tied off"]
  itrng["itrng_data=0, itrng_valid=0<br/>ETRNG mode"]
  straps["lifecycle=PRODUCTION, debug_locked=1<br/>scan_mode=0<br/>STUDY cptra_obf_key localparam"]
  qspi -.-> ctop
  jtag -.-> ctop
  itrng -.-> ctop
  straps -.-> ctop
```

Text equivalent (for PDF / plain renderers):

```
 clk (50 MHz) + reset_n
        |
        v
 nios_caliptra_sys (Platform Designer)
   Nios V/m --AXI4-lite--> interconnect
        +-- ram (64 KiB OCM, reset vector 0x0, init onchip_mem.hex)
        +-- jtag_uart (stdout, IRQ 0)     +-- cpu timer @ 0x80040, debug @ 0x90000
        +-- ctrl_pio  (out) --> cptra_pwrgood / cptra_rst_b / BootFSM_BrkPoint
        +-- status_pio(in)  <-- ready_for_* / mailbox_* / errors / etrng_req / gen_out[23:0]
        +-- magic_pio (out) --> led[7:0]  and  generic_input_wires[31:0]  (! see M1)
        +-- caliptra_win (256 KiB mm_bridge, exported Avalon master, 18-bit byte address)
                    |
                    v
        window decode in nios_caliptra_top.sv
           0x00000-0x1BFFF  soc_fw_store   (M20K, fw/caliptra-fw-bundle.hex)
           0x1F000-0x1FFFF  soc_fuse_ctrl  (MMIO + APB master; fw/fuse_image.hex)
           0x20000-0x3FFFF  avmm_to_apb    (PAUSER=0x1 constant) --+
                                soc_fuse_ctrl APB (when busy)  --+--> Caliptra APB
                                                                 |
                                                                 v
                                         caliptra_passive_top
                                           caliptra_top v1.1
                                           mailbox SRAM, ROM, ICCM/DCCM/ICache
                                           QSPI / Caliptra JTAG / iTRNG / scan tied off
```

There is **no** Intel Reset Release IP (`ninit_done`), **no** PLL (or PLL-lock AND into reset), and **no** ISSP in this project. `clk` and `reset_n` go straight to the PD clock source and to the Caliptra control AND gates.

---

## 3. Full signal connection table

Widths and official roles follow caliptra-rtl v1.1 `caliptra_top` / Integration Spec Tables 4–11. “FPGA source/sink” is what `nios_caliptra_top.sv` and `caliptra_passive_top.sv` actually wire.

### 3.1 Clocks and resets

| Caliptra port | W | FPGA source / sink | Notes |
|---|---:|---|---|
| `clk` | 1 | Board `clk` (top port). Shared by Nios, glue, and Caliptra. | SDC: 50 MHz (`period 20 ns`). **No PLL**, no on-die oscillator. Spec validates up to 400 MHz and requires an on-die oscillator for the threat model. The input clock is **ungated**; internal Caliptra clock gating is off until SoC writes `CPTRA_CLK_GATING_EN` (`0x3_00C0`, default 0, SoC-writable, resets on `cptra_rst_b`). Nios never writes it. Clock is running before Nios asserts `cptra_pwrgood`. |
| `cptra_pwrgood` | 1 | `ctrl_pio[0] & reset_n` | Active-high. PIO reset value 0 ⇒ Caliptra held unpowered until Nios writes bit 0. Board `reset_n` also forces it low (**cold reset**). **No external 2FF synchronizer** on this pin (spec FAIL; see §5). |
| `cptra_rst_b` | 1 | `ctrl_pio[1] & reset_n` | Active-low warm-reset pin. Same raw AND. Official minimum: **≥ 10 clocks** after pwrgood before deasserting `cptra_rst_b`. Nios `delay(1000)` / TB 20 cycles meet that for the *intended* cold-boot path. Deassert is not guaranteed synchronous when `reset_n` is in the path. |

Top-level `reset_n` also resets the Platform Designer system (clock_source `resetSynchronousEdges DEASSERT` — this *does* sync-deassert the **Nios/PD** reset) and the glue (`avmm_to_apb`, `soc_fuse_ctrl`). Caliptra's two pins do **not** use that PD synchronizer; they AND the raw `reset_n` pin. SDC: `set_false_path -from [get_ports reset_n]`.

See **§5** for cold vs warm reset, fuse persistence, and the sequence diagram.

### 3.2 APB (SoC mailbox / soc_ifc)

APB is 32-bit address, 32-bit data, 32-bit PAUSER (`CALIPTRA_APB_*_WIDTH` in `config_defines.svh`). Nios sees only an 18-bit window; `avmm_to_apb` zero-extends and forces 32-bit alignment.

| Caliptra port | W | FPGA source / sink | Notes |
|---|---:|---|---|
| `PADDR` | 32 | Mux: `soc_fuse_ctrl` while `busy`, else `avmm_to_apb` | Fuse controller uses `0x0003_0200 + 4*idx` then `0x0003_00B0`. Nios path uses the 18-bit Avalon byte address. |
| `PPROT` | 3 | `avmm_to_apb` constant `3'b000` | Fuse controller does **not** drive `PPROT`; the bridge constant remains during fuse push. |
| `PSEL`, `PENABLE`, `PWRITE`, `PWDATA` | 1 / 1 / 1 / 32 | Same mux | Standard APB3 SETUP then ACCESS until `PREADY`. |
| `PAUSER` | 32 | `avmm_to_apb` parameter `PAUSER_VAL = 32'h1` | Always 1, including during fuse push (fuse IP does not drive PAUSER). Default mailbox valid PAUSER in RTL is `CPTRA_DEF_MBOX_VALID_PAUSER = 0xFFFFFFFF`, so Nios **must** program and lock slot 0 to 1 before using the mailbox. |
| `PREADY`, `PRDATA`, `PSLVERR` | 1 / 32 / 1 | Caliptra → bridge and fuse controller | Bridge reports `avs_response = 2'b10` on `PSLVERR` (mm_bridge `USE_RESPONSE` is not enabled, so the Nios CPU does not see AXI/Avalon error responses). |

### 3.3 Boot / mailbox notification and errors

| Caliptra port | W | FPGA source / sink | Notes |
|---|---:|---|---|
| `ready_for_fuses` | 1 | `status_pio[0]` and `soc_fuse_ctrl.ready_for_fuses` | Asserted in Boot FSM `BOOT_FUSE`. START is rejected if this is low. |
| `ready_for_fw_push` | 1 | `status_pio[1]` | Nios waits, then issues mailbox `FIRMWARE_LOAD`. Wired and used correctly. |
| `ready_for_runtime` | 1 | `status_pio[2]` | Success criterion; MAGIC `0xCA11F00D`. Wired and used correctly. |
| `mailbox_data_avail` | 1 | `status_pio[3]` | Level status reflecting the mailbox register. **Not** connected to a Nios IRQ. Polling is architecturally allowed (SoC is responsible for noticing data). |
| `mailbox_flow_done` | 1 | `status_pio[4]` | Same. |
| `cptra_error_fatal` | 1 | `status_pio[5]` | Polled (`0xDEAD00FF` / `0xDEAD000D`). **Not an IRQ**, contrary to Integration Spec error-recovery (“shall be routed to SoC interrupt controller”). The pin is sticky until `cptra_rst_b` / `cptra_noncore_rst_b`. Spec also: recover a fatal with a **power-good** reset; WDT t2 additionally needs a **warm reset** to restart the timers. This host does neither automatically. |
| `cptra_error_non_fatal` | 1 | `status_pio[6]` | Polled at the end of boot. Same missing IRQ routing. |
| `BootFSM_BrkPoint` | 1 | `ctrl_pio[2]` | 1.x name is `BootFSM_BrkPoint` (there is no `cptra_bootfsm_bp` pin). Reset value 0 (do not halt Boot FSM after fuses). If set, the FSM goes `BOOT_FUSE` → `BOOT_WAIT` until SoC writes `CPTRA_BOOTFSM_GO.GO = 1` at `0x3_00B8`. Nios never sets the strap or writes GO. |

The only Platform Designer IRQ is `jtag_uart` at irqNumber 0. Caliptra status is polled. See **§6** for WDT / NMI / fatal behavior.

### 3.4 TRNG

`CALIPTRA_INTERNAL_TRNG` is **commented out** in upstream `config_defines.svh`, so this build is **external-source (ETRNG) mode**. The 1.x RTL still *contains* entropy_src / CSRNG, but they are not instantiated without that define.

| Caliptra port | W | FPGA source / sink | Notes |
|---|---:|---|---|
| `etrng_req` | 1 | `status_pio[7]` | ROM/FW raise this; Nios `trng_service()` in `sw/app/main.c` polls it. |
| `itrng_data` | 4 | Tied `4'h0` | Unused in ETRNG mode. |
| `itrng_valid` | 1 | Tied `1'b0` | Forces ETRNG; no physical bitstream. |

There is **no** FPGA entropy IP, no ring oscillator, and no hardware LFSR. Servicing is done in **Nios C firmware**:

1. See `status_pio[7]`.
2. Write 12 words to `CPTRA_TRNG_DATA0`…`DATA11` (`0x30078`–`0x300A4`) from an **xorshift32** seeded with `0x1234ABCD`.
3. Write `CPTRA_TRNG_STATUS = 2` (`DATA_WR_DONE`).
4. Wait for `etrng_req` to drop.

The Verilator TB does the same with `$urandom`. `CPTRA_TRNG_VALID_PAUSER` / `CPTRA_TRNG_PAUSER_LOCK` are **never programmed**.

This is **TEST-ONLY**. It is not NIST-compliant entropy. The Integration Spec requires a dedicated iTRNG (or, if the shared ETRNG API is used, **immutable SoC hardware gasket logic**, not mutable firmware) and recommends locking TRNG PAUSER. See §8.

### 3.5 Security straps, generic wires, scan, JTAG, QSPI

| Caliptra port | W | FPGA source / sink | Notes |
|---|---:|---|---|
| `cptra_obf_key` | 256 | Localparam `STUDY_PROD_MIMIC_OBF_KEY` in `nios_caliptra_top.sv` | Fixed study value, always driven. **Not** a product secret; visible in RTL/bitstream. Real silicon would ECO/PUF this and keep it off scan. Latched inside Caliptra on a power-good cycle (internal `pwrgood_toggle_hint`). |
| `security_state.device_lifecycle` | 2 | Hardwired `2'b11` (`DEVICE_PRODUCTION`) | Production-*flow mimic*, not a live SoC lifecycle strap. Captured inside Caliptra on the first cycle after internal non-core reset release (default latched value before capture is also PRODUCTION + debug locked). |
| `security_state.debug_locked` | 1 | Hardwired `1'b1` | Debug locked (HW spec: MSB of security_state). Because of this, rom-1.1.1 arms WDT1 from `CPTRA_WDT_CFG`. JTAG would not open. |
| `scan_mode` | 1 | Tied `1'b0` | Correct for this FPGA (no DFT). Spec: must be set to 1 *before* scan is enabled so secrets can be flushed. RDC analysis also assumes 0 for functional mode. |
| `generic_input_wires` | 64 | `{32'h0, magic_out}` | **Spec mismatch (M1).** Official v1.1 binding: bit 0 = fuse zeroization status; bits 63:1 reserved and must be tied 0, not connected to flops. Here bits 31:0 track `magic_pio`, so MAGIC `1` at start of boot also sets bit 0. |
| `generic_output_wires` | 64 | `[23:0]` packed into `status_pio[31:8]`; `[63:24]` not visible to Nios | ROM/FW character log in the TB uses bits `[8:0]` (bit 8 toggles, `[7:0]` is the char). |
| `jtag_tck/tms/tdi` | 1 | Tied 0 | Caliptra TAP not brought out. |
| `jtag_trst_n` | 1 | Tied 0 | Held in reset. Spec wants a TAP endpoint and `jtag_trst_n` deassert synchronized to `jtag_tck`. Acceptable for a debug-locked FPGA study; not a production TAP. |
| `jtag_tdo`, `jtag_tdoEn` | 1 | Unconnected | — |
| `qspi_clk_o`, `qspi_cs_no`, `qspi_d_o`, `qspi_d_en_o` | — | Unconnected in the wrapper | `CALIPTRA_INTERNAL_QSPI` is not enabled. |
| `qspi_d_i` | 4 | Tied `'0` | — |
| UART `uart_tx`/`uart_rx` | — | Not present | `CALIPTRA_INTERNAL_UART` undefined; ports compiled out. |

Nios has its **own** JTAG UART and debug module (Intel SLD / `altera_reserved_tck` in the SDC). That is unrelated to the Caliptra TAP.

Firmware image source is **`soc_fw_store`** (on-chip M20K, `fw/caliptra-fw-bundle.hex`, 109,000 bytes), a stand-in for SoC boot flash. There is no QSPI/flash controller in this design.

### 3.6 Memories (instantiated in `caliptra_passive_top`)

| Memory | Size / shape | Implementation | Notes |
|---|---|---|---|
| Mailbox SRAM | 128 KiB + 7-bit ECC, 32768 × 39 | `caliptra_sram` → M20K | Export from `caliptra_top`. |
| BootROM (imem) | 48 KiB, 6144 × 64 | `caliptra_rom_m20k`, `$readmemh("../fw/caliptra-rom.hex")` | caliptra-sw **rom-1.1.1**. Do not use a 2.x ROM. Path is relative to `quartus_a5e_nios/`. |
| VeeR ICCM | 128 KiB + ECC, 4 × 8192 × 39 | `caliptra_veer_sram_export` | Error injection tied to 0. |
| VeeR DCCM | 128 KiB + ECC, 4 × 8192 × 39 | same | same |
| ICache (data+tag) | ~16 KiB | same export | Spec notes I-Cache may be disabled/removed for synthesis; it is still instantiated. |
| SoC FW store | 28,672 × 32 (112 KiB) | `soc_fw_store` M20K | Not a Caliptra memory. |
| SoC fuse image | 83 × 32 | `$readmemh` array in `soc_fuse_ctrl` | FPGA stand-in for OTP; not non-volatile. |
| Nios OCM | 64 KiB | PD `intel_onchip_memory`, `onchip_mem.hex` | Host code/data. |

Spec also wants SRAM repair only on power-good, and SRAM contents **zeroed before `cptra_rst_b` deassert**. This FPGA design does not implement a repair/zeroization pass (open item). Mailbox / ICCM / DCCM come up with M20K power-up contents, not a guaranteed 0.

---

## 4. Memory map as seen by Nios

From `qsys/nios_caliptra_sys.tcl` and generated `sw/bsp/system.h`. Data-master view:

| Base | Span | Block |
|---|---|---|
| `0x0000_0000` | 64 KiB | `ram` on-chip memory (code + data, init `onchip_mem.hex`) |
| `0x0004_0000` | 256 KiB | `caliptra_win` window (offsets below) |
| `0x0008_0000` | 8 B | `jtag_uart` |
| `0x0008_0010` | 16 B | `ctrl_pio` — bit 0 `cptra_pwrgood`, bit 1 `cptra_rst_b`, bit 2 `BootFSM_BrkPoint` (reset 0) |
| `0x0008_0020` | 16 B | `status_pio` — see bit table below |
| `0x0008_0030` | 16 B | `magic_pio` → `led[7:0]` and `generic_input_wires[31:0]` |
| `0x0008_0040` | 64 B | Nios V `timer_sw_agent` (mtime) — **Nios** timer, unrelated to Caliptra `CPTRA_TIMER_CONFIG` |
| `0x0009_0000` | 64 KiB | Nios V debug module |

### 4.1 Window at `0x0004_0000` (18-bit offset)

Decode in `nios_caliptra_top.sv`: `address[17]` selects Caliptra; `address[16:12] == 0x1F` selects the fuse controller; everything else in the low half is the FW store.

| Window offset | Nios address | Block |
|---|---|---|
| `0x0_0000`–`0x1_BFFF` | `0x0004_0000`–`0x0005_BFFF` | `soc_fw_store` (word-addressed firmware bundle, little-endian 32-bit) |
| `0x1_C000`–`0x1_EFFF` | — | **Hole:** decode still hits `soc_fw_store`, address clamped to word 0. Do not use. |
| `0x1_F000`–`0x1_FFFF` | `0x0005_F000` | `soc_fuse_ctrl` MMIO (4 KiB) |
| `0x2_0000`–`0x2_FFFF` | `0x0006_0000` | Caliptra `MBOX_CSR` (via APB) |
| `0x3_0000`–`0x3_FFFF` | `0x0007_0000` | Caliptra `soc_ifc` (via APB) |

### 4.2 `soc_fuse_ctrl` MMIO (base `0x0005_F000`)

| Offset | Access | Meaning |
|---|---|---|
| `0x00` ID | RO | `0x4655_5345` (`"FUSE"`) |
| `0x04` CTRL | WO | bit 0 START, bit 1 CLEAR (clears DONE/ERR) |
| `0x08` STATUS | RO | bit 0 BUSY, bit 1 DONE, bit 2 ERR, bit 3 live `ready_for_fuses` |
| `0x0C` COUNT | RO | APB writes completed (84 = 83 fuse words + `FUSE_WR_DONE`) |
| `0x10` FW_BYTES | RO | `109000` — size of the bundle in `soc_fw_store` |
| `0x14` NUM_FUSES | RO | `83` |

UDS / field entropy in the on-chip image are **not** readable through this MMIO (Nios can only START and read status). After programming, Caliptra itself reads back `FUSE_UDS_SEED` / `FUSE_FIELD_ENTROPY` as 0 (write-only to the SoC), which the TB checks.

### 4.3 Selected Caliptra APB offsets (add to `0x0004_0000`)

| Offset | Register | Use in this host / notes |
|---|---|---|
| `0x2_0000` | `MBOX_LOCK` | Acquire before `FIRMWARE_LOAD` |
| `0x2_0004` | `MBOX_USER` | Must equal `1` (our PAUSER) |
| `0x2_0008` | `MBOX_CMD` | `0x46574C44` (`"FWLD"`) |
| `0x2_000C` | `MBOX_DLEN` | Bundle length in bytes |
| `0x2_0010` | `MBOX_DATAIN` | Word stream from `soc_fw_store` |
| `0x2_0018` | `MBOX_EXECUTE` | 1 to start, 0 to release |
| `0x2_001C` | `MBOX_STATUS` | 2 = CMD_COMPLETE, 3 = CMD_FAILURE |
| `0x3_0000` | `CPTRA_HW_ERROR_FATAL` | Sticky. Bit 0 ICCM ECC, bit 1 DCCM ECC, **bit 2 `nmi_pin` (0x4) = WDT t2**, bit 3 crypto. Writing 1 clears a bit in the *register* but **does not** deassert the `cptra_error_fatal` pin. |
| `0x3_003C` | `CPTRA_FLOW_STATUS` | Includes `ready_for_*` bits |
| `0x3_0048` / `0x3_005C` | `CPTRA_MBOX_VALID_PAUSER[0]` / `LOCK[0]` | Programmed to 1 / 1 before mailbox use |
| `0x3_0078`–`0x3_00A4` | `CPTRA_TRNG_DATA[0..11]` | 12 ETRNG words |
| `0x3_00AC` | `CPTRA_TRNG_STATUS` | Write 2 = `DATA_WR_DONE` |
| `0x3_00B0` | `CPTRA_FUSE_WR_DONE` | Written by `soc_fuse_ctrl`, then checked by Nios. Sticky on **pwrgood**. |
| `0x3_00B4` | `CPTRA_TIMER_CONFIG` | Clock period in **picoseconds** (SoC RW, sticky on pwrgood, default 0). Used by Caliptra FW `get_cycle_count()` for MTIME. **Nios never programs this** (50 MHz would be 20,000 ps). |
| `0x3_00B8` | `CPTRA_BOOTFSM_GO` | Write `GO=1` to leave `BOOT_WAIT` if `BootFSM_BrkPoint` was set. Unused (strap is 0). |
| `0x3_00C0` | `CPTRA_CLK_GATING_EN` | SoC-writable global enable for *internal* clock gating (default 0, resets on `cptra_rst_b`). Nios leaves it 0 (gating disabled). (HW spec table lists `0x300300bc`; the v1.1 register header / RDL address is `0x300300c0`.) |
| `0x3_00D4` | `CPTRA_HW_REV_ID` | `{SOC_STEPPING_ID, CPTRA_GENERATION}`. Generation reset value `0x0011`. Stepping is driven from `FUSE_SOC_STEPPING_ID`. Host reads this *before* fuses ⇒ `0x0000_0011`. After stepping fuse `0x1` is written, a later read can be `0x0001_0011`. |
| `0x3_00D8` / `0x3_00DC` | `CPTRA_FW_REV_ID0/1` | Read after `ready_for_runtime` |
| `0x3_00E4`…`0x3_0104` | `CPTRA_WDT_TIMER*` / `STATUS` | Caliptra-internal WDT programming and t1/t2 status. SoC is RO on the period/status. See §6. |
| `0x3_0110` / `0x3_0114` | `CPTRA_WDT_CFG0/1` | SoC-provided 64-bit WDT1 timeout in cycles, sticky on **pwrgood**, default 0. Nios writes `100_000_000` / `0` **before** fuses. |
| `0x3_0200`–`0x3_0348` | `FUSE_*` | Written by `soc_fuse_ctrl`, not by Nios |

### 4.4 `status_pio` bits

| Bit | Signal |
|---|---|
| 0 | `ready_for_fuses` |
| 1 | `ready_for_fw_push` |
| 2 | `ready_for_runtime` |
| 3 | `mailbox_data_avail` |
| 4 | `mailbox_flow_done` |
| 5 | `cptra_error_fatal` |
| 6 | `cptra_error_non_fatal` |
| 7 | `etrng_req` |
| 31:8 | `generic_output_wires[23:0]` |

---

## 5. Reset and power-good

### 5.1 How the pins are generated (this FPGA)

```
reset_n (board, active-low, SDC false path)
   │
   ├──► Platform Designer clock_source.clk_in_reset
   │      resetSynchronousEdges = DEASSERT
   │      ⇒ Nios, OCM, PIOs, mm_bridge get a sync-deasserted reset
   │      ctrl_pio reset value = 0
   │
   └──► combinational AND in nios_caliptra_top.sv
          cptra_pwrgood = ctrl_pio[0] & reset_n
          cptra_rst_b   = ctrl_pio[1] & reset_n
```

Not present, and relevant for a real A5E kit bring-up:

- **Intel Reset Release IP / `ninit_done`.** Agilex 5 fabric is not guaranteed ready until the Reset Release (`ninit_done`) handshake. Quartus already warned about a missing Reset Release IP on the sibling A5E project (`STUDY.md`). This Nios top has the same gap.
- **PLL and PLL-lock.** The SDC assumes a 50 MHz input already at the `clk` port. There is no PLL-lock term in the reset AND.
- **ISSP** (In-System Sources and Probes) for debug-overriding resets: not instantiated.
- **External 2FF synchronizers** on `cptra_pwrgood` and `cptra_rst_b`: not instantiated.

### 5.2 Official ordering (v1.1 Integration Spec)

- Clock must be running **before** `cptra_pwrgood` asserts. (Met: free-running board/`clk`.)
- **≥ 10 clocks** after `cptra_pwrgood` asserts before `cptra_rst_b` is deasserted. (Met in `main.c` / TB for the cold-boot path.)
- Assertions of `cptra_pwrgood` / `cptra_rst_b` may be asynchronous; **deassertions must be synchronous to `clk`**. The integrator **must add external reset synchronizers**; Caliptra assumes the pins are already synchronized at its boundary (RDC “Reset constraints and assumptions”).
- **`cptra_pwrgood` deasserted** = power cycle / **cold reset**. All resettable flops return to default, including sticky registers (fuses, `FUSE_WR_DONE`, `CPTRA_WDT_CFG`, error logs, `CPTRA_TIMER_CONFIG`, fuse PAUSER lock).
- **`cptra_rst_b` deasserted while pwrgood stays high** = **warm reset**. Resets all but sticky registers. Fuses and `FUSE_WR_DONE` **persist**. The SoC must still perform a write to `FUSE_WR_DONE` while the Boot FSM is in `BOOT_FUSE` (`fuse_wr_done_observed` is cleared on `cptra_noncore_rst_b` and must see a fresh `swmod` on the done register).
- `BootFSM_BrkPoint=1` stops the FSM after fuse download until `CPTRA_BOOTFSM_GO`.

Internal Boot FSM (v1.1 `soc_ifc_boot_fsm.sv`): `BOOT_IDLE` (held while `cptra_rst_b` is asserted) → `BOOT_FUSE` (`ready_for_fuses`, non-core reset already released so the APB fuse window works) → `BOOT_DONE` (or `BOOT_WAIT` if the breakpoint strap is set). `BOOT_DONE` deasserts `cptra_uc_rst_b` through a 2FF synchronizer. A firmware-update reset only pulses the VeeR reset (`BOOT_FW_RST`).

### 5.3 Sequence (intended cold boot — what `main.c` actually does)

```mermaid
sequenceDiagram
  autonumber
  participant Board as Board reset_n / clk
  participant PD as Nios + PD (sync deassert)
  participant PIO as ctrl_pio
  participant C as Caliptra

  Board->>PD: clk already running
  Board->>PD: reset_n deassert (PD synchronizes deassert)
  Note over PIO,C: ctrl_pio = 0 after PD reset<br/>cptra_pwrgood=0, cptra_rst_b=0 (cold)
  PD->>PIO: MAGIC 1, write ctrl=1 (pwrgood)
  PIO->>C: cptra_pwrgood = 1
  Note over PD: delay(1000) software loops<br/>(spec min. 10 clk)
  PD->>PIO: write ctrl=3 (pwrgood | rst_b)
  PIO->>C: cptra_rst_b = 1 (warm-reset pin released)
  C-->>PD: ready_for_fuses (BOOT_FUSE)
  PD->>C: program PAUSER + WDT_CFG (and should program TIMER_CONFIG)
  PD->>C: soc_fuse_ctrl START → 83 FUSE_* + FUSE_WR_DONE
  C-->>PD: ready_for_fw_push / FIRMWARE_LOAD / ready_for_runtime
```

A **board `reset_n` assertion** forces both Caliptra pins low *and* resets Nios / `ctrl_pio`, so it is always a **Caliptra cold reset**. There is no hardware path that pulses only `cptra_rst_b` (warm) without also dropping pwrgood, except a Nios write of `ctrl_pio = 1` (pwrgood only) then back to `3`. Firmware never does that.

### 5.4 How Nios and Caliptra resets are related

| Event | Nios / PD | Caliptra |
|---|---|---|
| Board `reset_n` low | Reset (async assert, sync deassert in PD) | `pwrgood=0` and `rst_b=0` immediately (cold) |
| Nios comes out of reset | Runs `main`, `ctrl_pio` still 0 | Still held in cold reset until software says otherwise |
| `main` writes pwrgood, then rst_b | Running | Official cold-boot sequence (if the 10-cycle gap is kept) |
| Nios writes `ctrl_pio` bit 1 only (not implemented) | Running | Warm reset; fuses persist |
| WDT t2 / `cptra_error_fatal` | Polled; `fail()` infinite loop | Stays in fatal until something issues `cptra_rst_b` / pwrgood. **No automatic SoC reaction.** |

### 5.5 `soc_fuse_ctrl` and warm reset

`fuse_wr_done_reg_write_observed` is cleared on `cptra_noncore_rst_b`. Advance from `BOOT_FUSE` requires `fuse_done && fuse_wr_done_observed`. After a warm reset, `CPTRA_FUSE_WR_DONE` is still 1 (sticky on pwrgood) but *observed* is 0, so the SoC must write the done register again.

`soc_fuse_ctrl` has only one path: START writes all **83** `FUSE_*` words, then `FUSE_WR_DONE=1`. After a warm reset those fuse registers are write-locked (`swwel` once done is set) and `FUSE_WR_DONE` itself is not writable when already 1 (`swwe = ~done`). The sequencer would therefore either take `PSLVERR` / ERR, or write DONE without `swmod`, leaving `fuse_wr_done_observed` 0 and the Boot FSM stuck in `BOOT_FUSE`.

**Verdict:** the current cold-boot firmware path is consistent with the spec. Warm-reset bring-up is **not implemented** and the fuse IP cannot perform the required done-only write.

### 5.6 SDC / false paths

`quartus_a5e_nios/nios_caliptra.sdc`:

- `create_clock -period 20` on `clk` (50 MHz).
- `altera_reserved_tck` 40 ns, asynchronous to `clk`.
- `set_false_path -from [get_ports reset_n]`.

There are no explicit constraints matching the official RDC false-path table (CPTRA_PWRGD vs other reset groups, etc.). The false path on `reset_n` hides the unsynchronized AND into the Caliptra pins.

---

## 6. Watchdog, NMI, and fatal errors

### 6.1 What exists in 1.x RTL

Caliptra contains a **two-stage WDT** (`wdt.sv`), independent of VeeR, documented in the Hardware Spec “Watchdog timer” section. There are **no SoC pins** for t1/t2 timeout. Visibility to the SoC is:

- `CPTRA_WDT_STATUS.t1_timeout` / `t2_timeout` (SoC RO, `0x3_0104`)
- `CPTRA_HW_ERROR_FATAL.nmi_pin` (bit 2, mask `0x4`) on t2 in cascade mode
- The `cptra_error_fatal` output pin

Default mode is **cascade** (Timer 2 enable = 0):

1. ROM/FW enable Timer 1. Timer 1 counts until it matches its period.
2. **t1 timeout** raises an *internal* error interrupt to VeeR (`error_wdt_timer1_timeout_sts`). Timer 2 starts. If FW services t1 before t2 expires, both timers restart.
3. **t2 timeout in cascade** asserts `nmi_intr` (`nmi_intr = t2_timeout && !timer2_en`), which is connected to VeeR's NMI input, sets `CPTRA_HW_ERROR_FATAL.nmi_pin`, and sets `cptra_error_fatal`. Hardware Spec: “A warm reset is required by the SoC to reset the timers when Timer 2 times out.”

If Timer 2 is enabled independently, t2 is just another error IRQ (no NMI / no fatal from this path).

Timeout periods (`CPTRA_WDT_TIMERn_TIMEOUT_PERIOD`, 64-bit, default `0xFFFF_FFFF_FFFF_FFFF`) are **Caliptra-only writable** and reset on `cptra_rst_b`. The SoC-visible knob is **`CPTRA_WDT_CFG[1:0]`** (`0x3_0110/0x114`): a 64-bit cycle count, SoC RW, sticky on **pwrgood**, default **0**. rom-1.1.1 `start_wdt()` runs only when `debug_locked=1`, reads that 64-bit value, **replaces 0 with 1 cycle**, and programs WDT1.

That is why a debug-locked boot with `WDT_CFG=0` produced `HW_ERROR_FATAL=0x4` (`nmi_pin`) at cycle 213,002, and why the host/TB now write `WDT_CFG0=100_000_000`, `WDT_CFG1=0` before fuses (~2.0 s at 50 MHz, ~250 ms at 400 MHz).

### 6.2 NMI vector

There is **no NMI-vector strap** in 1.x. `internal_nmi_vector` is an internal soc_ifc register; `nmi_vector` is driven to VeeR (`nmi_vec = nmi_vector[31:1]`). ROM/FW program it. The SoC does not.

### 6.3 SoC-side reaction in this design

- `cptra_error_fatal` / `non_fatal` are packed into `status_pio` and **polled**. They are not Platform Designer IRQs (spec: both “shall be routed to SoC interrupt controller”).
- On fatal, `main.c` calls `fail(0xDEAD00FF)` and **spins forever**. It does not pulse `cptra_rst_b` (warm) or drop `cptra_pwrgood` (cold).
- A board `reset_n` would cold-reset both Nios and Caliptra (and clear sticky WDT_CFG / fuses), which is heavier than the WDT-specified warm reset but does recover the fatal pin.
- `CPTRA_TIMER_CONFIG` (generic timer / MTIME period in picoseconds) is not programmed. Boot does not need it; any FW path that calls `get_cycle_count()` would return `DRIVER_SOC_IFC_INVALID_TIMER_CONFIG`.

### 6.4 Verdict

WDT **inside** Caliptra is intact and the host's `WDT_CFG` programming is the right production-mimic fix for debug-locked ROM. The **SoC reaction path is missing**: no IRQ, no automatic warm reset after t2, no dedicated t1/t2 observability beyond polling `status_pio` / `CPTRA_HW_ERROR_FATAL`. Severity: **Medium (FAIL vs integration requirements; study boot still passes if the host keeps servicing the mailbox and the 100e6-cycle WDT1 does not expire).**

---

## 7. Boot / bring-up sequence

This is what `quartus_a5e_nios/sw/app/main.c` does (same sequence as `sim/tb_nios_top_fw.sv`). MAGIC values are written to `magic_pio`.

1. **MAGIC `0x1` — alive.** Nios is out of reset. Caliptra is still in cold reset (`ctrl_pio=0`).
2. **Power-good.** Write `ctrl_pio = 1` (`cptra_pwrgood`). Clock is already running.
3. **Wait**, then **release `cptra_rst_b`.** Write `ctrl_pio = 3`. Official Boot FSM: at least 10 clocks between pwrgood and reset release.
4. **Poll `ready_for_fuses`** (`status_pio[0]`), servicing ETRNG if it appears. Timeout → MAGIC `0xDEAD0001`.
5. **MAGIC `0x2`.** Read `CPTRA_HW_REV_ID` (fail `0xDEAD0002` if 0 or all-ones). At this pre-fuse point expect `0x0000_0011`.
6. **Program mailbox PAUSER** slot 0 = `1` and lock it. **Program `CPTRA_WDT_CFG`** = 100,000,000 / 0 (required when `debug_locked=1`). `CPTRA_TIMER_CONFIG` is *not* programmed. **MAGIC `0x3`.**
7. **Fuse programming (hardware IP, not Nios writing `FUSE_*`).** Check fuse-ctrl ID `0x46555345`. Write `CTRL.START`. IP waits for `ready_for_fuses` (else ERR), then writes all **83** `FUSE_*` words from `fw/fuse_image.hex` over APB starting at `0x3_0200`, then writes `CPTRA_FUSE_WR_DONE = 1`. Nios only polls `STATUS`. Fail `0xDEAD0003`–`0xDEAD0006` on bad ID, timeout, `ERR`, or done-bit not set. **MAGIC `0x4`.**
8. **ROM boot.** Boot FSM leaves `BOOT_FUSE`, releases `cptra_uc_rst_b`, and ROM runs (including `start_wdt()` because debug is locked). Nios **must** keep servicing `etrng_req` (xorshift stand-in). Poll `ready_for_fw_push`. Timeout → `0xDEAD0007`. **MAGIC `0x5`.**
9. **Mailbox `FIRMWARE_LOAD`.** Acquire `MBOX_LOCK`, check `MBOX_USER==1`, write CMD `"FWLD"`, `DLEN=FW_BYTES` (109000), stream words from `soc_fw_store`, set `EXECUTE=1`. **MAGIC `0x6`.** Poll `MBOX_STATUS`, still servicing TRNG. Complete (2) vs failure (3 / `0xDEAD000B`). Clear `EXECUTE`. **MAGIC `0x7`.**
10. **Poll `ready_for_runtime`.** Read `CPTRA_FW_REV_ID*`. Fail `0xDEAD000C` on timeout, `0xDEAD000D` if fatal/non-fatal is set.
11. **MAGIC `0xCA11F00D`** (LED = `0x0D`). Idle loop continues to service runtime TRNG requests.

Verilator result (2026-11-03, behavioral Nios, not the full PD CPU): **PASS** at cycle 24,064,873 after 32 TRNG fills; `MBOX_STATUS=2`. Full PD Nios V simulation needs Intel Questa/ModelSim plus Quartus libraries and has not been run.

---

## 8. TRNG section (review)

**Mode:** External TRNG API (ETRNG). `CALIPTRA_INTERNAL_TRNG` is off; `itrng_valid` is tied 0, so the internal entropy_src / CSRNG path is not built, and no physical bitstream is provided.

**Who services it:** Nios firmware (`trng_service` in `main.c`), not a hardware gasket. Handshake is the official one: `etrng_req` → 12 words in `CPTRA_TRNG_DATA*` → `CPTRA_TRNG_STATUS.DATA_WR_DONE` → request drops. ROM/FW time out after 250,000 polls of DONE if the SoC is silent.

**Entropy source:** Software **xorshift32**, seed `0x1234ABCD`. Simulation uses `$urandom`. There is no FPGA TRNG, no ring-oscillator, no LFSR in RTL.

**Security:**

- Not a NIST SP 800-90B entropy source.
- Integration Spec: *“It is a requirement for FIPS compliance that this TRNG HW API is always handled by SoC hardware gasket logic (and not some SoC ROM or firmware code).”* This design violates that on purpose for bring-up.
- Spec also strongly prefers enabling `CALIPTRA_INTERNAL_TRNG` and wiring a physical PTRNG to `itrng_data` / `itrng_valid` (~50 kHz valid rate).
- TRNG PAUSER is unlocked. API text says lock=0 means any APB agent can write TRNG DATA (and the passing sim matches that). A later “programming rules” row says unprogrammed lock means *no* agent is accepted — that row does not match this v1.1 RTL behavior, but locking PAUSER to a gasket ID is still the recommended threat-model posture and is **not** done here.

**Verdict:** Wired correctly for an ETRNG *bring-up* hook, and enough for the ROM/FW boot that passed in Verilator. **Test-only. Do not treat boot measurements, IDevID, or any Caliptra-derived key as trustworthy on this FPGA image.**

---

## 9. Fuse section (review)

**Mechanism:** A **hardware fuse-controller soft IP** (`soc_fuse_ctrl.sv`), not Nios poking `FUSE_*` registers. This matches the Integration Spec rule “SoC shall write fuse registers and fuse done via immutable logic or ROM code” *in structure* (an FSM in RTL). It is still only an FPGA stand-in for OEM OTP + sequencer: the image is a `$readmemh` of `fw/fuse_image.hex` into on-chip storage, regenerated by `scripts/gen_fuse_image.py`. Anyone who can rebuild the bitstream can change UDS / field entropy / PK hashes.

**Sequencing (cold boot):** Nios waits for `ready_for_fuses`, optionally programs PAUSER/WDT, then pulses START. The IP errors if `ready_for_fuses` is low. It writes 83 words at `0x3_0200 + 4*i`, then `CPTRA_FUSE_WR_DONE=1` at `0x3_00B0`. Fuses are one-time per **power-good**. Warm-reset handling is **missing** (see §5.5).

**APB ownership:** While `busy`, the APB mux gives the fuse IP the bus. Nios is expected only to poll fuse-ctrl STATUS (a local slave, not Caliptra APB). There is no additional hardware interlock if software also issues a Caliptra-window access during the push.

**Fuse PAUSER:** `CPTRA_SET_FUSE_PAUSER_INTEG = 0` in upstream `soc_ifc_pkg.sv`; this project does not lock `CPTRA_FUSE_VALID_PAUSER`. Writes go out with `PAUSER=1` and were accepted in sim.

**Image contents** (`fw/fuse_image.hex`, 83 words, STUDY values only):

| Fuse | Value in this image |
|---|---|
| `FUSE_UDS_SEED[0..11]` | Deterministic STUDY words (`0x1F2E3D4C ^ 0x9E3779B9*(i+1)`). These are the words programmed into the fuse *registers* (the payload DOE consumes with `cptra_obf_key`). They are **not** documented as a real, provisioned, pre-obfuscated UDS, and they are **not** unique per device. |
| `FUSE_FIELD_ENTROPY[0..7]` | Deterministic STUDY words (`0xA7C3E519 ^ 0x85EBCA6B*(i+1)`). Same caveats. |
| `FUSE_KEY_MANIFEST_PK_HASH[0..11]` | SHA-384 of the vendor public-key descriptor in `fw/caliptra-fw-bundle.bin`, 12 big-endian words (caliptra-sw `bytes_to_be_words_48`). |
| `FUSE_KEY_MANIFEST_PK_HASH_MASK` | 0 (no vendor ECC key revoked) |
| `FUSE_OWNER_PK_HASH[0..11]` | SHA-384 of the owner public-key descriptor, same packing. |
| `FUSE_FMC_KEY_MANIFEST_SVN` | 0 (bundle FMC SVN is 0; ROM requires image SVN ≥ fuse SVN) |
| `FUSE_RUNTIME_SVN[0..3]` | 0 (bundle RT SVN is 0) |
| `FUSE_ANTI_ROLLBACK_DISABLE` | 0 |
| `FUSE_IDEVID_CERT_ATTR[0..23]` | 0 |
| `FUSE_IDEVID_MANUF_HSM_ID[0..3]` | 0 |
| `FUSE_LIFE_CYCLE` | `0x3` (Production), matches the `DEVICE_PRODUCTION` strap |
| `FUSE_LMS_VERIFY` / `FUSE_LMS_REVOCATION` | 0 |
| `FUSE_SOC_STEPPING_ID` | `0x00000001` (A0 test); also reflected in `CPTRA_HW_REV_ID[31:16]` after it is written |

Re-run `scripts/gen_fuse_image.py` if the FW bundle is re-signed. UDS/FE are never exposed through fuse-ctrl MMIO; Nios must not (and the boot ROM does not need to) read them back.

**Lifecycle straps vs fuses:** Both are Production (`2'b11` / fuse `0x3`) with debug locked. This is a hardwired mimic so ROM/FW take the production path (including WDT). It is not a real manufacturing/production lifecycle controller.

---

## 10. Review findings

Severities: **High** = security or correctness risk if this image were treated as more than a study; **Medium** = real mismatch or missing integration item that should be fixed before hardware bring-up / any hardening; **Low** = limitation or tidy-up.

### High — test-only / insecure if mistaken for production

| ID | Finding |
|---|---|
| H1 | **TRNG is a software xorshift** serviced by mutable Nios firmware over ETRNG registers. No iTRNG, no physical entropy, no hardware gasket. Official FIPS/threat-model requirements are not met. |
| H2 | **`cptra_obf_key` is a fixed study localparam** in RTL (and therefore in the bitstream and this repo). Not PUF/HSM provisioned, not protected from scan/debug as the spec requires. |
| H3 | **Fuse “OTP” is an on-chip hex image.** STUDY UDS and field entropy are deterministic and rebuildable. No manufacturing burn, no field-entropy API with anti-replay, no debug-path disable in PRODUCTION beyond what Caliptra already does for those two register files. |
| H4 | **Lifecycle is hardwired** to `DEVICE_PRODUCTION` + `debug_locked`. The SoC does not drive a real security-state strap. |

### Medium — mismatches, bugs, or missing required connections

| ID | Finding |
|---|---|
| M1 | **`generic_input_wires[31:0]` is driven by `magic_pio`.** The v1.1 Integration Spec binds bit 0 as *zeroization status* and requires bits 63:1 be tied to 0 with **no** run-time flops. Nios writes MAGIC `1` immediately at boot, which also asserts bit 0. The Verilator production-mimic still reached `ready_for_runtime`, so rom-1.1.1 did not fail the boot in this configuration, but the wiring is a spec violation and should be tied off (drive LEDs from `magic_pio` only). *Not fixed in this documentation-only change.* |
| M2 | **TRNG PAUSER is never programmed or locked.** Boot relies on unlocked “any agent may write TRNG DATA” behavior. |
| M3 | **Fuse PAUSER is not hardened** (`CPTRA_SET_FUSE_PAUSER_INTEG=0`, lock never written). Any APB agent that can reach soc_ifc before `FUSE_WR_DONE` can write fuses. |
| M4 | **`quartus_a5e_nios/README.md` is stale** in “Firmware” and “Not done”: it still describes a one-word TEST UDS poke, `ROM_INIT_FILE=""`, and FIRMWARE_LOAD as future work. RTL/FW already perform the full 83-word fuse push, load rom-1.1.1, and `FIRMWARE_LOAD` the bundle. |
| M5 | **`cptra_error_fatal` / `cptra_error_non_fatal` are not IRQs** and the host has **no reset reaction**. Integration Spec: both shall be routed to the SoC interrupt controller; fatal recovery is a power-good reset; WDT t2 needs a warm reset to restart the timers. `main.c` only polls and `fail()`-spins. Only `jtag_uart` is in the PD interrupt map. |
| M6 | **No hardware mutex** beyond the `fuse_busy` APB mux. Current FW is careful; a buggy host could overlap Nios APB with the fuse FSM. |
| M7 | **No external synchronizers on `cptra_pwrgood` / `cptra_rst_b`.** Spec RDC: integrator must synchronize both to `clk` before they enter Caliptra. The pins are `ctrl_pio & reset_n` with `reset_n` an SDC false path. PIO writes are synchronous; the `reset_n` term is not. |
| M8 | **Mailbox / ICCM / DCCM are not explicitly zeroed** (and no SRAM repair) before `cptra_rst_b` deassert, which the spec requires on a power-good cycle. |
| M9 | **Clock / pins:** 50 MHz board clock, no PLL, no on-die oscillator, almost all I/O still **virtual pins** (only `clk` and `reset_n` are real in the QSF). Not board-proven. |
| M10 | **No warm-reset fuse path.** `soc_fuse_ctrl` always rewrites all 83 fuses then DONE. After a warm reset those writes are locked and the required done-only `swmod` may never be observed, leaving the Boot FSM in `BOOT_FUSE`. The current host only cold-boots, so the intended path is OK. |
| M11 | **No Intel Reset Release IP / `ninit_done`, no PLL-lock in reset.** Quartus already flagged a missing Reset Release IP on the sibling A5E build. Needed before a kit bring-up. |
| M12 | **`CPTRA_TIMER_CONFIG` left at 0.** SoC should program the clock period in picoseconds (20,000 for 50 MHz). Boot still passed; FW `get_cycle_count()` would fail if used. |

### Low

| ID | Finding |
|---|---|
| L1 | Caliptra QSPI and UART are tied off / compiled out. Expected; firmware comes from `soc_fw_store`, not flash. |
| L2 | Caliptra JTAG TAP is tied off (`trst_n=0`). Nios JTAG UART/debug is separate and is connected. Fine for debug-locked study; not a TAP endpoint. |
| L3 | `generic_output_wires[63:24]` never reach Nios. |
| L4 | Window hole `0x1C000–0x1EFFF` aliases FW-store word 0. |
| L5 | ICache SRAMs are still in the VeeR export (area leftover; not a functional bug for this 1.x config). |
| L6 | `PSLVERR` is not propagated as an Avalon/AXI response to the Nios CPU (`USE_RESPONSE` off). Fuse IP *does* latch `PSLVERR` into its ERR bit. |
| L7 | Full Platform Designer Nios V + interconnect is not simulated; Verilator uses a behavioral host. |

### Doc vs RTL mismatches (summary)

- `quartus_a5e_nios/README.md` Firmware / Not-done sections: **stale** (see M4).
- Top-level `README.md`, the architecture section of the Nios README, and `sim/BOOT_NIOS_TOP_PROD.md`: **aligned** with RTL on fuse IP, ETRNG, ROM hex, and `0xCA11F00D`.
- First revision of this note: `CPTRA_HW_REV_ID` oversimplified as always `0x0000_0011`; reset-synchronizer requirement understated; warm-reset fuse path and WDT/fatal SoC reaction not fully spelled out. Corrected above.
- Official Integration Spec vs this FPGA glue: ETRNG-by-firmware, study key, soft OTP, generic_input ← magic_pio, unlocked TRNG/fuse PAUSER, no iTRNG, no Caliptra TAP, no reset synchronizers, no Reset Release IP, virtual pins — all called out above.

---

## 11. Spec compliance checklist

Requirements are from caliptra-rtl v1.1 Integration Spec (interface tables, Boot FSM, Fuses, RDC, Table 17 “SoC integration requirements”, error-recovery flow) and Hardware Spec (WDT, clock gating, security state), audited against this FPGA glue at `32924ba`.

| Requirement | Spec ref | Our implementation | Status |
|---|---|---|---|
| Clock running before `cptra_pwrgood` | Integ Table 17, clocks | Free-running `clk` (50 MHz SDC) | **PASS** (study clock; see oscillator row) |
| ≥ 10 clocks from pwrgood to `rst_b` deassert | Integ Boot FSM | `delay(1000)` / TB 20 cycles | **PASS** (cold-boot FW path) |
| `cptra_pwrgood` / `cptra_rst_b` pre-synchronized to `clk`; deassert synchronous | Integ RDC constraints | `ctrl_pio & reset_n`; no 2FF; `reset_n` false-pathed | **FAIL** |
| pwrgood deassert = cold reset; `rst_b` only = warm reset | Integ Interface rules | Wiring can do both; FW only performs cold boot. Board `reset_n` always cold-resets Caliptra (and Nios). | **PASS** (cold path) / **OPEN** (no warm-reset host) |
| Fuses persist across warm reset; SoC must rewrite `FUSE_WR_DONE` in `BOOT_FUSE` | Integ Fuses / Boot FSM | RTL sticky as specified. `soc_fuse_ctrl` has no done-only mode. | **FAIL** (warm path) / **PASS** (cold path) |
| Fuse writes + done via immutable logic or ROM | Integ Table 17 | `soc_fuse_ctrl` FSM (good structure) but image is a rebuildable hex in M20K | **TEST-ONLY** |
| UDS/FE come from OTP, no debug inject | Integ Table 17 | Hex image + STUDY values | **TEST-ONLY** |
| Security state driven from SoC security state | Integ Table 17 / HW Security state | Hardwired PRODUCTION + debug_locked | **TEST-ONLY** |
| `scan_mode` 0 in functional mode; 1 before scan | Integ DFT / RDC | Tied 0; no scan | **PASS** (FPGA functional) |
| `BootFSM_BrkPoint` / `CPTRA_BOOTFSM_GO` | Integ Interface rules | Strap wired to `ctrl_pio[2]`, default 0; GO unused | **PASS** |
| `ready_for_fuses` / `fw_push` / `runtime` connected and used | Integ Table 7 | `status_pio[2:0]`, polled by FW | **PASS** |
| `mailbox_data_avail` / `mailbox_flow_done` visible to SoC | Integ Table 7 | `status_pio[4:3]`, polled (no IRQ) | **PASS** (connectivity) |
| `cptra_error_fatal` / `non_fatal` routed to SoC interrupt controller | Integ error recovery / Table 17 | `status_pio` only; no IRQ, no reset reaction | **FAIL** |
| Recover fatal via power-good reset; WDT t2 via warm reset | Integ Table 17; HW WDT | Host `fail()`-spins; board reset would cold-reset everything | **FAIL** |
| SoC programs `CPTRA_WDT_CFG` before debug-locked ROM starts WDT | HW WDT; rom-1.1.1 `start_wdt` | Writes 100,000,000 / 0 before fuses | **PASS** |
| t1/t2 timeout visible / handled | HW WDT | No t1/t2 pins (none in 1.x); status/fatal registers not used by host IRQ logic | **OPEN** |
| NMI vector strap | (n/a in 1.x) | Internal register only; correctly not a pin | **PASS** (N/A as strap) |
| Input clock from on-die oscillator; defend clock attacks | Integ Table 17 | Board oscillator, 50 MHz, no PLL | **TEST-ONLY** / **OPEN** |
| SoC shall not independently power-gate Caliptra; clock gating is the `CPTRA_CLK_GATING_EN` + FW halt mechanism | Integ Table 17; HW Clock gating | Input clk ungated; `CLK_GATING_EN` left 0 | **PASS** |
| Program `CPTRA_TIMER_CONFIG` (ps period) if MTIME conversion is used | soc_ifc RDL / drivers | Left 0 | **OPEN** |
| TRNG: dedicated iTRNG, or ETRNG via immutable gasket; lock TRNG PAUSER | Integ TRNG API / Table 17 | ETRNG + Nios xorshift; PAUSER unlocked | **TEST-ONLY** / **FAIL** (FIPS) |
| Mailbox PAUSER programmed/locked or set at integration | Integ MAILBOX PAUSER rules | Slot 0 = 1, locked in FW before mailbox use. Default remains `0xFFFFFFFF`. | **PASS** (FW path) |
| Fuse PAUSER locked or hardened at integration | Integ FUSE PAUSER rules | Neither | **FAIL** |
| PAUSER driven correctly on APB | Integ Table 17 | Constant 1 from `avmm_to_apb` | **PASS** |
| SRAM 1-cycle read, sized for SECDED | Integ SRAM / Table 17 | `caliptra_sram` / VeeR export, 39-bit mailbox | **PASS** (FPGA model) |
| SRAM zero + repair on pwrgood, before `rst_b` deassert | Integ Table 17 | Not implemented | **FAIL** |
| `generic_input` bit 0 = zeroization status; 63:1 tied 0, no flops | Integ late-binding Table 12 | `{32'h0, magic_pio}` | **FAIL** |
| Obfuscation key stable before reset, not a software value, off scan | Integ straps / Table 17 | Fixed study localparam in RTL | **TEST-ONLY** |
| Caliptra TAP as TAP endpoint; `jtag_trst_n` sync deassert | Integ Table 17 / JTAG | TAP tied off (`trst_n=0`) | **OPEN** / **TEST-ONLY** |
| QSPI / UART only if defines enabled | Integ parameters | Defines off; QSPI tied off | **PASS** |
| No 2.x `strap_ss_*` required | 1.x `caliptra_top` ports | None present; none wired | **PASS** (N/A) |
| Agilex `ninit_done` / Reset Release before user logic | Intel A5E / Quartus warning | Not instantiated | **OPEN** (board bring-up) |

---

## 12. Open items

- Add **external 2FF synchronizers** on `cptra_pwrgood` and `cptra_rst_b` (and stop false-pathing the unsynchronized `reset_n` term into those pins).
- Add Intel **Reset Release IP** (`ninit_done`) and, if the kit clock is not 50 MHz, a **PLL + lock** in the reset qualification.
- Implement a **warm-reset path**: pulse only `cptra_rst_b`, and extend `soc_fuse_ctrl` (or Nios) to write **only** `FUSE_WR_DONE` when fuses already persist.
- Route `cptra_error_fatal` / `non_fatal` (and optionally `etrng_req`, `mailbox_data_avail`) as **Nios IRQs**. On fatal, issue the specified reset (warm for WDT t2; power-good for general fatal recovery).
- Program **`CPTRA_TIMER_CONFIG`** = 20,000 (50 MHz period in ps), or whatever the final clock is.
- Finish Quartus **route + timing** on a ≥32 GB host (placement already succeeded; routing OOM’d at ~16 GB). Programming-file / `.sof` still depends on a valid **SW-AGILEX-5E** license that includes programming-file generation (Error 23714 was seen on a related project license).
- Assign a real **board pinout** and I/O standards.
- Replace ETRNG xorshift with a **hardware entropy source** (preferably `CALIPTRA_INTERNAL_TRNG` + `itrng_*`, or an immutable ETRNG gasket) and lock TRNG PAUSER.
- Replace `soc_fuse_ctrl`’s hex image with a real (or better FPGA-emulated) **OTP**, provision unique UDS/FE, lock fuse PAUSER, and stop treating STUDY hashes/keys as secrets.
- **Fix `generic_input_wires`** (tie reserved bits to 0; do not connect `magic_pio`).
- Zero (and, on ASIC, repair) SRAMs on power-good before releasing `cptra_rst_b`.
- Simulate the **real PD Nios V** system (Questa + Quartus libs), and bring the design up on the A5E kit once a SOF exists.
- Manufacturing items not in scope here: IDevID certificate provisioning, field-entropy API, FIPS zeroization API, scandump exclusion for the obfuscation key.

---

## 13. Source index

| Path | Role |
|---|---|
| `rtl/caliptra_passive_top.sv` | Caliptra 1.x wrapper, memories, QSPI tie-offs |
| `quartus_a5e_nios/rtl/nios_caliptra_top.sv` | Top: PD system, window decode, APB mux, straps, TRNG/reset tie-offs |
| `quartus_a5e_nios/rtl/avmm_to_apb.sv` | Avalon → APB3, `PAUSER=1` |
| `quartus_a5e_nios/rtl/soc_fuse_ctrl.sv` | Fuse sequencer soft IP (cold-boot only) |
| `quartus_a5e_nios/rtl/soc_fw_store.sv` | FW-bundle M20K |
| `quartus_a5e_nios/qsys/nios_caliptra_sys.tcl` | Regeneratable PD system |
| `quartus_a5e_nios/sw/app/main.c` | Nios boot ROM (pwr/reset, PAUSER, WDT_CFG, fuse START, ETRNG, FW load) |
| `quartus_a5e_nios/nios_caliptra.sdc` | 50 MHz `clk`, false path on `reset_n` |
| `scripts/gen_fuse_image.py` / `fw/fuse_image.hex` | STUDY OTP image |
| `fw/caliptra-rom.hex`, `fw/caliptra-fw-bundle.hex` | ROM 1.1.1 and signed 1.x bundle |
| `sim/tb_nios_top_fw.sv`, `sim/run_nios_top_fw.sh` | Verilator production-mimic TB |
| caliptra-rtl v1.1 `5f85fb4` `docs/CaliptraIntegrationSpecification.md` | Official SoC interface, Boot FSM, RDC, Table 17 |
| caliptra-rtl v1.1 `docs/CaliptraHardwareSpecification.md` | WDT, clock gating, security state |
| caliptra-rtl v1.1 `src/soc_ifc/rtl/soc_ifc_boot_fsm.sv`, `wdt.sv`, `soc_ifc_top.sv` | Boot FSM, WDT/NMI/fatal, fuse sticky / observed |

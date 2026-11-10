# Nios V ↔ Caliptra 1.x Integration Note

- **Project:** Caliptra 1.x (passive) on Intel Agilex 5 E **A5EC065BB32AE6S**, Nios V/m mailbox host (AXI4-lite → Avalon → APB).
- **Repo:** [pwilliam282/caliptra-a5e-quartus](https://github.com/pwilliam282/caliptra-a5e-quartus)
- **This document:** [`docs/NIOS_CALIPTRA_INTEGRATION.md`](https://github.com/pwilliam282/caliptra-a5e-quartus/blob/main/docs/NIOS_CALIPTRA_INTEGRATION.md)
- **RTL reviewed at:** `32924ba` (main, 2026-11-03 production-lifecycle mimic). No RTL was changed for this note.
- **Date:** 2026-11-10 (America/Chicago).
- **Scope:** FPGA study / production-flow *mimic*. STUDY keys, UDS, field entropy, and TRNG are **not** production secrets or a FIPS entropy source.

This is the complete connection map and bring-up note for the Nios host design. It is based on the *actual* RTL, Platform Designer system, and Nios firmware, then compared with the earlier in-repo notes and the official Caliptra 1.x Integration Specification (caliptra-rtl v1.1).

---

## 1. Where the earlier connection-map docs live

There was **no** `docs/` tree and no single integration note in the repo before this file. The Nios ↔ Caliptra map was spread across these documents (all still present):

| Document | What it covers | Status vs RTL at `32924ba` |
|---|---|---|
| [`quartus_a5e_nios/README.md`](https://github.com/pwilliam282/caliptra-a5e-quartus/blob/main/quartus_a5e_nios/README.md) | Closest thing to a connection map: ASCII block diagram, Nios address map, straps, fuse-image summary | **Architecture / address-map / strap sections are mostly accurate.** The **Firmware** and **Not done** sections are stale (see §8). |
| [`README.md`](https://github.com/pwilliam282/caliptra-a5e-quartus/blob/main/README.md) | Top-level overview: fuse controller, ETRNG service, FIRMWARE_LOAD, MAGIC `0xCA11F00D` | Accurate at a high level. |
| [`sim/BOOT_NIOS_TOP_PROD.md`](https://github.com/pwilliam282/caliptra-a5e-quartus/blob/main/sim/BOOT_NIOS_TOP_PROD.md) | Verilator production-mimic boot (PASS at cycle 24,064,873, 32 TRNG fills) | Accurate for the behavioral-Nios TB. |
| [`STUDY.md`](https://github.com/pwilliam282/caliptra-a5e-quartus/blob/main/STUDY.md) | C10 GX / A5E fit study (ALMs, routing OOM) | Not a signal map; still the place for fit numbers. |

Official SoC-interface rules (ports, Boot FSM, fuse/TRNG PAUSER, SRAM export) are in chipsalliance **Caliptra Integration Specification** (caliptra-rtl v1.1, tag used here: `5f85fb4`). That file is *not* vendored in this git repo; get it with the RTL from release [rtl-20261101](https://github.com/pwilliam282/caliptra-a5e-quartus/releases/tag/rtl-20261101) or `caliptra-rtl` v1.1 `docs/CaliptraIntegrationSpecification.md`.

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
  magic -->|"generic_input_wires[31:0]<br/>SPEC ISSUE: see §8"| ctop

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
        +-- magic_pio (out) --> led[7:0]  and  generic_input_wires[31:0]  (! see §8)
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

---

## 3. Full signal connection table

Widths and official roles follow caliptra-rtl v1.1 `caliptra_top` / Integration Spec Tables 4–11. “FPGA source/sink” is what `nios_caliptra_top.sv` and `caliptra_passive_top.sv` actually wire.

### 3.1 Clocks and resets

| Caliptra port | W | FPGA source / sink | Notes |
|---|---:|---|---|
| `clk` | 1 | Board `clk` (top port). Shared by Nios, glue, and Caliptra. | SDC: 50 MHz (`period 20 ns`). No PLL. Spec validates up to 400 MHz and wants an on-die oscillator; this is a board-oscillator FPGA study clock. Clock is running before Nios asserts `cptra_pwrgood`. |
| `cptra_pwrgood` | 1 | `ctrl_pio[0] & reset_n` | Active-high. PIO reset value 0 ⇒ Caliptra held unpowered until Nios writes bit 0. Board `reset_n` also forces it low. Spec: async assert, sync deassert. PIO writes are synchronous; the `reset_n` term is a raw async AND, and `reset_n` is a false path in the SDC. |
| `cptra_rst_b` | 1 | `ctrl_pio[1] & reset_n` | Active-low. Same AND as above. Nios waits a software delay (~1000 loop iterations; TB waits 20 cycles) after pwrgood; official minimum is **10 clocks**. |

Top-level `reset_n` also resets the Platform Designer system (clock_source `resetSynchronousEdges DEASSERT`) and the glue (`avmm_to_apb`, `soc_fuse_ctrl`).

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
| `ready_for_fuses` | 1 | `status_pio[0]` and `soc_fuse_ctrl.ready_for_fuses` | START is rejected if this is low. |
| `ready_for_fw_push` | 1 | `status_pio[1]` | Nios waits, then issues mailbox `FIRMWARE_LOAD`. |
| `ready_for_runtime` | 1 | `status_pio[2]` | Success criterion; MAGIC `0xCA11F00D`. |
| `mailbox_data_avail` | 1 | `status_pio[3]` | Level status only — **not** connected to a Nios IRQ. |
| `mailbox_flow_done` | 1 | `status_pio[4]` | Same. |
| `cptra_error_fatal` | 1 | `status_pio[5]` | Polled (`0xDEAD00FF` / `0xDEAD000D`). Not an IRQ. Spec: recover fatal only with a power-good reset. |
| `cptra_error_non_fatal` | 1 | `status_pio[6]` | Polled at the end of boot. |
| `BootFSM_BrkPoint` | 1 | `ctrl_pio[2]` | Reset value 0 (do not halt Boot FSM). |

The only Platform Designer IRQ is `jtag_uart` at irqNumber 0. Caliptra status is polled.

### 3.4 TRNG

`CALIPTRA_INTERNAL_TRNG` is **commented out** in upstream `config_defines.svh`, so this build is **external-source (ETRNG) mode**.

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
| `cptra_obf_key` | 256 | Localparam `STUDY_PROD_MIMIC_OBF_KEY` in `nios_caliptra_top.sv` | Fixed study value, always driven. **Not** a product secret; visible in RTL/bitstream. Real silicon would ECO/PUF this and keep it off scan. Latched on a power-good cycle per the spec. |
| `security_state.device_lifecycle` | 2 | Hardwired `2'b11` (`DEVICE_PRODUCTION`) | Production-*flow mimic*, not a live SoC lifecycle strap. |
| `security_state.debug_locked` | 1 | Hardwired `1'b1` | Debug locked. Because of this, ROM arms WDT1 from `CPTRA_WDT_CFG`; Nios programs timeout `100,000,000` (a 0 timeout is a 1-cycle fatal NMI — already hit and fixed in FW/TB). |
| `scan_mode` | 1 | Tied `1'b0` | Correct for this FPGA (no DFT). |
| `generic_input_wires` | 64 | `{32'h0, magic_out}` | **Spec mismatch.** Official binding: bit 0 = fuse zeroization status; bits 63:1 reserved and must be tied 0, not connected to flops. Here bits 31:0 track `magic_pio`, so MAGIC `1` at start of boot also sets bit 0. See §8. |
| `generic_output_wires` | 64 | `[23:0]` packed into `status_pio[31:8]`; `[63:24]` not visible to Nios | ROM/FW character log in the TB uses bits `[8:0]` (bit 8 toggles, `[7:0]` is the char). |
| `jtag_tck/tms/tdi` | 1 | Tied 0 | Caliptra TAP not brought out. |
| `jtag_trst_n` | 1 | Tied 0 | Held in reset. |
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

Spec also wants SRAM repair only on power-good, and SRAM contents zeroed before `cptra_rst_b` deassert. This FPGA design does not implement a repair/zeroization pass (open item).

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
| `0x0008_0040` | 64 B | Nios V `timer_sw_agent` (mtime) |
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

| Offset | Register | Use in this host |
|---|---|---|
| `0x2_0000` | `MBOX_LOCK` | Acquire before `FIRMWARE_LOAD` |
| `0x2_0004` | `MBOX_USER` | Must equal `1` (our PAUSER) |
| `0x2_0008` | `MBOX_CMD` | `0x46574C44` (`"FWLD"`) |
| `0x2_000C` | `MBOX_DLEN` | Bundle length in bytes |
| `0x2_0010` | `MBOX_DATAIN` | Word stream from `soc_fw_store` |
| `0x2_0018` | `MBOX_EXECUTE` | 1 to start, 0 to release |
| `0x2_001C` | `MBOX_STATUS` | 2 = CMD_COMPLETE, 3 = CMD_FAILURE |
| `0x3_003C` | `CPTRA_FLOW_STATUS` | Includes `ready_for_*` bits |
| `0x3_0048` / `0x3_005C` | `CPTRA_MBOX_VALID_PAUSER[0]` / `LOCK[0]` | Programmed to 1 / 1 before mailbox use |
| `0x3_0078`–`0x3_00A4` | `CPTRA_TRNG_DATA[0..11]` | 12 ETRNG words |
| `0x3_00AC` | `CPTRA_TRNG_STATUS` | Write 2 = `DATA_WR_DONE` |
| `0x3_00B0` | `CPTRA_FUSE_WR_DONE` | Written by `soc_fuse_ctrl`, then checked by Nios |
| `0x3_00D4` | `CPTRA_HW_REV_ID` | Expect `0x0000_0011` (generation 1.1) |
| `0x3_00D8` / `0x3_00DC` | `CPTRA_FW_REV_ID0/1` | Read after `ready_for_runtime` |
| `0x3_0110` / `0x3_0114` | `CPTRA_WDT_CFG0/1` | `100_000_000` / `0`, programmed **before** fuses |
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

## 5. Boot / bring-up sequence

This is what `quartus_a5e_nios/sw/app/main.c` does (same sequence as `sim/tb_nios_top_fw.sv`). MAGIC values are written to `magic_pio`.

1. **MAGIC `0x1` — alive.** Nios is out of reset.
2. **Power-good.** Write `ctrl_pio = 1` (`cptra_pwrgood`). Clock is already running.
3. **Wait**, then **release `cptra_rst_b`.** Write `ctrl_pio = 3`. Official Boot FSM: at least 10 clocks between pwrgood and reset release.
4. **Poll `ready_for_fuses`** (`status_pio[0]`), servicing ETRNG if it appears. Timeout → MAGIC `0xDEAD0001`.
5. **MAGIC `0x2`.** Read `CPTRA_HW_REV_ID` (fail `0xDEAD0002` if 0 or all-ones). Expect `0x0000_0011`.
6. **Program mailbox PAUSER** slot 0 = `1` and lock it. **Program `CPTRA_WDT_CFG`** = 100,000,000 / 0 (required when `debug_locked=1`). **MAGIC `0x3`.**
7. **Fuse programming (hardware IP, not Nios writing `FUSE_*`).** Check fuse-ctrl ID `0x46555345`. Write `CTRL.START`. IP waits for `ready_for_fuses` (else ERR), then writes all **83** `FUSE_*` words from `fw/fuse_image.hex` over APB starting at `0x3_0200`, then writes `CPTRA_FUSE_WR_DONE = 1`. Nios only polls `STATUS`. Fail `0xDEAD0003`–`0xDEAD0006` on bad ID, timeout, `ERR`, or done-bit not set. **MAGIC `0x4`.**
8. **ROM boot.** Internal Boot FSM leaves `BOOT_FUSE`, releases the Caliptra core reset, and ROM runs. Nios **must** keep servicing `etrng_req` (xorshift stand-in). Poll `ready_for_fw_push`. Timeout → `0xDEAD0007`. **MAGIC `0x5`.**
9. **Mailbox `FIRMWARE_LOAD`.** Acquire `MBOX_LOCK`, check `MBOX_USER==1`, write CMD `"FWLD"`, `DLEN=FW_BYTES` (109000), stream words from `soc_fw_store`, set `EXECUTE=1`. **MAGIC `0x6`.** Poll `MBOX_STATUS`, still servicing TRNG. Complete (2) vs failure (3 / `0xDEAD000B`). Clear `EXECUTE`. **MAGIC `0x7`.**
10. **Poll `ready_for_runtime`.** Read `CPTRA_FW_REV_ID*`. Fail `0xDEAD000C` on timeout, `0xDEAD000D` if fatal/non-fatal is set.
11. **MAGIC `0xCA11F00D`** (LED = `0x0D`). Idle loop continues to service runtime TRNG requests.

Verilator result (2026-11-03, behavioral Nios, not the full PD CPU): **PASS** at cycle 24,064,873 after 32 TRNG fills; `MBOX_STATUS=2`. Full PD Nios V simulation needs Intel Questa/ModelSim plus Quartus libraries and has not been run.

---

## 6. TRNG section (review)

**Mode:** External TRNG API (ETRNG). `CALIPTRA_INTERNAL_TRNG` is off; `itrng_valid` is tied 0, so the internal entropy_src / CSRNG path is not fed a physical bitstream.

**Who services it:** Nios firmware (`trng_service` in `main.c`), not a hardware gasket. Handshake is the official one: `etrng_req` → 12 words in `CPTRA_TRNG_DATA*` → `CPTRA_TRNG_STATUS.DATA_WR_DONE` → request drops. ROM/FW time out after 250,000 polls of DONE if the SoC is silent.

**Entropy source:** Software **xorshift32**, seed `0x1234ABCD`. Simulation uses `$urandom`. There is no FPGA TRNG, no ring-oscillator, no LFSR in RTL.

**Security:**

- Not a NIST SP 800-90B entropy source.
- Integration Spec: *“It is a requirement for FIPS compliance that this TRNG HW API is always handled by SoC hardware gasket logic (and not some SoC ROM or firmware code).”* This design violates that on purpose for bring-up.
- Spec also strongly prefers enabling `CALIPTRA_INTERNAL_TRNG` and wiring a physical PTRNG to `itrng_data` / `itrng_valid` (~50 kHz valid rate).
- TRNG PAUSER is unlocked. API text says lock=0 means any APB agent can write TRNG DATA (and the passing sim matches that). A later “programming rules” row says unprogrammed lock means *no* agent is accepted — that row does not match this v1.1 RTL behavior, but locking PAUSER to a gasket ID is still the recommended threat-model posture and is **not** done here.

**Verdict:** Wired correctly for an ETRNG *bring-up* hook, and enough for the ROM/FW boot that passed in Verilator. **Test-only. Do not treat boot measurements, IDevID, or any Caliptra-derived key as trustworthy on this FPGA image.**

---

## 7. Fuse section (review)

**Mechanism:** A **hardware fuse-controller soft IP** (`soc_fuse_ctrl.sv`), not Nios poking `FUSE_*` registers. This matches the Integration Spec rule “SoC shall write fuse registers and fuse done via immutable logic or ROM code” *in structure* (an FSM in RTL). It is still only an FPGA stand-in for OEM OTP + sequencer: the image is a `$readmemh` of `fw/fuse_image.hex` into on-chip storage, regenerated by `scripts/gen_fuse_image.py`. Anyone who can rebuild the bitstream can change UDS / field entropy / PK hashes.

**Sequencing:** Nios waits for `ready_for_fuses`, optionally programs PAUSER/WDT, then pulses START. The IP errors if `ready_for_fuses` is low. It writes 83 words at `0x3_0200 + 4*i`, then `CPTRA_FUSE_WR_DONE=1` at `0x3_00B0`. Fuses are one-time per power-good (warm reset still requires a write to the done register in `BOOT_FUSE`; this host always does a full cold-style push after pwrgood).

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
| `FUSE_SOC_STEPPING_ID` | `0x00000001` (A0 test) |

Re-run `scripts/gen_fuse_image.py` if the FW bundle is re-signed. UDS/FE are never exposed through fuse-ctrl MMIO; Nios must not (and the boot ROM does not need to) read them back.

**Lifecycle straps vs fuses:** Both are Production (`2'b11` / fuse `0x3`) with debug locked. This is a hardwired mimic so ROM/FW take the production path (including WDT). It is not a real manufacturing/production lifecycle controller.

---

## 8. Review findings

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
| M4 | **`quartus_a5e_nios/README.md` is stale** in “Firmware” and “Not done”: it still describes a one-word TEST UDS poke, `ROM_INIT_FILE=""`, and FIRMWARE_LOAD as future work. RTL/FW already perform the full 83-word fuse push, load rom-1.1.1, and `FIRMWARE_LOAD` the bundle. The architecture/address-map sections of that README are mostly right; this note supersedes the stale boot-flow text. |
| M5 | **Caliptra notification/error outputs are not IRQs** — only `jtag_uart` is in the PD interrupt map. Fatal/WDT/mailbox events are noticed only when firmware polls `status_pio`. |
| M6 | **No hardware mutex** beyond the `fuse_busy` APB mux. Current FW is careful; a buggy host could overlap Nios APB with the fuse FSM. |
| M7 | **`cptra_pwrgood` / `cptra_rst_b` include unsynchronized `reset_n`.** Spec wants asynchronous assertion and synchronous deassertion. PIO updates are synchronous; the board-reset term is not passed through a deassert synchronizer dedicated to those two Caliptra pins (`reset_n` is also an SDC false path). |
| M8 | **Mailbox / ICCM / DCCM are not explicitly zeroed** (and no SRAM repair) before `cptra_rst_b` deassert, which the spec requires on a power-good cycle. |
| M9 | **Clock / pins:** 50 MHz board clock, no PLL, no on-die oscillator, almost all I/O still **virtual pins** (only `clk` and `reset_n` are real in the QSF). Not board-proven. |

### Low

| ID | Finding |
|---|---|
| L1 | Caliptra QSPI and UART are tied off / compiled out. Expected; firmware comes from `soc_fw_store`, not flash. |
| L2 | Caliptra JTAG TAP is tied off (`trst_n=0`). Nios JTAG UART/debug is separate and is connected. |
| L3 | `generic_output_wires[63:24]` never reach Nios. |
| L4 | Window hole `0x1C000–0x1EFFF` aliases FW-store word 0. |
| L5 | ICache SRAMs are still in the VeeR export (area leftover; not a functional bug for this 1.x config). |
| L6 | `PSLVERR` is not propagated as an Avalon/AXI response to the Nios CPU (`USE_RESPONSE` off). Fuse IP *does* latch `PSLVERR` into its ERR bit. |
| L7 | Full Platform Designer Nios V + interconnect is not simulated; Verilator uses a behavioral host. |

### Doc vs RTL mismatches (summary)

- `quartus_a5e_nios/README.md` Firmware / Not-done sections: **stale** (see M4).
- Top-level `README.md`, the architecture section of the Nios README, and `sim/BOOT_NIOS_TOP_PROD.md`: **aligned** with RTL on fuse IP, ETRNG, ROM hex, and `0xCA11F00D`.
- Official Integration Spec vs this FPGA glue: ETRNG-by-firmware, study key, soft OTP, generic_input ← magic_pio, unlocked TRNG/fuse PAUSER, no iTRNG, no Caliptra TAP, virtual pins — all called out above.

---

## 9. Open items

- Finish Quartus **route + timing** on a ≥32 GB host (placement already succeeded; routing OOM’d at ~16 GB). Programming-file / `.sof` still depends on a valid **SW-AGILEX-5E** license that includes programming-file generation (Error 23714 was seen on a related project license).
- Assign a real **board pinout**, I/O standards, and a PLL if the kit clock is not 50 MHz.
- Replace ETRNG xorshift with a **hardware entropy source** (preferably `CALIPTRA_INTERNAL_TRNG` + `itrng_*`, or an immutable ETRNG gasket) and lock TRNG PAUSER.
- Replace `soc_fuse_ctrl`’s hex image with a real (or better FPGA-emulated) **OTP**, provision unique UDS/FE, lock fuse PAUSER, and stop treating STUDY hashes/keys as secrets.
- **Fix `generic_input_wires`** (tie reserved bits to 0; do not connect `magic_pio`).
- Optionally route `cptra_error_fatal` / `mailbox_data_avail` / `etrng_req` as **Nios IRQs**, and synchronize `reset_n` deassert into the Caliptra pwrgood/reset pair.
- Zero (and, on ASIC, repair) SRAMs on power-good before releasing `cptra_rst_b`.
- Simulate the **real PD Nios V** system (Questa + Quartus libs), and bring the design up on the A5E kit once a SOF exists.
- Manufacturing items not in scope here: IDevID certificate provisioning, field-entropy API, FIPS zeroization API, scandump exclusion for the obfuscation key.

---

## 10. Source index

| Path | Role |
|---|---|
| `rtl/caliptra_passive_top.sv` | Caliptra 1.x wrapper, memories, QSPI tie-offs |
| `quartus_a5e_nios/rtl/nios_caliptra_top.sv` | Top: PD system, window decode, APB mux, straps, TRNG tie-offs |
| `quartus_a5e_nios/rtl/avmm_to_apb.sv` | Avalon → APB3, `PAUSER=1` |
| `quartus_a5e_nios/rtl/soc_fuse_ctrl.sv` | Fuse sequencer soft IP |
| `quartus_a5e_nios/rtl/soc_fw_store.sv` | FW-bundle M20K |
| `quartus_a5e_nios/qsys/nios_caliptra_sys.tcl` | Regeneratable PD system |
| `quartus_a5e_nios/sw/app/main.c` | Nios boot ROM (pwr/reset, PAUSER, fuse START, ETRNG, FW load) |
| `quartus_a5e_nios/nios_caliptra.sdc` | 50 MHz `clk`, false path on `reset_n` |
| `scripts/gen_fuse_image.py` / `fw/fuse_image.hex` | STUDY OTP image |
| `fw/caliptra-rom.hex`, `fw/caliptra-fw-bundle.hex` | ROM 1.1.1 and signed 1.x bundle |
| `sim/tb_nios_top_fw.sv`, `sim/run_nios_top_fw.sh` | Verilator production-mimic TB |

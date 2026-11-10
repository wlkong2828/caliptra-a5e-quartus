# Nios V/m host + Caliptra 1.x on Agilex 5 E (A5EC065BB32AE6S)

The complete, RTL-reviewed connection map, fuse/TRNG review, boot sequence, and spec checklist are in [`docs/NIOS_CALIPTRA_INTEGRATION.md`](../docs/NIOS_CALIPTRA_INTEGRATION.md) (revision 3).

Compile study: an Intel **Nios V/m** CPU acts as the SoC "mailbox host" for **Caliptra 1.x**
(chipsalliance/caliptra-rtl v1.1 @ 5f85fb4, passive mode) over Caliptra's **APB** subordinate.
Quartus Prime Pro 25.3 (Docker `alterafpga/quartuspro-v25.3:agilex5`). **Pinout TBD** – all I/O
except `clk`/`reset_n` are virtual pins; nothing here is board-proven yet.

## Architecture
```
 clk ─┬─────────────────────────────────────────────────────────────┐
      │  nios_caliptra_sys (Platform Designer)                      │
      │  Nios V/m ─AXI4-lite─► interconnect ─┬─ ram (64 KiB OCM, reset vector 0x0)
      │                                      ├─ jtag_uart (stdout)
      │                                      ├─ ctrl_pio  (out) ──► cptra_pwrgood / cptra_rst_b / BootFSM_BrkPoint
      │                                      ├─ status_pio(in)  ◄── ready_for_* / mailbox_* / errors / etrng_req / gen_out[23:0]
      │                                      ├─ magic_pio (out) ──► led[7:0] only (generic_input_wires tied 0)
      │                                      └─ caliptra_win (mm_bridge, 256 KiB) ─► exported Avalon master
      │                                                              │
      │        2FF reset sync (async assert / sync deassert) on cptra_pwrgood, cptra_rst_b
      │        rtl/avmm_to_apb.sv (PAUSER = nios_pauser, default 0x1) ◄──┘
      │                    │ APB3 (PADDR[17:0] used)
      └──► caliptra_passive_top (../rtl) ─ Caliptra 1.x + M20K mailbox/ROM/ICCM/DCCM
```
Straps (`rtl/nios_caliptra_top.sv`): **production-flow mimic** — lifecycle = `2'b11` DEVICE_PRODUCTION,
`debug_locked = 1`, fixed STUDY `cptra_obf_key` (not a real product secret), JTAG/scan/itrng tied off
(itrng_valid=0 → ETRNG mode).

Fuses (`../fw/fuse_image.hex`, from `../scripts/gen_fuse_image.py`, pushed by `soc_fuse_ctrl`):
FUSE_LIFE_CYCLE = 0x3 (Production); KEY_MANIFEST_PK_HASH / OWNER_PK_HASH = SHA-384 of the
vendor/owner public-key descriptors in `../fw/caliptra-fw-bundle.bin` (12 BE words, as caliptra-sw
tests); PK_HASH_MASK = 0; FMC/RT SVN fuses = 0 (bundle SVN 0); non-zero STUDY UDS seed + field
entropy. These are study values chosen so ROM/FW verification passes production lifecycle checks —
NOT real production secrets. Re-run the script if the FW bundle is re-signed.

Simulation: Verilator covers this FPGA glue RTL (`nios_caliptra_top` + fuse ctrl + FW store +
Caliptra) with a behavioral Nios host (`../sim/run_nios_top_fw.sh`, see `../sim/BOOT_NIOS_TOP_PROD.md`).
Simulating the full Platform Designer Nios V IP system needs Intel Questa/ModelSim with the Quartus
simulation libraries.

## Address map (Nios data master; from generated `sw/bsp/system.h`)
| Base | Span | Block |
|---|---|---|
| 0x0000_0000 | 64 KiB | `ram` on-chip memory (code+data, init from `onchip_mem.hex`) |
| 0x0004_0000 | 256 KiB | `caliptra_win` → Caliptra APB (offset = APB address) |
| 0x0008_0000 | 8 | `jtag_uart` |
| 0x0008_0010 | 16 | `ctrl_pio` bit0 pwrgood, bit1 cptra_rst_b, bit2 BootFSM_BrkPoint (reset 0 = held in reset) |
| 0x0008_0020 | 16 | `status_pio` bit0 ready_for_fuses, 1 ready_for_fw_push, 2 ready_for_runtime, 3 mailbox_data_avail, 4 mailbox_flow_done, 5 error_fatal, 6 error_non_fatal, 7 etrng_req, 31:8 generic_output_wires[23:0] |
| 0x0008_0030 | 16 | `magic_pio` → led[7:0] |
| 0x0008_0040 | 64 | Nios V timer_sw_agent (mtime) |
| 0x0009_0000 | 64 KiB | Nios V debug module |

Caliptra registers through the window (base 0x0004_0000 + offset):
`MBOX_CSR` 0x2_0000 (MBOX_LOCK 0x2_0000), `CPTRA_FLOW_STATUS` 0x3_003C (bit30 ready_for_fuses),
`CPTRA_HW_REV_ID` 0x3_00D4 (`{SOC_STEPPING_ID, 0x0011}`; `0x0000_0011` before fuses, `0x0001_0011` after stepping=1), fuses 0x3_0200…

## Firmware (`sw/app/main.c`)
1. magic=1 → pwrgood → release `cptra_rst_b` (through the 2FF synchronizers)
2. poll `status_pio.ready_for_fuses`
3. magic=2; read `CPTRA_HW_REV_ID`
4. magic=3: program+lock fuse, TRNG, and mailbox PAUSER to 1; write `CPTRA_TIMER_CONFIG=20000`; write `CPTRA_WDT_CFG=100_000_000`
5. magic=4: `soc_fuse_ctrl` CTRL.START (83 `FUSE_*` words + `FUSE_WR_DONE`). After a **warm reset** use CTRL.START_DONE (bit 2); ROM resumes existing FW to `ready_for_runtime` (no second `FIRMWARE_LOAD`) — see `caliptra_warm_reset()`.
6. poll `ready_for_fw_push` while servicing ETRNG (xorshift, TEST-ONLY)
7. mailbox `FIRMWARE_LOAD` of `soc_fw_store` (109000 bytes); magic=6/7
8. poll `ready_for_runtime`; magic=`0xCA11F00D` (led=0x0D)
9. idle: keep servicing TRNG; poll errors — non-fatal is RW1C-cleared, fatal does a limited pwrgood-cycle recovery

Same sequence as `../sim/tb_nios_top_fw.sv`. After editing main.c, rerun `sw/build_app.sh` so `onchip_mem.hex` matches before synthesis. If Quartus `elf2hex` is unavailable, the script falls back to `scripts/elf2hex_intel.py`.

## Rebuild
All Quartus/PD commands run inside Docker via `./dock.sh '<cmd>'` (needs `--net=host` + license
`LIC_HOST=/path/SW-AGILEX-5E.dat`; the fixed license is tied to the build host's NIC MAC).
```bash
# 1. Platform Designer system (regeneratable source = qsys/nios_caliptra_sys.tcl)
./dock.sh 'cd qsys && rm -rf ip nios_caliptra_sys.qsys && qsys-script --script=nios_caliptra_sys.tcl --quartus-project=none'
# 2. BSP + app CMake (already checked in under sw/bsp, sw/app)
./dock.sh 'niosv-bsp -c -s=qsys/nios_caliptra_sys.qsys -t=hal --cmd="set_setting hal.stdout jtag_uart; set_setting hal.stdin jtag_uart; set_setting hal.stderr jtag_uart" sw/bsp/settings.bsp'
./dock.sh 'niosv-app --bsp-dir=sw/bsp --app-dir=sw/app --srcs=sw/app/main.c --elf-name=caliptra_host.elf'
# 3. Compile app (any rv32 GCC; tested xPack riscv-none-elf-gcc 14.2 + cmake + ninja), makes onchip_mem.hex
RISCV_BIN=/path/to/xpack-riscv-none-elf-gcc/bin sw/build_app.sh
# 4. Synthesis (IP generate + quartus_syn).  'fit' also routes – needs >=32 GB RAM.
./run_nios_a5e_docker.sh syn
```
Quartus files: `nios_caliptra_a5e.qpf/.qsf` (paths relative: `../caliptra-rtl`, `../rtl`, `../quartus/syn_src`),
`nios_caliptra.sdc` (50 MHz clk). Order: build the app first so `onchip_mem.hex` exists before synthesis.

## Not done / blockers for "talk on hardware"
- No board pinout / IO standards (clk, reset_n, led virtual-pin study only); no PLL; no Intel Reset Release IP (`ninit_done`) — steps in the integration note §12 (M11).
- Full fit not run here (16 GB host OOMs on Caliptra place&route; need ≥32 GB).
- SRAM pwrgood zeroization walk is not implemented (FPGA init-to-0 only; M8).
- Error pins are polled with recovery; they are not yet Nios IRQs (Qsys steps in §12).
- ETRNG xorshift, study UDS/FE/obf key, and the fuse hex image are TEST-ONLY.
- Full Platform Designer Nios V + interconnect is not simulated; Verilator uses a behavioral host (`../sim/run_nios_top_fw.sh`, plusargs `+test=prod|sync|pauser|warm|fatal|all`).

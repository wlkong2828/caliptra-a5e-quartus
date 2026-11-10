# Nios V/m host + Caliptra 1.x on Agilex 5 E (A5EC065BB32AE6S)

The complete, RTL-reviewed connection map, fuse/TRNG review, and boot sequence are in [`docs/NIOS_CALIPTRA_INTEGRATION.md`](../docs/NIOS_CALIPTRA_INTEGRATION.md). That note supersedes the **Firmware** and **Not done** sections below, which are stale relative to the `soc_fuse_ctrl` + rom-1.1.1 + `FIRMWARE_LOAD` flow already in this tree.

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
      │                                      ├─ magic_pio (out) ──► led[7:0] + Caliptra generic_input_wires[31:0]
      │                                      └─ caliptra_win (mm_bridge, 256 KiB) ─► exported Avalon master
      │                                                              │
      │        rtl/avmm_to_apb.sv (PAUSER = 0x0000_0001 constant) ◄──┘
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
`CPTRA_HW_REV_ID` 0x3_00D4 (**expect 0x0000_0011** = CPTRA_GENERATION 1.1), fuses 0x3_0200…

## Firmware (`sw/app/main.c`)
1. magic=1 → pwrgood → release `cptra_rst_b`
2. poll `status_pio.ready_for_fuses` (timeout → magic 0xDEAD0001)
3. magic=2; read `CPTRA_HW_REV_ID` and `CPTRA_FLOW_STATUS` over APB, print on JTAG UART
4. magic=3: program + lock `CPTRA_MBOX_VALID_PAUSER[0]`=1 (our bridge PAUSER; default 0xFFFFFFFF would PSLVERR the mailbox)
5. magic=4: TEST fuse load (one UDS word) + `CPTRA_FUSE_WR_DONE`=1 (fail 0xDEAD0003)
6. acquire `MBOX_LOCK`, check `MBOX_USER`=1 (fail 0xDEAD0004); fatal/non-fatal error check (fail 0xDEAD0005)
7. magic=**0xCA11F00D** on success (led=0x0D). Same sequence as `../sim/tb_boot_apb.sv` (passes in Verilator).
Mailbox `FIRMWARE_LOAD` needs the caliptra-sw 1.x ROM in the build (next step).
Note: after editing main.c, rerun `sw/build_app.sh` (with elf2hex) so `onchip_mem.hex` matches before synthesis.

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
- No board pinout / IO standards (clk, reset_n, led virtual-pin study only); no PLL.
- Full fit not run here (16 GB host OOMs on Caliptra place&route; need ≥32 GB).
- Caliptra ROM image not loaded (`ROM_INIT_FILE=""`): HW_REV_ID / FLOW_STATUS / fuses work from
  the BootFSM without ROM, but going past `ready_for_fuses` needs the caliptra-sw 1.x ROM hex + fuse/FW flow.
- No simulation testbench of the PD system yet (avmm_to_apb + Caliptra APB is simple; recommended next).

# caliptra2x/ — Caliptra 2.x passive + Nios V study sources

These are the sources for the Caliptra 2.x (caliptra-rtl v2.1.2) study, copied from the local 2.x design tree so that the guides in [`docs/caliptra-2x/`](../docs/caliptra-2x/) are self-contained.

| Path | Contents |
|---|---|
| `rtl_2x/` | `nios_caliptra2x_top.sv`, `caliptra_passive_top.sv` (2.x core-only wrapper), `avmm_to_axi.sv`, `soc_fuse_ctrl2x.sv`, `soc_fw_store.sv`, `reset_sync.sv`, `caliptra_veer_sram_export.sv` |
| `sim_2x/` | Verilator TB `tb_nios2x_top_fw.sv`, file list `boot2x.f`, `run_nios2x_top_fw.sh`, adams-bridge Verilator patch, PASS record `BOOT_NIOS2X.md` + full run log + build log. Attestation/DPE flow (`+test=attest`): `attest/` (driver, analyzer, emulator backend, TEST CA certs), `attest_ref/` (reference RTL + emulator results), `ATTEST_2X.md`. To run it yourself: [`docs/caliptra-2x/SIMULATION_2X.md` §8.2](../docs/caliptra-2x/SIMULATION_2X.md#82-quick-start-run-it-yourself) (what the Nios model covers: [§8.1](../docs/caliptra-2x/SIMULATION_2X.md#81-what-this-simulation-covers-nios-model)) |
| `sim/rst_release_stub.sv` | Reset Release IP stand-in used by `boot2x.f` |
| `fw_2x/` | 2.x ROM (`rom-2.1.3-1`, with log) and FW bundle (`fw-2.1.4`), `.bin` + `$readmemh` hex, `SHA256SUMS`, `build_rom.sh`, `fuse_image_2x.hex` |
| `scripts/gen_fuse_image_2x.py` | Builds `fw_2x/fuse_image_2x.hex` from the bundle |
| `quartus_a5e_2x/` | Quartus Pro 25.3 synthesis-only fit-gate project (core only) and committed report extracts |
| `quartus_a5e_2x_nios/` | **Full Nios V + Caliptra 2.x Quartus project** (top `rtl_2x/nios_caliptra2x_top.sv`): Platform Designer system `nios_caliptra2x_sys` (Tcl + generated output), `ip/rst_release.ip`, QSF/SDC, Nios firmware `sw/` (2.x port of the 1.x `main.c`, BSP, `build_app.sh`), `onchip_mem.hex`, `run_nios2x_a5e_docker.sh`. Synthesis 286,415 / 222,400 ALMs (129 %, does not fit) |
| `docs/` | Fit result and 1.x → 2.x plan (also copied into `docs/caliptra-2x/`) |

Notes:
- **The FW bundle is signed with caliptra-sw's public fake keys. It is for simulation only.** See `docs/caliptra-2x/FIRMWARE_AND_KEYS_2X.md`. No private keys are in this repo.
- caliptra-rtl v2.1.2 (`49370266`, with adams-bridge `b77e3d8`) is the `external/caliptra-rtl-2x` submodule (run `scripts/fetch_deps.sh`). caliptra-sw `dd1e79d` is not vendored. `sim_2x/boot2x.f` and the QSF use paths relative to their own directory.
- `quartus_a5e_2x/caliptra2x_a5e.qsf` is committed with repo-relative paths. `gen_qsf.py` regenerates it only from the 2.x tree's Verilator list (`FLIST=…/caliptra_passive_top.f REGEN_QSF=1 ./run_syn_docker.sh`). That list is not copied here.
- The 2.x design **does not fit** the A5EC065: 279,685 / 222,400 ALMs (126 %).
- The 2.x design **with the Nios system** (`quartus_a5e_2x_nios/`) estimates 286,415 / 222,400 ALMs (129 %).

## Nios V system: Caliptra 1.1 vs 2.x

`quartus_a5e_2x_nios/qsys/nios_caliptra2x_sys.tcl` is the 1.1 `quartus_a5e_nios/qsys/nios_caliptra_sys.tcl` with only the Caliptra window changed. The generated `.ip` files for clk, RAM, JTAG UART and the three PIOs are identical to 1.1, the CPU differs only in its address map, and the BSP settings are identical. Full table: `docs/caliptra-2x/NIOS_CALIPTRA_2X_INTEGRATION.md` §18.

| Item | Caliptra 1.1 (`quartus_a5e_nios/`) | Caliptra 2.x (`caliptra2x/quartus_a5e_2x_nios/`) | Same? |
|---|---|---|---|
| CPU | Nios V/m, reset `ram.s1`+0, debug on | Nios V/m, reset `ram.s1`+0, debug on | yes |
| RAM | 64 KiB on-chip @ `0x0000_0000`, `onchip_mem.hex` | same | yes |
| JTAG UART | @ `0x0008_0000`, IRQ 0 | same | yes |
| ctrl / status / magic PIO | 32-bit @ `0x0008_0010` / `0x0008_0020` / `0x0008_0030` | same | yes |
| Timer / debug module | `0x0008_0040` / `0x0009_0000` | same | yes |
| Clock / reset | 50 MHz `clock_source`; Reset Release IP + 2FF syncs | same (same `rst_release.ip`) | yes |
| SDC, device, pins | A5EC065BB32AE6S, virtual I/O except `clk`, `reset_n` | same | yes |
| BSP / boot flow / LED codes | HAL; cold boot, fuses, TRNG, FW load, runtime; 1…7, `0xCA11F00D` | same | yes |
| Caliptra window | 256 KiB @ `0x0004_0000`, `caliptra_apb` → `avmm_to_apb` → APB | 1 MiB @ `0x0010_0000`, `caliptra_axi` → `avmm_to_axi` → AXI4 | no (2.x bus) |
| Window map | fw `0x00000`, fuse `0x1F000`, Caliptra `0x20000` | fw `0x00000`, fuse `0x7F000`, Caliptra `0x80000` | no |
| Requester IDs | PAUSER 1 (Nios + fuse ctrl) | AxUSER 1 Nios, 2 fuse ctrl | no |
| FW bundle | 109,000 B | 253,440 B | no |
| `status_pio[1]` | `ready_for_fw_push` | `ready_for_mb_processing` | renamed |


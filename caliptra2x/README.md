# caliptra2x/ — Caliptra 2.x passive + Nios V study sources

These are the sources for the Caliptra 2.x (caliptra-rtl v2.1.2) study, copied from the local 2.x design tree so that the guides in [`docs/caliptra-2x/`](../docs/caliptra-2x/) are self-contained.

| Path | Contents |
|---|---|
| `rtl_2x/` | `nios_caliptra2x_top.sv`, `caliptra_passive_top.sv` (2.x core-only wrapper), `avmm_to_axi.sv`, `soc_fuse_ctrl2x.sv`, `soc_fw_store.sv`, `reset_sync.sv`, `caliptra_veer_sram_export.sv` |
| `sim_2x/` | Verilator TB `tb_nios2x_top_fw.sv`, file list `boot2x.f`, `run_nios2x_top_fw.sh`, adams-bridge Verilator patch, PASS record `BOOT_NIOS2X.md` + full run log + build log |
| `sim/rst_release_stub.sv` | Reset Release IP stand-in used by `boot2x.f` |
| `fw_2x/` | 2.x ROM (`rom-2.1.3-1`, with log) and FW bundle (`fw-2.1.4`), `.bin` + `$readmemh` hex, `SHA256SUMS`, `build_rom.sh`, `fuse_image_2x.hex` |
| `scripts/gen_fuse_image_2x.py` | Builds `fw_2x/fuse_image_2x.hex` from the bundle |
| `quartus_a5e_2x/` | Quartus Pro 25.3 synthesis-only fit-gate project (core only) and committed report extracts |
| `docs/` | Fit result and 1.x → 2.x plan (also copied into `docs/caliptra-2x/`) |

Notes:
- **The FW bundle is signed with caliptra-sw's public fake keys. It is for simulation only.** See `docs/caliptra-2x/FIRMWARE_AND_KEYS_2X.md`. No private keys are in this repo.
- Not vendored: caliptra-rtl v2.1.2 (`49370266`, clone with `--recursive`) and caliptra-sw `dd1e79d`. `sim_2x/boot2x.f` expects caliptra-rtl at `/workspace/caliptra-rtl`; its repo-local paths are relative.
- `quartus_a5e_2x/caliptra2x_a5e.qsf`, `gen_qsf.py` and `run_syn_docker.sh` still contain absolute paths from the build box (`/workspace/...`) and reference `ref/agilex7-2x-phaseA/` from the 2.x tree, which is not copied here. Regenerate the QSF before using it elsewhere.
- The 2.x design **does not fit** the A5EC065: 279,685 / 222,400 ALMs (126 %).

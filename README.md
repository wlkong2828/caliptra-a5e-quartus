# Caliptra 1.x on Agilex 5 E (Quartus project)

Passive Caliptra 1.x (v1.1) Quartus Prime Pro 25.3 project targeting **A5EC065BB32AE6S**.

**Caliptra 2.x study (passive / core-only, Nios V host):** [`docs/caliptra-2x/`](docs/caliptra-2x/) has three guides. [Integration](docs/caliptra-2x/NIOS_CALIPTRA_2X_INTEGRATION.md) covers signals, AxUSER IDs, the memory map, the fuse map, TRNG, the boot sequence, the spec checklist and the A5E fit result (126 %, does not fit). [Simulation](docs/caliptra-2x/SIMULATION_2X.md) covers the Verilator flow and the PASS run to `ready_for_runtime`. [Firmware & keys](docs/caliptra-2x/FIRMWARE_AND_KEYS_2X.md) covers the ROM and bundle build, fuse image generation, and production HSM key preparation. A combined PDF is at [`docs/caliptra-2x/NIOS_CALIPTRA_2X_GUIDE.pdf`](docs/caliptra-2x/NIOS_CALIPTRA_2X_GUIDE.pdf). The 2.x sources are in [`caliptra2x/`](caliptra2x/).

**Nios ↔ Caliptra integration (signal map, TRNG, fuses, reset, watchdog, spec checklist):** [`docs/NIOS_CALIPTRA_INTEGRATION.md`](docs/NIOS_CALIPTRA_INTEGRATION.md) (revision 3; PDF: [`docs/NIOS_CALIPTRA_INTEGRATION.pdf`](docs/NIOS_CALIPTRA_INTEGRATION.pdf)).

## Getting the sources and compiling

The upstream Caliptra RTL is **not copied into this repo**. It is pulled in as pinned git submodules under `external/`:

| Path | Upstream | Version | Commit | Used by |
|---|---|---|---|---|
| `external/caliptra-rtl-1x` | chipsalliance/caliptra-rtl | v1.1 | `5f85fb4` | `quartus_a5e/`, `quartus_a5e_nios/`, `sim/` |
| `external/caliptra-rtl-2x` | chipsalliance/caliptra-rtl | v2.1.2 | `4937026` | `caliptra2x/quartus_a5e_2x/`, `caliptra2x/sim_2x/` |
| `external/caliptra-rtl-2x/submodules/adams-bridge` | chipsalliance/adams-bridge | v2.0.3 | `b77e3d8` | 2.x (ML-DSA) |

The upstream trees are used unmodified. All FPGA changes are in this repo: `rtl/`, `quartus/syn_src/`, `quartus_a5e_nios/rtl/`, `caliptra2x/rtl_2x/`, `caliptra2x/quartus_a5e_2x/syn_src/`. Every path in the `.qsf`, `.f` and run scripts is relative to the file's own directory, so the checkout can live anywhere. If you see `caliptra_passive_top` or `caliptra_top` undefined, the submodules have not been fetched.

**1. Get the sources** (Linux or macOS, needs git; about 1 GB):
```bash
# one script: clones (or pulls + updates submodules in an existing clone) and checks the pins
curl -fsSLO https://raw.githubusercontent.com/pwilliam282/caliptra-a5e-quartus/main/scripts/get_caliptra_a5e.sh
bash get_caliptra_a5e.sh ~/work/caliptra-a5e-quartus
# or by hand:
git clone --recursive https://github.com/pwilliam282/caliptra-a5e-quartus.git
cd caliptra-a5e-quartus
scripts/fetch_deps.sh          # inits/updates the submodules and checks the pinned commits ("deps OK")
```
If you cloned without `--recursive`, or downloaded a ZIP, run `scripts/fetch_deps.sh` anyway. It runs `git submodule update --init --recursive`, or clones the pinned commits when there is no `.git`.

**2. Tools.** Quartus Prime **Pro 25.3.0** (Build 109) with Agilex 5 device support, and the no-cost **SW-AGILEX-5E** license. That license is node-locked to the NIC MAC of the machine that runs Quartus. Quartus Pro runs only on Linux/Windows x86-64, so on a Mac (including Apple silicon) use a Linux x86-64 PC, VM or server. The official Docker image `alterafpga/quartuspro-v25.3:agilex5` is linux/amd64 only and needs `--net=host` for the license. It is not usable under emulation on Apple-silicon Docker Desktop.

**3. Open or compile a project** (Quartus GUI: *File → Open Project*, then pick the `.qpf`):

| Project | Top | Directory / `.qpf` |
|---|---|---|
| Nios V + Caliptra 1.x (main design) | `nios_caliptra_top` | `quartus_a5e_nios/nios_caliptra_a5e.qpf` |
| Caliptra 1.x core only (size study) | `caliptra_passive_top` | `quartus_a5e/caliptra_a5e.qpf` |
| Caliptra 2.x core only (size study, does not fit) | `caliptra_passive_top` | `caliptra2x/quartus_a5e_2x/caliptra2x_a5e.qpf` |

The Nios project's Platform Designer output (`qsys/nios_caliptra_sys/`, `qsys/ip/…`) is committed. The Reset Release IP (`ip/rst_release.ip`) is generated locally (`ip/rst_release/` is gitignored), so **run `quartus_ipgenerate` once before synthesis**. In the GUI the equivalent is *Tools → Generate IP*, or let the compile prompt you.

Native Quartus on Linux:
```bash
cd quartus_a5e_nios
quartus_ipgenerate nios_caliptra_a5e
quartus_syn nios_caliptra_a5e                     # full synthesis (~7 min, ~4 GB)
# quick check only: quartus_syn --analysis_and_elaboration nios_caliptra_a5e
cd ../quartus_a5e              && quartus_syn caliptra_a5e
cd ../caliptra2x/quartus_a5e_2x && quartus_syn caliptra2x_a5e   # ~22 min, ~7 GB
```
With Docker (`scripts/quartus_docker.sh <dir> '<cmd>'` mounts the repo and your license):
```bash
export LIC_HOST=$HOME/licenses/SW-AGILEX-5E.dat
scripts/quartus_docker.sh quartus_a5e_nios 'quartus_ipgenerate nios_caliptra_a5e && quartus_syn nios_caliptra_a5e'
scripts/quartus_docker.sh quartus_a5e 'quartus_syn caliptra_a5e'
scripts/quartus_docker.sh caliptra2x/quartus_a5e_2x 'quartus_syn caliptra2x_a5e'
```
Full details (license, GUI, outputs, measured numbers, known Docker issues such as the intermittent start-up crash and a stalled `quartus_syn`, which you fix by killing the container and rerunning): §15–§16 of [`docs/NIOS_CALIPTRA_INTEGRATION.md`](docs/NIOS_CALIPTRA_INTEGRATION.md) and §16–§17 of the [2.x guide](docs/caliptra-2x/NIOS_CALIPTRA_2X_INTEGRATION.md).

`quartus_a5e_nios/run_nios_a5e_docker.sh` regenerates the whole Platform Designer system from `qsys/nios_caliptra_sys.tcl`, then runs ipgenerate and synthesis. The full fit needs at least 32 GB of RAM.

## Contents
- `quartus_a5e/` — Caliptra-only A5E synth study (QSF/QPF, reports)
- `quartus_a5e_nios/` — **Nios V/m host + Avalon→APB + Caliptra 1.x** (synth ~62% ALMs)
- `STUDY.md` — C10 GX + A5E fit notes

- `quartus_a5e/` — QSF/QPF, SDC, `run_a5e_docker.sh`, `flow.log`, synthesis reports under `output_files/`
- `STUDY.md` — C10 GX + A5E fit study notes

## Synth result (`quartus_a5e/`, Caliptra-only study)
- Logic: ~141,256 / 222,400 ALMs (**64%**)
- Placement succeeded; routing OOM on 16 GB VM — needs ≥32 GB for full fit
- Nios project (`quartus_a5e_nios/`, with Reset Release IP): **138,715 / 222,400 ALMs (62%)**, synthesis only

## License
Requires Altera **SW-AGILEX-5E** (no-cost) for your host NIC. Do **not** commit license `.dat` files. Request one from Altera SSLC for your MAC.

## Build
See [Getting the sources and compiling](#getting-the-sources-and-compiling). Docker wrapper: `LIC_HOST=/path/to/SW-AGILEX-5E.dat quartus_a5e/run_a5e_docker.sh [syn|fit]`.

## Nios V host (new)

See [`quartus_a5e_nios/`](quartus_a5e_nios/) — Nios V/m + Avalon→APB bridge + Caliptra 1.x.
Synthesis succeeded on A5EC065BB32AE6S: **~138.7K / 222.4K ALMs (62%)**.

## rtl/ (passive wrapper)

`rtl/caliptra_passive_top.sv` is the thin Caliptra 1.x passive-mode wrapper referenced by the Quartus QSF as `../rtl/caliptra_passive_top.sv` (sibling of `quartus_a5e_nios/`). The upstream caliptra-rtl v1.1 tree is the `external/caliptra-rtl-1x` submodule (run `scripts/fetch_deps.sh`).

## quartus/syn_src/ (FPGA synthesis overrides)
Referenced by the QSF as `../quartus/syn_src/*.sv`:
- `caliptra_top_tb_pkg.sv` – tb_pkg variant without SystemVerilog classes (guarded for `SYNTHESIS`), fixes "caliptra_top_tb_pkg is not declared".
- `caliptra_veer_sram_export.sv` – VeeR SRAM export wrapper.
- `caliptra_sram.sv` – M20K-friendly SRAM model.
Everything else comes from the unmodified upstream tree in `external/caliptra-rtl-1x` (chipsalliance v1.1).

## Caliptra bootROM (`fw/`)

`fw/caliptra-rom.hex` is the Caliptra **1.x** bootROM (caliptra-sw rom-1.1.1, 6144 x 64-bit words, same image used in sim to reach `ready_for_runtime`); `fw/caliptra-rom.bin` + `fw/SHA256SUMS` for verification.
`quartus_a5e_nios/rtl/nios_caliptra_top.sv` instantiates `caliptra_passive_top #(.ROM_INIT_FILE("../fw/caliptra-rom.hex"))`, which `$readmemh`s it into the Caliptra ROM M20K at synthesis (path is relative to `quartus_a5e_nios/`). The QSF also lists it as `HEX_FILE` for dependency tracking.
**Do not use a Caliptra 2.x ROM** — it is incompatible with this 1.x RTL.

## Fuse controller IP + firmware download (Nios)

The Nios project runs the full Caliptra 1.x passive boot like a production SoC:
power/reset (2FF-synchronized `cptra_pwrgood` / `cptra_rst_b`) → `ready_for_fuses` → program/lock PAUSER, `TIMER_CONFIG=20000`, `WDT_CFG` → **`soc_fuse_ctrl`** writes all 83 `FUSE_*` registers from `fw/fuse_image.hex` + `CPTRA_FUSE_WR_DONE` (or START_DONE only after a warm reset) → ROM boots (Nios services `etrng_req`) →
`ready_for_fw_push` → Nios mailbox **FIRMWARE_LOAD** of `fw/caliptra-fw-bundle.hex` (held in `soc_fw_store`) → `ready_for_runtime` → MAGIC `0xCA11F00D`.
Fatal errors recover via a pwrgood cycle; non-fatal errors are logged and cleared. Fuse image is generated by `scripts/gen_fuse_image.py` (TEST values only). Details: [`quartus_a5e_nios/README.md`](quartus_a5e_nios/README.md). Sim: `sim/run_nios_top_fw.sh` (`+test=all` by default). Revision-3 Verilator results: sync, pauser, prod (`ready_for_runtime` at cycle 24,064,900), warm (back to runtime at 32,845,182 without FIRMWARE_LOAD), fatal (pwrgood recovery + full fuse push) and all — **all PASS**; see [`sim/BOOT_NIOS_TOP_PROD.md`](sim/BOOT_NIOS_TOP_PROD.md) and §13 of the integration note.

# Caliptra 2.x — Firmware, Keys and Fuse-Image Preparation

> **Where the files are (published copy).** This guide was written in the local Caliptra 2.x design tree. In this repo, the 2.x sources it names live under [`caliptra2x/`](../../caliptra2x/):
> - `rtl_2x/`, `sim_2x/`, `sim/rst_release_stub.sv`, `fw_2x/`, `scripts/gen_fuse_image_2x.py` and `quartus_a5e_2x/` → `caliptra2x/…`
> - `docs/P1_FIT_RESULT_2X_A5E.md` and `docs/CALIPTRA_2X_INTEGRATION_PLAN.md` → this folder
> - The 1.x guide `docs/NIOS_CALIPTRA_INTEGRATION.md` is [`../NIOS_CALIPTRA_INTEGRATION.md`](../NIOS_CALIPTRA_INTEGRATION.md)
>
> caliptra-rtl and caliptra-sw are not vendored.

- **Applies to:** `fw_2x/` and `scripts/gen_fuse_image_2x.py` in this repo.
- **Source:** caliptra-sw `dd1e79d5bf55a9bd5bdb05915757eaf34844145d`, tags `rom-2.1.3-1` and `fw-2.1.4` (checked out on the build box at `/workspace/caliptra-sw-rom`).
- **Hardware revision:** `--hw-revision 2.1`, matching caliptra-rtl v2.1.2 (`CPTRA_HW_REV_ID` reads `0x212`).
- **Related:** [NIOS_CALIPTRA_2X_INTEGRATION.md](NIOS_CALIPTRA_2X_INTEGRATION.md) §8 (fuse map), [SIMULATION_2X.md](SIMULATION_2X.md).

> ⚠️ **The firmware bundle in `fw_2x/` is signed with caliptra-sw's public "fake" test keys.** The private halves of every vendor and owner key are published in caliptra-sw `image/fake-keys/src/lib.rs`, for example `VENDOR_ECC_KEY_0_PRIVATE`, `VENDOR_MLDSA_KEY_0_PRIVATE`, `OWNER_ECC_KEY_PRIVATE` and `OWNER_MLDSA_KEY_PRIVATE`. A device fused with the hashes in `fw_2x/fuse_image_2x.hex` will accept **any** firmware anyone signs with those keys. Use them for simulation and FPGA study only. §6 describes the production procedure.

---

## 1. Artifacts in `fw_2x/`

| File | Size | What it is |
|---|---:|---|
| `caliptra-rom.bin` | 98,304 B (96 KiB) | 2.x ROM **with UART logging** (`ROM_WITH_UART`). SHA-256 `26d505a7ec938d14adbc82627cebd00e3240f7fdd3da464bb4a325c82e18cef2` |
| `caliptra-rom.hex` | 12,288 lines | ROM as little-endian **64-bit** words, one per line (`$readmemh` into `caliptra_rom_m20k`) |
| `caliptra-fw-bundle.bin` | 253,440 B | Signed bundle: manifest + FMC + runtime. SHA-256 `361bdf44d0267dc2f3073f62dc888c94ef929c6095e5d62a615c278b520524f2` |
| `caliptra-fw-bundle.hex` | 63,360 lines | Bundle as little-endian **32-bit** words (`$readmemh` into `soc_fw_store`) |
| `SHA256SUMS` | | `sha256sum *.bin` (covers the two `.bin` files only) |
| `fuse_image_2x.hex` | 117 lines | Fuse image derived from the bundle (§5) |
| `build_rom.sh` | | Rebuild script (§2) |

Verify with `cd fw_2x && sha256sum -c SHA256SUMS`. Both hex files were checked word-for-word against the `.bin` files (all 12,288 / 63,360 words match).

---

## 2. Building the ROM and bundle (`fw_2x/build_rom.sh`)

```bash
source ~/.cargo/env
SW=${SW:-/workspace/caliptra-sw-rom}          # caliptra-sw at dd1e79d
cd $SW
cargo run --release --manifest-path builder/Cargo.toml --bin image -- --hw-revision 2.1 \
  --rom-with-log $OUT/caliptra-rom.bin --fw $OUT/caliptra-fw-bundle.bin
# then: pad + convert to caliptra-rom.hex (64-bit LE words) and caliptra-fw-bundle.hex (32-bit LE words)
sha256sum *.bin > SHA256SUMS
```

The `image` binary is `builder/bin/image_gen.rs` (`[[bin]] name = "image"` in `builder/Cargo.toml`). With the options above it does the following:

| Option | Effect in `image_gen.rs` |
|---|---|
| `--hw-revision 2.1` | Sets `CALIPTRA_HW_REV=2.1` before building |
| `--rom-with-log FILE` | `build_firmware_rom(&firmware::ROM_WITH_UART)` (ROM with UART log → the `LOG` lines in the sim) |
| `--fw FILE` | `build_and_sign_image(&FMC_WITH_UART, &APP_WITH_UART_OCP_LOCK, image_options)` |
| *(no `--image-options`)* | `ImageOptions { fmc_version: version::get_fmc_version(), app_version: version::get_runtime_version(), fw_svn (default 0), pqc_key_type (default MLDSA), ..Default::default() }` |

`ImageOptions::default()` (`builder/src/lib.rs`) supplies the keys:

| Field | Default | Meaning |
|---|---|---|
| `vendor_config` | `caliptra_image_fake_keys::VENDOR_CONFIG_KEY_0` | 4 vendor ECC P-384 keys, 4 ML-DSA-87 keys (32 LMS keys also defined); active `ecc_key_idx = 0`, `pqc_key_idx = 0`; **private keys included**; `pl0_pauser = 0x1` |
| `owner_config` | `Some(caliptra_image_fake_keys::OWNER_CONFIG)` | 1 owner ECC P-384 key + 1 ML-DSA-87 key (+ LMS), **private keys included** |
| `pqc_key_type` | `FwVerificationPqcKeyType::MLDSA` (= 1; LMS = 3) | |
| `fw_svn` | 0 | |

**Values decoded from the bundle we built** (parsed from `caliptra-fw-bundle.bin`):

| Field | Value |
|---|---|
| Manifest marker / size | `0x324E4D43` ("CMN2") / 16,956 B |
| `pqc_key_type` | 1 (ML-DSA) |
| ECC key descriptor | version 1, `key_hash_count` 4 |
| PQC key descriptor | version 1, key type 1, `key_hash_count` 4 |
| Active vendor key index (ECC / PQC) | 0 / 0 |
| Header `flags` / `toc_len` / `pl0_pauser` / `svn` | `0x1` / 2 / `0x1` / 0 |
| FMC TOC | version `0x1044`, load = entry = `0x40000000`, offset 16,956, size 30,760 |
| Runtime TOC | version `0x2010004`, load = entry = `0x40008000`, offset 47,716, size 205,516 |

The ROM log in the sim agrees: `Load FMC at address 0x40000000 len 30760` and `Load Runtime at address 0x40008000 len 205516`.

---

## 3. Bundle / manifest layout (2.x, "CMN2")

From caliptra-sw `image/types/src/lib.rs`. Offsets are into `caliptra-fw-bundle.bin`.

| Offset | Size | Field |
|---:|---:|---|
| 0 | 4 | `marker` = `0x324E4D43` |
| 4 | 4 | `size` = 16,956 |
| 8 | 1 + 3 | `pqc_key_type`, reserved |
| **12** | **1,736** | `preamble.vendor_pub_key_info` = ECC descriptor (4 + 4×48) + PQC descriptor (4 + 32×48) → **hashed into `FUSE_VENDOR_PK_HASH`** |
| 1,748 | 4 | `vendor_ecc_pub_key_idx` |
| 1,752 | 96 | `vendor_ecc_active_pub_key` (x, y) |
| 1,848 | 4 | `vendor_pqc_pub_key_idx` |
| 1,852 | 2,592 | `vendor_pqc_active_pub_key` |
| 4,444 | 96 + 4,628 | `vendor_sigs` (ECC r‖s, PQC signature) |
| **9,168** | **2,688** | `owner_pub_keys` = ECC (96) + PQC (2,592) → **hashed into `CPTRA_OWNER_PK_HASH`** |
| 11,856 | 96 + 4,628 | `owner_sigs` |
| 16,580 | 8 | reserved |
| 16,588 | 160 | `header` (revision, key idx, flags, toc_len, pl0_pauser, toc_digest, **svn @ +76**, vendor_data, owner_data @ +120) |
| 16,748 | 2 × 104 | TOC: FMC, runtime |
| 16,956 | 30,760 | FMC image |
| 47,716 | 205,516 | Runtime image |
| 253,232 | 208 | padding to the 253,440-byte bundle size |

**What gets signed** (`image/gen/src/generator.rs`):
- **Vendor:** ECC-P384 signs SHA-384(`header[0..120]`), i.e. the header up to `owner_data` (bundle bytes 16,588–16,707). ML-DSA-87 signs those raw 120 bytes (pure ML-DSA, empty context).
- **Owner:** ECC signs SHA-384(the full 160-byte header, bytes 16,588–16,747). ML-DSA signs those raw bytes.
- The header's `toc_digest` covers the TOC, and each TOC entry's digest covers its image.
- Keys and signatures are stored in "hw format": 32-bit words, little-endian in the file, most-significant word first.
- *Verified:* the vendor and owner ECC signatures in our bundle check out against the active public keys over exactly these byte ranges. The ML-DSA ranges are taken from the generator source and were not independently verified.

---

## 4. Byte-to-hex conversion

`build_rom.sh` (inline Python):
- **ROM:** pad to a multiple of 8, then write each 8 bytes as `%016x` of a little-endian u64. That gives 12,288 lines for `CALIPTRA_IMEM_DEPTH` = 12288 × 64-bit.
- **Bundle:** pad to a multiple of 4, then write each 4 bytes as `%08x` of a little-endian u32. That gives 63,360 lines. `soc_fw_store` has 65,536 words, and the Nios streams words 0..63,359 into `MBOX_DATAIN`.

---

## 5. Fuse image generation (`scripts/gen_fuse_image_2x.py`)

```bash
python3 scripts/gen_fuse_image_2x.py [path/to/caliptra-fw-bundle.bin]   # default fw_2x/caliptra-fw-bundle.bin
# -> fw_2x/fuse_image_2x.hex: 117 entries (104 fuse words + 13 owner-hash/lock); +FUSE_WR_DONE = 118 AXI writes; pqc_key_type=1
```

What the script does:
1. **Checks the bundle.** It asserts:
   - marker = `CMN2`;
   - `pqc_key_type` ∈ {1, 3};
   - `manifest.size` = 16,956 (the 2.x layout);
   - header SVN = 0 (it refuses otherwise, because the SVN fuses are written as 0);
   - the PQC descriptor's key type equals the manifest `pqc_key_type`.
2. **Vendor hash.** `FUSE_VENDOR_PK_HASH` = SHA-384(bundle[12 : 12+1736]), written as 12 **big-endian** 32-bit words. This matches caliptra-sw `image_pk_desc_hash` / `bytes_to_be_words_48`, and the `caliptra-image-app --print-hashes` computation (`image/app/src/create/mod.rs`).
3. **Owner hash.** `CPTRA_OWNER_PK_HASH` = SHA-384(bundle[9168 : 9168+2688]) (owner ECC key 96 B + PQC key field 2,592 B), written as 12 **big-endian** 32-bit words to `0x30140–0x3016C`. Then `CPTRA_OWNER_PK_HASH_LOCK` = 1.
4. **PQC type.** `FUSE_PQC_KEY_TYPE` = manifest `pqc_key_type` (1).
5. **STUDY seeds.** STUDY UDS (16 words) and FE (8 words) from fixed formulas, **not secrets**. Every other fuse word is 0, except `FUSE_SOC_STEPPING_ID` = 1.
6. **Output.** Writes `{addr,data}` lines (see the integration guide §8 for the full table) and prints both hashes. With the current bundle:
   - `vendor_pk_hash 30399676 a17e3e97 3677b3ff 862f4bf2 d1932d88 4778453c 376fe00d c93fb8aa 0770f3eb f3411a08 53e9c57e ce8a2980`
   - `owner_pk_hash  48afdb07 3c5e0d4e e4649046 8ef81f2c f57249b6 e76a28f5 fca4de69 6a7d3e2e d3efc4e6 77431854 3e95307a 54988bd7`

Because the hashes come from the bundle itself, **re-run the script after every bundle rebuild or re-sign**, then rebuild the sim or bitstream (the image is `$readmemh`'d at elaboration). Re-running it on the committed bundle reproduces `fuse_image_2x.hex` byte for byte.

**What the ROM checks against these values** (`image/verify/src/verifier.rs`, when not Unprovisioned):
- `FUSE_PQC_KEY_TYPE` must equal the manifest PQC type (`IMAGE_VERIFIER_ERR_PQC_KEY_TYPE_MISMATCH`).
- `FUSE_VENDOR_PK_HASH` must be non-zero and match the descriptor digest.
- The active vendor key's hash must appear in the descriptor, and the key must not be revoked.
- The owner key digest must match `CPTRA_OWNER_PK_HASH`.
- Signatures must verify.
- Image SVN must be ≥ fuse SVN (unless anti-rollback is disabled).

---

## 6. Production key preparation (procedure)

Steps marked *(untested here)* follow the caliptra-sw source but were not run in this project.

### 6.1 Decide the key set

| Key | Algorithm | Count | Held by |
|---|---|---|---|
| Vendor firmware-signing keys | ECC P-384 | 1–4 (`VENDOR_ECC_MAX_KEY_COUNT` = 4) | Silicon or firmware vendor HSM |
| Vendor PQC keys | **ML-DSA-87** (`pqc_key_type` = 1) **or** LMS (`= 3`) | ML-DSA 1–4 (`VENDOR_MLDSA_MAX_KEY_COUNT`), LMS 1–32 (`VENDOR_LMS_MAX_KEY_COUNT`) | Vendor HSM |
| Owner key | ECC P-384 + one PQC key of the bundle's single `pqc_key_type` (ML-DSA-87 if 1, LMS if 3) | 1 each | Platform owner HSM |

- All vendor public keys are hashed into one descriptor, so `FUSE_VENDOR_PK_HASH` commits to the whole set.
- Keep spare keys for revocation. The **last** key index can never be revoked (`verify_vendor_ecc_pk_idx`: "Last key index is never revoked").

### 6.2 Generate keys in an HSM

- Generate every private key **inside the HSM** (non-exportable). Export only the public keys.
- Formats the caliptra-sw tools read (`image/gen/src/lib.rs`, `image/crypto/src/openssl.rs`):

| Key | Format accepted |
|---|---|
| ECC P-384 public | PEM `PUBLIC KEY` (SPKI) |
| ECC P-384 private (only for local test signing) | PEM, read via OpenSSL `EcKey::private_key_from_pem` |
| ML-DSA-87 public | Raw 2,592-byte file, **or** PEM SPKI (the BIT STRING payload is used) |
| ML-DSA-87 private (local test only) | Raw 4,896-byte expanded key, or PEM PKCS#8 whose privateKey octets are exactly that raw key |
| LMS public / private | PEM or raw `ImageLmsPublicKey` / `ImageLmsPrivKey` structs |

- **Local test keys** with OpenSSL 3.5 (for a dry run of the flow, never for a product):
  ```bash
  mkdir -p keys && chmod 700 keys            # keys/ is gitignored (see 6.6)
  openssl ecparam -name secp384r1 -genkey -noout -out keys/vnd_ecc0_priv.pem
  openssl ec -in keys/vnd_ecc0_priv.pem -pubout -out keys/vnd_ecc0_pub.pem
  openssl genpkey -algorithm ML-DSA-87 -provparam ml-dsa.output_formats=priv-only -out keys/vnd_mldsa0_priv.pem
  openssl pkey -in keys/vnd_mldsa0_priv.pem -pubout -out keys/vnd_mldsa0_pub.pem   # SPKI, accepted as-is
  ```
- **ML-DSA private key format caveat.** OpenSSL's PKCS#8 for ML-DSA wraps the 4,896-byte key in an inner OCTET STRING: the privateKey field is 4,900 bytes. This was checked with OpenSSL 3.5.7 on the box. The caliptra-sw reader takes those octets directly, so it would get 4,900 bytes and fail. Extract the raw key first, e.g. `python3 -c "import base64,sys;d=base64.b64decode(''.join(l for l in open(sys.argv[1]) if not l.startswith('-----')));open(sys.argv[2],'wb').write(d[-4896:])" keys/vnd_mldsa0_priv.pem keys/vnd_mldsa0_priv.bin` *(untested with the image tool)*.

### 6.3 Sign the firmware — mechanisms that exist in caliptra-sw `dd1e79d`

**A. `caliptra-image-app create` with a key-config TOML** (`image/app`).
- This signs **ELF** FMC/runtime with key files listed in a TOML. Arguments:
  - `--pqc-key-type 1|3`, `--key-config <toml>`, `--ecc-pk-idx`, `--pqc-pk-idx`
  - `--fmc <elf> --fmc-version N --fmc-rev <hex>`, `--rt <elf> --rt-version N --rt-rev <hex>`
  - `--fw-svn N --out <bundle>`, optional `--own-from-date/--own-to-date/--mfg-from-date/--mfg-to-date`, `--print-hashes`
- Key-config schema (`image/app/src/create/config.rs`); paths are relative to the TOML file:
  ```toml
  [vendor]
  ecc_pub_keys   = ["vnd_ecc0_pub.pem", "vnd_ecc1_pub.pem", "vnd_ecc2_pub.pem", "vnd_ecc3_pub.pem"]
  lms_pub_keys   = []
  mldsa_pub_keys = ["vnd_mldsa0_pub.pem", "vnd_mldsa1_pub.pem", "vnd_mldsa2_pub.pem", "vnd_mldsa3_pub.pem"]
  ecc_priv_keys   = ["vnd_ecc0_priv.pem", ...]     # optional
  mldsa_priv_keys = ["vnd_mldsa0_priv.bin", ...]   # optional
  [owner]
  ecc_pub_key   = "own_ecc_pub.pem"
  lms_pub_key   = ""                               # field is required by the schema; read only for LMS
  mldsa_pub_key = "own_mldsa_pub.pem"
  ecc_priv_key   = "own_ecc_priv.pem"              # optional
  mldsa_priv_key = "own_mldsa_priv.bin"            # optional
  ```
- If the private keys are omitted, the image is generated with **zero signatures**. The tool needs the private keys locally to sign, so with non-exportable HSM keys use **B** for the signatures.
- Get the ELFs with `image --all_elfs <dir>` (`builder/bin/image_gen.rs`).
- `--fmc-rev`/`--rt-rev`/`--pqc-pk-idx` are declared optional but are unwrapped in `run_cmd`, so pass them.

**B. `image` builder with `--image-options`, `--hashes`, and signature override** (`builder/bin/image_gen.rs`). This is the external/HSM path.
- `--image-options <toml>` replaces the `ImageOptions` struct (versions, `fw_svn`, `pqc_key_type`, full `vendor_config` / `owner_config` with inline public keys and optional private keys). The reference is `builder/test_data/default_image_options.toml`, which is a copy of the fake-key defaults, *including private keys*. For production, put your public keys in and **leave out** `priv_keys`.
- `--hashes <json>` writes `{"vendor": SHA-384(header[..owner_data]), "owner": SHA-384(header)}`. These are the ECC message digests "for external signing tools".
- `--vendor-sig-override <file>` / `--owner-sig-override <file>` replace `preamble.vendor_sigs` / `owner_sigs` with the bytes of `<file>`, parsed as `ImageSignatures`. That is the ECC signature (r‖s, 96 B, hw format) followed by the PQC signature field (4,628 B), 4,724 B total. The CLI help text still says "ECC … concatenated with an LMS signature"; the struct holds whichever PQC type is selected.

**HSM signing procedure (B), *(untested here)*:**
1. Build once with your public-key-only `--image-options` plus `--hashes h.json`. The bundle comes out with zero signatures.
2. Sign with the HSM:
   - **ECC:** sign `h.json.vendor` with the active vendor ECC key and `h.json.owner` with the owner ECC key (ECDSA P-384 over the given SHA-384 digest).
   - **ML-DSA-87:** sign the **raw header bytes**, not the digest. Vendor = bundle[16588:16708], owner = bundle[16588:16748] (§3). Pure ML-DSA, empty context. `--hashes` does not export these bytes, so cut them from the step-1 bundle.
3. Assemble the two 4,724-byte `ImageSignatures` files. Convert r, s and the ML-DSA signature into caliptra's word order (§3); the ML-DSA signature is 4,627 B plus 1 pad byte.
4. Rebuild with the step-1 public-key-only `--image-options` TOML plus `--vendor-sig-override vsig.bin --owner-sig-override osig.bin`. Alternatively, patch the bytes at offsets 4,444 and 11,856 of the step-1 bundle.
   - Rebuilding is only valid if the build is reproducible. caliptra-sw has a consistency test for ELF builds, but this was not checked here.
5. Verify before fusing:
   - Check the ECC signatures with your public keys over the §3 byte ranges: ECDSA P-384 over SHA-384 of bundle[16588:16708] (vendor) and bundle[16588:16748] (owner). This is the check that passed on the fake-key bundle.
   - Boot in Verilator ([SIMULATION_2X.md](SIMULATION_2X.md)), or in caliptra-sw's emulator, with the regenerated fuse image.

No other external-signing tool exists in caliptra-sw `dd1e79d`: no PKCS#11 / HSM plug-in.

### 6.4 Regenerate the fuse image

- `python3 scripts/gen_fuse_image_2x.py path/to/your-bundle.bin`. This recomputes `FUSE_VENDOR_PK_HASH` and `CPTRA_OWNER_PK_HASH` from your keys and sets `FUSE_PQC_KEY_TYPE`.
- Cross-check against `caliptra-image-app … --print-hashes` (§6.3 A) if you build with method A.
- In a product:
  - `FUSE_VENDOR_PK_HASH`, `FUSE_PQC_KEY_TYPE`, revocations and SVNs are burned into OTP at manufacturing.
  - `CPTRA_OWNER_PK_HASH` (a register in 2.x) is written and locked from immutable SoC logic or ROM on every cold boot, from owner-controlled storage.
  - The UDS seed and field entropy are generated per device and protected by the obfuscation key. They are **never** the STUDY formulas in the script.
- The script currently asserts bundle SVN = 0. Change its SVN handling (and the fuse values) when you adopt an SVN policy (§6.5).

### 6.5 SVN and revocation policy

- **FW SVN:**
  - Header `svn` is set by `fw_svn` (`--fw-svn` or the image-options `fw_svn`). Maximum 128 (`MAX_FIRMWARE_SVN`).
  - The fuse SVN is `128 − leading_zeros(FUSE_RUNTIME_SVN[0..3] as u128)`, i.e. the position of the highest burned bit (`drivers/src/fuse_bank.rs`, `first_set_msbit`). Burning bit *n*−1 sets fuse SVN *n*.
  - The ROM rejects images with `svn` < fuse SVN, unless `FUSE_ANTI_ROLLBACK_DISABLE` is set (keep it 0 in production).
  - Bump the SVN only for security fixes, and burn the next bit only after the new image is deployed fleet-wide.
- **Vendor key revocation:**
  - `FUSE_ECC_REVOCATION` (4-bit mask), `FUSE_MLDSA_REVOCATION` or `FUSE_LMS_REVOCATION` (masks); bit *i* revokes vendor key *i*.
  - The last index cannot be revoked.
  - After revoking key *i*, sign with key *i*+1 (`ecc_key_idx` / `pqc_key_idx`).
- **Owner key rotation:** sign with the new owner key, and update the owner hash the SoC writes into `CPTRA_OWNER_PK_HASH`. It is not a fuse in 2.x, so this needs no OTP burn, but the storage must be authenticated.
- `FUSE_FMC_KEY_MANIFEST_SVN`, `FUSE_SOC_MANIFEST_SVN` and `FUSE_SOC_MANIFEST_MAX_SVN` are written 0 in this study.

### 6.6 Keep keys out of git

- The repo `.gitignore` now ignores `keys/`, `*.key`, `*_priv*.pem`, `*_priv*.bin`, `*.p8`, `*.p12` and `*.pfx`. Even so, never copy private keys into the tree. Keep them in the HSM and keep only public keys and bundles in git.
- The fake-key private halves are already public upstream; they are **not** copied into this repo.
- Review `git status` before every commit when working with real keys.

---

## 7. Checklist before you trust a bundle

1. `sha256sum -c fw_2x/SHA256SUMS` passes (or record new sums).
2. The bundle parses with marker `CMN2`, the expected `pqc_key_type`, SVN and TOC sizes (the §2 table, or the asserts in `gen_fuse_image_2x.py`).
3. The fuse image was regenerated from **this** bundle, and both printed hashes match your HSM's public keys.
4. Verilator boot reaches `[fwproc] Img verified …` and `ready_for_runtime` with that fuse image.
5. No private key is in the working tree (`git status`, `git ls-files | grep -i priv`).

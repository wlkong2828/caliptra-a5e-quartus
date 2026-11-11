# Caliptra 2.x passive — attestation exercise (measurement capture + certificate dump)

**Design under test:** `caliptra2x/rtl_2x/nios_caliptra2x_top.sv` (caliptra-rtl v2.1.2, core-only passive mode, AXI) +
`caliptra2x/fw_2x/caliptra-rom.bin` (rom-2.1.3-1) + `caliptra2x/fw_2x/caliptra-fw-bundle.bin` (fw-2.1.4, **public caliptra-sw test keys**),
fuses from `caliptra2x/fw_2x/fuse_image_2x.hex` (STUDY UDS/FE, vendor PK hash, owner PK hash register + lock, PQC type 1),
DEVICE_PRODUCTION + debug locked, Nios = AxUSER 1 (mailbox + TRNG user), fuse controller = AxUSER 2.
TEST/STUDY material only — nothing here is a product secret or product identity.

## 1. What was proven

| Claim | Evidence | Step A (sw-emulator) | Step B (RTL) |
|---|---|---|---|
| Caliptra RT accepts a SoC measurement (`STASH_MEASUREMENT`) | resp `dpe_result = 0`, mailbox `CMD_COMPLETE/DATA_READY`, checksum OK | PASS | PASS |
| The measurement is **stored in PCR31** | `QUOTE_PCRS` PCR31 goes `0…0` → `SHA384(0^48 ‖ M)` | PASS | PASS |
| PCR evidence is **signed by Caliptra** | ECC + ML-DSA quote signatures verify with the **FMC Alias** public key; digest recomputed from the 32 PCRs + nonce | PASS | PASS (FMC Alias sig; digest recomputes with the RTL nonce word order, see §7) |
| The measurement is **in the DPE context tree** and attested | DPE `CertifyKey` leaf: MultiTcbInfo entry `type='NIOS'`, `svn=1`, `fwid sha384 = M`, `vendorInfo = 00000001` (locality = AxUSER 1); absent in the leaf certified *before* the stash | PASS | PASS |
| Full DICE cert chain can be dumped over the mailbox | IDevID, LDevID, FMC Alias, RT Alias, DPE leaf, DPE `GetCertificateChain` — ECC P-384 **and** ML-DSA-87 | PASS (34/34 commands) | PASS (34/34 commands) |
| Chain verifies cryptographically | `openssl verify` (OpenSSL 3.5.7) each link + full chain to the test mfg CA, strict (no `-ignore_critical`) | ECC OK, ML-DSA-87 OK | ECC OK, ML-DSA-87 OK |
| Same device identity in emulator and RTL | byte-compare of every DER and every raw mailbox response | — | All DERs identical; mailbox responses identical except 3 QUOTE_PCRS (same PCRs/nonce; digest+sig differ because the emulator and RTL feed the nonce words to SHA-512 in opposite order) |

## 2. Measurement used

| Field | Value |
|---|---|
| Image measured (stand-in for the Nios application) | ASCII `Nios V SoC application image v1.0 (A5E attestation exercise)` |
| `measurement` M = SHA-384(image) | `a206a828e5aa1592be7e20300d6b735667df5ed305fa3603501a04ff9286fce00870532215cb9664525e8ae7c5281877` |
| `metadata` (4-byte TCI tag) | `NIOS` (4e 49 4f 53) |
| `context` | SHA-384(`nios-app-context`) |
| `svn` | 1 |
| Expected PCR31 after stash = SHA-384(0^48 ‖ M) | `bbd599442d64ee6a19f3548c6066453c415316310aa65a6ce588eb21f027e1ab89ddd9e3d39a3bd190ccf6692b72a1a2` |

### Where the measurement shows up

1. **PCR31** (`PCR_ID_STASH_MEASUREMENT`): `runtime/src/stash_measurement.rs` extends PCR31 with M. Quote before
   stash: PCR31 = all-zero; after: `bbd59944…72a1a2` = expected value, identical in the ECC and ML-DSA quotes.
2. **DPE context**: the same command runs DPE `DeriveContext(data=M, tci_type=metadata, MAKE_DEFAULT|CHANGE_LOCALITY…,
   target_locality=caller AxUSER)`. A `CertifyKey` on the default handle afterwards yields a DPE leaf whose
   `tcg-dice-MultiTcbInfo` (2.23.133.5.4.5) has three TCB entries:
   | idx | type (as encoded) | meaning | svn | vendorInfo (locality) | fwid (SHA-384) |
   |---|---|---|---|---|---|
   | 0 | `RMTR` (= `RTMR` u32) | Caliptra RT current PCR (DPE root) | 0 | `ffffffff` (Caliptra) | `12b8f5b0…963fc41` (= PCR2) |
   | 1 | `VICC` (= `CCIV` u32) | Caliptra-configured init values | 0 | `00000001` | `0c10074f…d8fb7215` |
   | 2 | **`NIOS`** | **our stashed measurement** | **1** | `00000001` (Nios AxUSER) | **`a206a828…c5281877` = M** |
   The leaf certified *before* the stash has only entries 0 and 1, so entry 2 is our measurement.
3. **Not in the RT Alias cert.** The RT Alias `TcbInfo` holds the ROM-measured RT firmware digest
   (`e3dc800c…e14cc1a2`, = `FW_INFO.runtime_sha384_digest`); the FMC Alias `MultiTcbInfo` holds the FMC digest
   (`13ab8249…bb856f9f`), owner-info and vendor-info fuse digests. Both are created at boot, before any runtime stash,
   so a runtime `STASH_MEASUREMENT` only appears in PCR31 and in DPE leaves. (A measurement stashed *in ROM*
   before FIRMWARE_LOAD would land in PCR31 via the ROM measurement log; not exercised here.)

## 3. Mailbox commands (caliptra-sw dd1e79d `api/src/mailbox.rs`)

Every request is `chksum(u32) ‖ payload`, `chksum = 0 − Σ(bytes of cmd LE ‖ payload)` (`api/src/checksum.rs`); every
response is `chksum ‖ fips_status ‖ …` and the driver checks the response checksum (`calc_checksum(0, resp[4:])`).
Nios register sequence (`tb_nios2x_top_fw.sv` `mbox_cmd_from_file`): read `MBOX_LOCK` until 0 → `MBOX_CMD` →
`MBOX_DLEN` → `MBOX_DATAIN`×⌈dlen/4⌉ → `MBOX_EXECUTE=1` → poll `MBOX_STATUS[3:0]` (servicing `etrng_req`) →
if `DATA_READY` read `MBOX_DLEN` + `MBOX_DATAOUT`×⌈dlen/4⌉ → `MBOX_EXECUTE=0`. AxUSER = 1.

| # | Command | ID | Request payload | Response used |
|---|---|---|---|---|
| 0 | FW_INFO | `0x494E464F` "INFO" | — | FMC/RT SHA-384, revisions |
| 1 | GET_IDEV_ECC384_INFO | `0x49444549` "IDEI" | — | IDevID P-384 pub x‖y |
| 2 | GET_IDEV_MLDSA87_INFO | `0x49444D49` "IDMI" | — | IDevID ML-DSA-87 pub (2592 B) |
| 3–5 | GET_LDEV / GET_FMC_ALIAS / GET_RT_ALIAS _ECC384_CERT | `0x4C444556` "LDEV", `0x43455246` "CERF", `0x43455252` "CERR" | — | `data_size ‖ DER` |
| 6–8 | GET_LDEV / GET_FMC_ALIAS / GET_RT_ALIAS _MLDSA87_CERT | `0x4C444D43` "LDMC", `0x434D4346` "CMCF", `0x434D4352` "CMCR" | — | `data_size ‖ DER` |
| 9 | QUOTE_PCRS_ECC384 (before) | `0x50435251` "PCRQ" | nonce[32] | 32 PCRs, nonce, reset ctrs, digest[48], r, s |
| 10 | INVOKE_DPE_ECC384 GetProfile | `0x44504543` "DPEC" | `data_size ‖ {magic "DPEC", cmd 0x01, profile 4}` | DPE profile |
| 11 | INVOKE_DPE_ECC384 CertifyKey (before) | "DPEC" | hdr(cmd 0x09) ‖ handle 0×16 ‖ flags 0 ‖ format 0 (X.509) ‖ label[48] | handle ‖ pub ‖ cert |
| 12 | **STASH_MEASUREMENT** | `0x4D454153` "MEAS" | metadata[4] ‖ measurement[48] ‖ context[48] ‖ svn | `dpe_result` = 0 |
| 13 | QUOTE_PCRS_ECC384 (after) | "PCRQ" | nonce2 | PCR31 |
| 14 | INVOKE_DPE_ECC384 CertifyKey (after) | "DPEC" | as #11 | DPE ECC leaf |
| 15–16 | INVOKE_DPE_ECC384 GetCertificateChain | "DPEC" | hdr(cmd 0x10) ‖ offset ‖ size=2048 | chain chunks (2 calls, 2586 B) |
| 17 | INVOKE_DPE_MLDSA87 GetProfile | `0x4450454D` "DPEM" | flags ‖ axi_response{lo,hi,max}=0 ‖ data_size ‖ {"DPEC", 0x01, profile 5} | |
| 18 | INVOKE_DPE_MLDSA87 CertifyKey | "DPEM" | as #14, profile 5 | DPE ML-DSA leaf |
| 19–30 | INVOKE_DPE_MLDSA87 GetCertificateChain | "DPEM" | offset ‖ 2048 | 12 chunks (23,658 B) |
| 31 | QUOTE_PCRS_MLDSA87 | `0x5043524D` "PCRM" | nonce2 | digest[64], ML-DSA sig |
| 32 | GET_IDEV_ECC384_CERT | `0x49444543` "IDEC" | tbs_size ‖ sig_r[48] ‖ sig_s[48] ‖ tbs | assembled IDevID cert |
| 33 | GET_IDEV_MLDSA87_CERT | `0x49444D43` "IDMC" | tbs_size ‖ sig[4628] ‖ tbs | assembled IDevID cert |

Not used: EXTEND_PCR / INCREMENT_PCR_RESET_COUNTER (not needed; reset counters read back 0), GET_IDEV_*_CSR (the
IDevID CSR is only produced in Manufacturing lifecycle with the GENERATE_IDEVID_CSR request; we boot Production).

## 4. How the IDevID certificate is produced (passive mode)

Caliptra derives the IDevID key pair from UDS (deterministic) but **does not hold an IDevID certificate**; that is the
manufacturer's job. `GET_IDEV_*_CERT` only *assembles* `Certificate{tbs, sigAlg, signature}` from a TBS + signature
supplied by the SoC (`runtime/src/dice.rs`). The flow used here (`attest/attest_driver.py: build_idev_tbs`):

1. `GET_IDEV_ECC384_INFO` / `GET_IDEV_MLDSA87_INFO` → IDevID public key; wrap it as SubjectPublicKeyInfo.
2. Subject = **exactly the issuer DN Caliptra wrote into the LDevID cert** (`CN=Caliptra 2.1 Ecc384 IDevID,
   serialNumber=<SHA-256 of key>`); ECC: SKI = LDevID's AKI, `basicConstraints CA:TRUE`, `keyUsage keyCertSign`.
3. A local **TEST mfg CA** (`attest/testca/test_mfg_ca_{ecc,mldsa}.pem`; ECC P-384 / ML-DSA-87 generated by
   OpenSSL 3.5.7; private keys `*.key` are git-ignored) signs it: `openssl x509 -new -force_pubkey`.
4. The TBS and signature are split out and sent to Caliptra; the returned cert is byte-identical to OpenSSL's cert
   (`idev_*_cert_eq_openssl_ref = true`) and its key equals the `*_INFO` key.
5. ML-DSA size limit: `GetIdevMldsa87CertReq` accepts at most 2820 B of TBS. With a 2592-byte key and the 113-byte
   Caliptra subject, the ML-DSA IDevID TBS was cut to 2818 B: CA name `CN=CA`, serial `01`, 10-year UTCTime validity,
   one non-critical extension `basicConstraints CA:TRUE` (no SKI/AKI/KU).
6. The TBS+signature are cached by public key in `attest/testca/idev_*`, so Step A and Step B submit
   byte-identical requests (OpenSSL ECDSA signing is randomized).

## 5. Certificates (Step A; Step B identical — see §7)

| File (`attest_ref/{emu,rtl}/`) | Subject CN | Issuer CN | Key / Sig | Basic constraints | DICE extensions | Size |
|---|---|---|---|---|---|---|
| `idevid_ecc384` | Caliptra 2.1 Ecc384 IDevID, sn 465F2680… | TEST Mfg CA ECC (O=TEST ONLY Nios-A5E Mfg) | P-384 / ecdsa-SHA384 | CA:TRUE | — (KU certSign, SKI/AKI) | 583 |
| `ldevid_ecc384` | Caliptra 2.1 Ecc384 LDevID, sn 1F841080… | …Ecc384 IDevID | P-384 / ecdsa-SHA384 | CA, pathlen 6 | Ueid, EKU | 717 |
| `fmc_alias_ecc384` | Caliptra 2.1 Ecc384 FMC Alias, sn CF64C9DD… | …Ecc384 LDevID | P-384 / ecdsa-SHA384 | CA, pathlen 5 | Ueid, EKU, MultiTcbInfo {owner-fuse info, vendor-fuse info, FMC fw svn 256 digest 13ab8249…} | 1040 |
| `rt_alias_ecc384` | Caliptra 2.1 Ecc384 Rt Alias, sn E61EC4C2… | …Ecc384 FMC Alias | P-384 / ecdsa-SHA384 | CA, pathlen 4 | Ueid, EKU, TcbInfo {RT fw svn 256 digest e3dc800c…} | 829 |
| `dpe_ecc_leaf_after` | DPE Leaf, sn F190BA82… | …Ecc384 Rt Alias | P-384 / ecdsa-SHA384 | CA:FALSE, KU digitalSignature | MultiTcbInfo {RTMR, CCIV, **NIOS = M**}, Ueid, EKU attestLoc | 1177 |
| `idevid_mldsa87` | Caliptra 2.1 MlDsa87 IDevID, sn 27A9FFCB… | CA (TEST) | ML-DSA-87 | CA:TRUE | — | 7468 |
| `ldevid_mldsa87` | Caliptra 2.1 MlDsa87 LDevID, sn 7DC585CD… | …MlDsa87 IDevID | ML-DSA-87 | CA, pathlen 6 | Ueid, EKU | 7741 |
| `fmc_alias_mldsa87` | Caliptra 2.1 MlDsa87 FMC Alias, sn DC224A78… | …MlDsa87 LDevID | ML-DSA-87 | CA, pathlen 5 | as ECC FMC alias | 8064 |
| `rt_alias_mldsa87` | Caliptra 2.1 MlDsa87 Rt Alias, sn 8371DD71… | …MlDsa87 FMC Alias | ML-DSA-87 | CA, pathlen 4 | as ECC RT alias | 7853 |
| `dpe_mldsa_leaf_after` | DPE Leaf, sn BB08DAA2… | …MlDsa87 Rt Alias | ML-DSA-87 | CA:FALSE | MultiTcbInfo {RTMR, CCIV, **NIOS = M**}, Ueid | 8199 |
| `dpe_{ecc,mldsa}_chain_{0,1,2}` | DPE `GetCertificateChain` = LDevID, FMC Alias, RT Alias | | | | | byte-identical to #3–8 |

Validity of Caliptra-generated certs: 2023-01-01 → 9999-12-31 (caliptra-sw defaults). Serial numbers and
`serialNumber` RDNs are derived from the public keys (no randomness). Full decodes: `*.txt` (`openssl x509 -text`)
and `analysis.json` (decoded TcbInfo/MultiTcbInfo/Ueid).

## 6. Verification results (`attest/analyze.py`)

| Check | ECC P-384 | ML-DSA-87 |
|---|---|---|
| IDevID ← TEST mfg CA | OK | OK |
| LDevID ← IDevID | OK | OK |
| FMC Alias ← LDevID | OK | OK |
| RT Alias ← FMC Alias | OK | OK |
| DPE leaf ← RT Alias | OK | OK |
| Full chain CA → IDevID → LDevID → FMC → RT → DPE leaf, strict | OK | OK |
| DPE GetCertificateChain == mailbox certs | 3/3 | 3/3 |
| IDevID cert key == GET_IDEV_*_INFO | yes | yes |
| Quote digest = SHA-512(PCR0‖…‖PCR31‖bswap32(nonce)) (ECC: first 48 B; ML-DSA: byte-reversed 64 B) | yes | yes |
| Quote digest = SHA-512(PCR0‖…‖PCR31‖dword-reversed(nonce)) (RTL `pv_gen_hash` order) | no | yes (Step B) |
| Quote signature key | **FMC Alias** (KV slot 7) — verifies; IDevID/LDevID/RT Alias do not | **FMC Alias** |

Per-link checks use `openssl verify -partial_chain -CAfile <issuer>`; the full-chain check uses `-CAfile
test_mfg_ca_*.pem -untrusted <intermediates>` without `-ignore_critical`.

## 7. Step A (sw-emulator) vs Step B (RTL)

Step B finished at 8:14:14 PM CST on Tue Nov 10, 2026 (`TB_NIOS2X PASS`, Production + debug locked, 379 TRNG fills). The detached driver completed all 34 mailbox commands: every response had `status=1` (DATA_READY / CMD_COMPLETE), `fwerr=00000000`, and a valid checksum (`chk=True`). Error registers at the end of the run were all zero (`CPTRA_HW_ERROR_FATAL`, `CPTRA_FW_ERROR_FATAL`, `CPTRA_HW_ERROR_NON_FATAL`, `CPTRA_FW_ERROR_NON_FATAL`).

### Wall time and cycles

| | Step A (sw-emulator) | Step B (RTL, Verilator 5.054) |
|---|---|---|
| Wall time | ~25 s (boot to `ready_for_runtime` + 34 commands, release build) | Script-measured `wall_time_s=10639` (5:16:55 PM – 8:14:14 PM CST, America/Chicago); Verilator reported walltime 7517.801 s, speed 78.853 µs/s, cpu 29963.309 s on 4 threads |
| Sim time / cycles | — | `$finish` at 593 ms; `cyc=59280395` |
| `ready_for_runtime` | — | cycle 36597934 |
| First command complete (`FW_INFO`) | — | cycle 36624580 |
| Last command complete (`GET_IDEV_MLDSA87_CERT`) | — | cycle 59240360 |
| Attest loop done | — | cycle 59260365 |

RTL boot milestones (cycles): `ready_for_fuses=40`, `fuses_done=591`, `first_trng=379134`, `ready_for_mb_processing=5542265`, `fw_load_issued=6049751`, `mbox_complete=21319057`, `rom_to_fmc=30035490`, `fmc_to_rt=36217537`, `ready_for_runtime=36597934`, `fuse_writes=118`, `trng_fills=379`.

Per-command completion cycle (written by the TB into `resp_NNN.done`):

| # | Command | Cycle |
|---|---|---|
| 0 | FW_INFO | 36624580 |
| 1 | GET_IDEV_ECC384_INFO | 36667806 |
| 2 | GET_IDEV_MLDSA87_INFO | 36739042 |
| 3 | GET_LDEV_ECC384_CERT | 36789582 |
| 4 | GET_FMC_ALIAS_ECC384_CERT | 36843174 |
| 5 | GET_RT_ALIAS_ECC384_CERT | 36895078 |
| 6 | GET_LDEV_MLDSA87_CERT | 37055792 |
| 7 | GET_FMC_ALIAS_MLDSA87_CERT | 37225271 |
| 8 | GET_RT_ALIAS_MLDSA87_CERT | 37387350 |
| 9 | QUOTE_PCRS_ECC_before | 38327090 |
| 10 | DPE_ECC_GET_PROFILE | 38375977 |
| 11 | DPE_ECC_CERTIFY_KEY_before | 42659941 |
| 12 | STASH_MEASUREMENT | 42720549 |
| 13 | QUOTE_PCRS_ECC_after | 43660293 |
| 14 | DPE_ECC_CERTIFY_KEY_after | 47956275 |
| 15 | DPE_ECC_GET_CERT_CHAIN_0 | 48027708 |
| 16 | DPE_ECC_GET_CERT_CHAIN_2048 | 48097509 |
| 17 | DPE_MLDSA_GET_PROFILE | 48765037 |
| 18 | DPE_MLDSA_CERTIFY_KEY_after | 50097743 |
| 19 | DPE_MLDSA_GET_CERT_CHAIN_0 | 50786403 |
| 20 | DPE_MLDSA_GET_CERT_CHAIN_2048 | 51475876 |
| 21 | DPE_MLDSA_GET_CERT_CHAIN_4096 | 52164729 |
| 22 | DPE_MLDSA_GET_CERT_CHAIN_6144 | 52853790 |
| 23 | DPE_MLDSA_GET_CERT_CHAIN_8192 | 53543065 |
| 24 | DPE_MLDSA_GET_CERT_CHAIN_10240 | 54232129 |
| 25 | DPE_MLDSA_GET_CERT_CHAIN_12288 | 54921401 |
| 26 | DPE_MLDSA_GET_CERT_CHAIN_14336 | 55610261 |
| 27 | DPE_MLDSA_GET_CERT_CHAIN_16384 | 56299523 |
| 28 | DPE_MLDSA_GET_CERT_CHAIN_18432 | 56988580 |
| 29 | DPE_MLDSA_GET_CERT_CHAIN_20480 | 57677645 |
| 30 | DPE_MLDSA_GET_CERT_CHAIN_22528 | 58366098 |
| 31 | QUOTE_PCRS_MLDSA_after | 58932857 |
| 32 | GET_IDEV_ECC384_CERT | 58991424 |
| 33 | GET_IDEV_MLDSA87_CERT | 59240360 |

Longest mailbox commands by cycle count were the two ECC `CertifyKey` calls (~4.28 M cycles before the stash, ~4.30 M after) and ML-DSA `CertifyKey` (~1.33 M cycles). `STASH_MEASUREMENT` itself completed at cycle 42720549.

### Byte compare (`python3 attest/analyze.py attest_ref/rtl attest_ref/emu`)

Every DER certificate is **byte-identical** between Step A and Step B: IDevID, LDevID, FMC Alias, RT Alias, DPE leaf before/after, and each DPE `GetCertificateChain` chunk, for both ECC P-384 and ML-DSA-87. The corresponding raw mailbox `resp_*.bin` files match as well, except the three `QUOTE_PCRS` responses:

| File | Identical | Differs |
|---|---|---|
| `resp_009_QUOTE_PCRS_ECC_before.bin` | 32 PCRs, nonce, reset counters | checksum, digest (48 B), ECC signature (r‖s) |
| `resp_013_QUOTE_PCRS_ECC_after.bin` | 32 PCRs, nonce, reset counters | checksum, digest (48 B), ECC signature (r‖s) |
| `resp_031_QUOTE_PCRS_MLDSA_after.bin` | 32 PCRs, nonce, reset counters | checksum, digest (64 B), ML-DSA signature |

`resp_*.done` files are not compared: the RTL TB writes the completion cycle; the emulator writes `emu`.

Chain verification on the RTL artefacts is the same as §6: every ECC and ML-DSA-87 link verifies, and the full chain to the TEST mfg CA verifies strictly (no `-ignore_critical`). DPE `GetCertificateChain` matches the mailbox certs 3/3 for both algorithms. PCR31 after the stash is the expected `SHA-384(0^48 ‖ M)` = `bbd59944…72a1a2` on both sides, and that measurement appears as MultiTcbInfo entry 2 (`type='NIOS'`, `svn=1`) in the post-stash DPE leaves only.

Quote signatures **verify with the FMC Alias** public key (IDevID, LDevID, and RT Alias do not), on both ECC quotes and the ML-DSA quote — same as Step A. `analyze.py`'s digest recomputation `SHA-512(PCR0‖…‖PCR31‖bswap32(nonce))` (ECC: first 48 B; ML-DSA: byte-reversed 64 B) matches the emulator quotes and does **not** match the digest field returned by RTL, even though the 32 PCR values and the nonce are byte-identical. The RTL quote is still a valid signature by the FMC Alias over the digest that RTL reported.

**Root cause (resolved Nov 11, 2026):** the emulator and RTL disagree on the order in which the 8 `SHA512_GEN_PCR_HASH_NONCE` registers are fed into the hash.

- RTL, `caliptra-rtl/src/pcrvault/rtl/pv_gen_hash.sv` (state `GEN_HASH_NONCE`): `block_wr_data = nonce[NONCE_LEN_DWORD-1-nonce_offset_i]`, i.e. NONCE[7] first, NONCE[0] last. Seen from the request bytes this is the nonce with its eight 4-byte chunks in reverse order, each chunk's bytes unchanged.
- Emulator, `caliptra-sw/sw-emulator/lib/periph/src/hash_sha512.rs` (`pcr_hash_op_complete`): `update_bytes(pcr_gen_hash_nonce.as_bytes())`, i.e. NONCE[0] first, each word byte-swapped, which is the `bswap32(nonce)` form above.

A brute-force over PCR and nonce byte orders finds exactly one match per quote: RTL digest = SHA-512(PCR0‖…‖PCR31‖dword_reverse(nonce)), first 48 B for ECC and byte-reversed 64 B for ML-DSA, on all three RTL quotes. PCR handling is identical on both sides. `analyze.py` now reports `digest_matches_emu_model` and `digest_matches_rtl_model` separately.

Implication: a verifier for quotes from real hardware (FPGA or silicon) must use the RTL order. A verifier built and tested only against the emulator will reject genuine hardware quotes. This looks like an emulator fidelity bug in `caliptra-sw` (rtl `4937026`, sw `a4b6bbf`) and could be reported upstream.


## 8. How to reproduce

All commands run from `caliptra2x/sim_2x/` of a clone with `external/caliptra-rtl-2x` fetched. The step-by-step
version, with expected log lines, is in [`docs/caliptra-2x/SIMULATION_2X.md` §8](../../docs/caliptra-2x/SIMULATION_2X.md).

```bash
# Step B — RTL (Verilator >= 5.040), detached. Boot ≈ 36.6 M cycles, attestation ≈ 22.7 M more.
rm -rf attest_out/rtl && mkdir -p attest_out/rtl
LOG=attest_run.log nohup setsid ./run_nios2x_top_fw.sh +test=attest +max_cycles=4000000000 > attest_run.out 2>&1 &
nohup setsid python3 attest/attest_driver.py attest_out/rtl > attest_out/rtl_driver.log 2>&1 &
# when 'TB_NIOS2X PASS' is in attest_run.log:
python3 attest/analyze.py attest_out/rtl attest_ref/emu      # decode + verify + byte-compare -> ANALYZE PASS

# Step A — optional, caliptra-sw sw-emulator, same ROM/bundle/fuses/obf key/lifecycle (~25 s)
cp attest/emu/attest_emu.rs  $CALIPTRA_SW/hw-model/examples/
(cd $CALIPTRA_SW && cargo build --release -p caliptra-hw-model --example attest_emu)   # needs `make` in PATH (openssl-src)
rm -rf attest_out/emu && mkdir -p attest_out/emu
$CALIPTRA_SW/target/release/examples/attest_emu ../fw_2x/caliptra-rom.bin ../fw_2x/caliptra-fw-bundle.bin \
    ../fw_2x/fuse_image_2x.hex attest_out/emu &
python3 attest/attest_driver.py attest_out/emu
python3 attest/analyze.py attest_out/emu
```

The emulator is given: UDS/FE/vendor-hash/PQC/stepping/SoC-manifest-max-SVN from `fuse_image_2x.hex`, the owner PK
hash written to `CPTRA_OWNER_PK_HASH` + `LOCK` before boot (as `soc_fuse_ctrl2x` does), `cptra_obf_key` = the RTL
`STUDY_PROD_MIMIC_OBF_KEY` (word *i* = bits [32i+31:32i]), CSR HMAC key `{16{5A3C96E1}}`, security state
Production + debug locked, mailbox AxUSER 1, external TRNG.

**TEST CA and keys.** `attest/testca/` holds the TEST mfg CA certificates and the IDevID TBS/certificates cached by
IDevID public key. With the committed ROM, bundle and fuse image the IDevID key is the same, so the cache hits and
**no CA private key is needed**. The CA private keys (`test_mfg_ca_{ecc,mldsa}.key`) are never committed
(`*.key` is git-ignored). If you change UDS/FE, the driver stops with a message; run it with
`ATTEST_CA_DIR=$PWD/attest_out/testca` (an empty directory) and it creates a new local TEST CA with OpenSSL ≥ 3.5
(`genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-384` and `genpkey -algorithm ML-DSA-87`) and signs new IDevID
TBSs. Pass the same `ATTEST_CA_DIR` to `analyze.py`.

## 9. Files

| Path (under `caliptra2x/sim_2x/`) | Content |
|---|---|
| `attest/attest_driver.py` | backend-agnostic Nios-host mailbox client (requests, checksums, DPE, IDevID TBS) |
| `attest/analyze.py` | DER/TcbInfo decoder, chain + quote verification, emu-vs-RTL compare, `ANALYZE PASS/FAIL` |
| `attest/emu/attest_emu.rs` | caliptra-hw-model (sw-emulator) backend, same file protocol |
| `attest/testca/*.pem, idev_*` | TEST mfg CA certs + cached IDevID TBS/cert (private `*.key` not committed) |
| `tb_nios2x_top_fw.sv` | `+test=attest` (`mbox_cmd_from_file`, `attest_loop`), `+attest_dir=DIR` |
| `attest_ref/{emu,rtl}/*.der, *.pem, *.txt` | reference certificates (DER, PEM, text decode) |
| `attest_ref/{emu,rtl}/req_NNN.hex, resp_NNN.hex, resp_NNN_<name>.bin` | every raw mailbox request/response |
| `attest_ref/{emu,rtl}/attest_summary.json, analysis.json` | measurement, quotes, decoded certs, verification |
| `attest_ref/rtl_tb_run.log`, `attest_ref/rtl_driver.log`, `attest_ref/emu_*.log` | reference run logs |
| `attest_out/`, `attest_run.log`, `attest_run.out` | your own runs (git-ignored) |

## 10. Caveats / not verified

- All keys are test material: caliptra-sw public fake vendor/owner keys, STUDY UDS/FE/obf key, a local TEST mfg CA.
  The IDevID certificates prove the mechanism only; a product IDevID cert comes from the manufacturer's CA/HSM
  (normally via the Manufacturing-lifecycle IDevID CSR flow, not exercised here).
- The RTL TB's TRNG model returns Verilator `$urandom` words (fixed default seed), not the xorshift32 generator
  of the Nios C firmware; the emulator uses its own ETRNG source. TRNG only feeds SCA masking / IVs here: key
  derivation is deterministic, ECDSA uses HMAC-DRBG (RFC 6979-style) and ML-DSA uses `sign_rnd = 0`, which is why
  the certificates can match byte-for-byte.
- Runtime-stash only; ROM-time stash (pre-FIRMWARE_LOAD measurement log), warm reset (PCR reset counters / DPE
  persistence), `EXTEND_PCR`, `CERTIFY_KEY_EXTENDED`, DPE `Sign` and exported-CDI were not exercised.
- `FW_INFO.rom_sha256_digest` (`ab0aeddb…`) differs from `sha256sum caliptra-rom.bin`; not investigated.
- No waveforms (the TB still cannot capture them for this length of run).

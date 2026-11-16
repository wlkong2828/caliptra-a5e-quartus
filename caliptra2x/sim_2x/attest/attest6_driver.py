#!/usr/bin/env python3
"""Caliptra 2.x exercise 6 (Nios-host side): one end-to-end measured boot + remote attestation, following the user's
sequence diagram (SoC MCU/Host = our Nios V, Caliptra RoT, Verifier), with every step checked against fw-2.1.4:
  boot     Phase 1  Caliptra boot. The ROM-phase FIRMWARE_LOAD is done by the boot path (attest_emu / the TB Nios model)
                    before request 0. Checked: FW_INFO digests == bundle TOC, GET_PCR_LOG (ROM + FMC entries), PCR0-3
                    replay == QUOTE, EXTEND_PCR on PCR0-3 refused (RUNTIME_PCR_RESERVED).
  prov     IDevID provisioning (POPULATE_IDEV_*_CERT from the attest4 TEST vendor CA) so a verifier can chain to a root.
  soctcb   Phase 2  SoC TCB: the host hashes the bootloader, ECDSA384_SIGNATURE_VERIFY (host supplies key + SHA-384),
                    tampered / wrong-key negatives, then STASH_MEASUREMENT (DPE + PCR31).
  os       Phase 3  OS hand-off: ECDSA384 + MLDSA87 SIGNATURE_VERIFY of the kernel, DPE DeriveContext, DPE_TAG_TCI.
  user     Phase 4  EXTEND_PCR PCR8 with app / driver / config hashes. Host event log of every measurement.
  attest   Phase 5  fresh verifier nonce -> GET_PCR_LOG, QUOTE_PCRS_ECC384 / _MLDSA87, DPE GetCertificateChain,
                    CertifyKey, DPE Sign over a nonce-bound transcript -> attestation bundle.
  verify   an independent verifier (Python + OpenSSL only): nonce, quote digest recomputed (emulator and RTL nonce
           order), quote signature (FMC Alias = Caliptra's PCR signing key), cert chains to the TEST vendor CA, event-log
           replay of all 32 PCRs, reference values (golden manifest), DPE leaf TCB, DPE signature.
  neg      negatives the verifier must reject: replayed nonce, tampered event log, tampered quote, unknown PCR8
           measurement (real EXTEND_PCR + new quote), hidden PCR31 extend (EXTEND_PCR 31 is accepted by fw-2.1.4).
Same file protocol / mailbox framing as attest5_driver.py. Needs the attest5 build of attest_emu (no rebuild for attest6).
Usage: attest6_driver.py DIR [TB_LOG]     (TB_LOG = the RTL run log: RTL mode, per-command cycles from the log)
Generated per run in DIR (gitignored, never committed): the TEST SoC signing keys soc_signing_ecc384.key /
soc_signing_mldsa87.key. TEST material only.
"""
import hashlib, json, os, re, struct, subprocess, sys, tempfile, time

DIR = os.path.abspath(sys.argv[1]); os.makedirs(DIR, exist_ok=True)
TB_LOG = sys.argv[2] if len(sys.argv) > 2 else None
for _f in os.listdir(DIR):
    if re.match(r"(req|resp)_\d{3}", _f) or _f == ".req.tmp": os.remove(os.path.join(DIR, _f))
LOG = []
T_START = time.time()

def cmd_id(s): return struct.unpack(">I", s.encode())[0]
CMD = {k: cmd_id(k) for k in ("INFO", "CERF", "CERR", "CMCF", "CMCR", "PCRQ", "PCRM", "PCRE", "PCRR", "PLOG",
                              "GTGD", "CKEX", "CKXM", "CKCH", "ALTN", "RCTX", "DSBL", "DPEC", "DPEM",
                              "IDEI", "IDMI", "IDEC", "IDMC", "LDEV", "LDMC", "IDEP", "IDMP", "ATMN", "ATVM", "ATSH",
                              "SWEE", "SWML", "RVCH", "MEAS")}
ERR = {0x000E0009: "RUNTIME_MAILBOX_INVALID_PARAMS", 0x000E003C: "RUNTIME_PCR_RESERVED",
       0x000E003D: "RUNTIME_PCR_INVALID_INDEX", 0x000E0036: "RUNTIME_INCREMENT_PCR_RESET_MAX_REACHED",
       0x000E001E: "RUNTIME_TAGGING_FAILURE", 0x000E001F: "RUNTIME_DUPLICATE_TAG",
       0x000E0020: "RUNTIME_CONTEXT_ALREADY_TAGGED", 0x000E003E: "RUNTIME_DMTF_DEVICE_INFO_VALIDATION_FAILED",
       0x000E0040: "RUNTIME_CERTIFY_KEY_EXTENDED_FAILED", 0x000E0027: "RUNTIME_DPE_COMMAND_DESERIALIZATION_FAILED",
       0x000E0070: "RUNTIME_REALLOCATE_DPE_CONTEXTS_PL0_LESS_THAN_MIN",
       0x000E0071: "RUNTIME_REALLOCATE_DPE_CONTEXTS_PL0_GREATER_THAN_MAX",
       0x000E0072: "RUNTIME_REALLOCATE_DPE_CONTEXTS_PL0_LESS_THAN_USED",
       0x000E0073: "RUNTIME_REALLOCATE_DPE_CONTEXTS_PL1_LESS_THAN_USED",
       0x000E0037: "RUNTIME_PL0_USED_DPE_CONTEXT_THRESHOLD_REACHED",
       0x000E0016: "RUNTIME_INCORRECT_PAUSER_PRIVILEGE_LEVEL", 0x000E0003: "RUNTIME_INSUFFICIENT_MEMORY",
       0x000E0001: "RUNTIME_INTERNAL", 0x000E0002: "RUNTIME_UNIMPLEMENTED_COMMAND",
       0x000E001C: "RUNTIME_IDEV_CERT_POPULATION_FAILED", 0x000E0023: "RUNTIME_MAILBOX_API_REQUEST_DATA_LEN_TOO_LARGE",
       0x000E0045: "RUNTIME_INVALID_AUTH_MANIFEST_MARKER", 0x000E0046: "RUNTIME_AUTH_MANIFEST_PREAMBLE_SIZE_MISMATCH",
       0x000E0047: "RUNTIME_AUTH_MANIFEST_VENDOR_ECC_SIGNATURE_INVALID",
       0x000E0049: "RUNTIME_AUTH_MANIFEST_OWNER_ECC_SIGNATURE_INVALID", 0x000E004B: "RUNTIME_AUTH_MANIFEST_PREAMBLE_SIZE_LT_MIN",
       0x000E004C: "RUNTIME_AUTH_MANIFEST_IMAGE_METADATA_LIST_INVALID_SIZE",
       0x000E004D: "RUNTIME_AUTH_MANIFEST_IMAGE_METADATA_LIST_INVALID_ENTRY_COUNT",
       0x000E004E: "RUNTIME_AUTH_AND_STASH_UNSUPPORTED_IMAGE_SOURCE", 0x000E0050: "RUNTIME_AUTH_AND_STASH_MEASUREMENT_DPE_ERROR",
       0x000E0053: "RUNTIME_AUTH_MANIFEST_IMAGE_METADATA_LIST_DUPLICATE_FIRMWARE_ID",
       0x000E0057: "RUNTIME_SIGN_WITH_EXPORTED_ECDSA_KEY_DERIVIATION_FAILED",
       0x000E0060: "RUNTIME_REVOKE_EXPORTED_CDI_HANDLE_NOT_FOUND",
       0x000E0065: "RUNTIME_AUTH_MANIFEST_MLDSA_VENDOR_SIG_INVALID", 0x000E0068: "RUNTIME_AUTH_MANIFEST_MLDSA_OWNER_SIG_INVALID",
       0x000E008C: "RUNTIME_AUTH_MANIFEST_PQC_KEY_TYPE_MISMATCH",
       0x000E009C: "RUNTIME_SIGN_WITH_EXPORTED_MLDSA_KEY_DERIVIATION_FAILED",
       0x000E00B0: "RUNTIME_STASH_MEASUREMENT_RESERVED_FW_ID", 0x000E00B2: "RUNTIME_AUTH_MANIFEST_DEBUG_IMAGE_NOT_ALLOWED",
       0x000E00B3: "RUNTIME_AUTH_MANIFEST_INVALID_FLAGS", 0x000E00B4: "RUNTIME_AUTH_MANIFEST_UEID_MISMATCH",
       0x000B002C: "IMAGE_VERIFIER_ERR_FIRMWARE_SVN_GREATER_THAN_MAX_SUPPORTED",
       0x000B002E: "IMAGE_VERIFIER_ERR_FIRMWARE_SVN_LESS_THAN_FUSE"}

_ej = os.path.join(os.path.dirname(os.path.abspath(__file__)), "caliptra_errors_fw214.json")
if os.path.exists(_ej): ERR.update({int(k, 16): v for k, v in json.load(open(_ej)).items()})
# fw-2.1.4 quirk: api/src/mailbox.rs comments DPE_TAG_TCI as "TAGT" but the value is 0x54514754 = "TQGT".
# Sending "TAGT" (0x54414754) returns RUNTIME_UNIMPLEMENTED_COMMAND (0x000E0002).
CMD["TAGT"] = 0x54514754
def tt(s): return struct.unpack("<I", s.encode())[0]   # tci_type: stored/encoded little-endian (see 'RMTR' quirk)

def checksum(cmd, data):          # caliptra-sw api/src/checksum.rs
    return (-(sum(struct.pack("<I", cmd)) + sum(data))) & 0xFFFFFFFF

n_req = 0
LAST = {}
EMU = True     # attest5+ attest_emu build (extra resp lines); False on the RTL testbench (pass TB_LOG as argv[2])
def mbox(name, cmd, payload=b"", timeout_s=float(os.environ.get("CRYPTO_TIMEOUT_H", "72")) * 3600, raw=False, chk=None):
    """Send one mailbox command; return (status, resp bytes, fw_err_non_fatal).
    raw=True: payload goes to the mailbox as-is (FIRMWARE_LOAD / FIRMWARE_VERIFY: the image IS the payload, no header).
    chk: force a (wrong) request checksum. Extra attest_emu lines (fwfatal, boot, cycles, lockwait) land in LAST."""
    global n_req, LAST
    name = re.sub(r"[^A-Za-z0-9_]", "", name.replace(" ", "_").replace("-", "_"))
    data = payload if raw else struct.pack("<I", checksum(cmd, payload) if chk is None else chk) + payload
    words = [struct.unpack_from("<I", data + b"\0" * 3, i)[0] for i in range(0, len(data), 4)]
    tmp = os.path.join(DIR, ".req.tmp")
    with open(tmp, "w") as f:
        f.write("%08x\n%08x\n" % (cmd, len(data)) + "".join("%08x\n" % w for w in words))
    os.rename(tmp, os.path.join(DIR, "req_%03d.hex" % n_req))
    t0 = time.time(); done = os.path.join(DIR, "resp_%03d.done" % n_req)
    print("[attest6] req %03d %-34s cmd=%08x dlen=%d" % (n_req, name, cmd, len(data)), flush=True)
    while not os.path.exists(done):
        if time.time() - t0 > timeout_s: raise SystemExit("timeout waiting for " + done)
        time.sleep(0.05)
    time.sleep(0.05)
    lines = open(os.path.join(DIR, "resp_%03d.hex" % n_req)).read().split("\n")
    st, dlen = int(lines[0], 16), int(lines[1], 16)
    kv = {}
    for l in lines[2 + (dlen + 3) // 4:]:
        if " " in l: k_, v_ = l.split(" ", 1); kv[k_] = v_.strip()
    fwerr = int(kv["fwerr"], 16)
    resp = b"".join(struct.pack("<I", int(l, 16)) for l in lines[2:2 + (dlen + 3) // 4])[:dlen]
    ok_ck = None
    if st == 1 and dlen >= 8:
        ok_ck = struct.unpack_from("<I", resp)[0] == checksum(0, resp[4:])
    fatal = int(kv.get("fwfatal", "0"), 16)
    ent = dict(n=n_req, name=name, cmd="%08x" % cmd, req_len=len(data), status=st, resp_len=dlen,
               fw_err_non_fatal="%08x" % fwerr, fw_err_name=ERR.get(fwerr), fw_err_fatal="%08x" % fatal,
               fw_err_fatal_name=ERR.get(fatal), boot_status=kv.get("boot"), emu_cycles=int(kv.get("cycles", "-1")),
               lockwait_cycles=int(kv.get("lockwait", "-1")), flow_status=kv.get("flow"), post_cycles=int(kv.get("postcycles", "-1")),
               emu_err=kv.get("err"), resp_checksum_ok=ok_ck, wall_s=round(time.time() - t0, 2))
    LOG.append(ent); LAST = ent
    print("[attest6]   -> status=%d len=%d fwerr=%08x%s%s chk=%s boot=%s cyc=%s%s (%.2fs)" % (st, dlen, fwerr,
          " (%s)" % ERR[fwerr] if fwerr in ERR else "", " FATAL=%08x (%s)" % (fatal, ERR.get(fatal)) if fatal else "",
          ok_ck, kv.get("boot"), kv.get("cycles"), " lockwait=%s" % kv["lockwait"] if kv.get("lockwait", "0") != "0" else "",
          ent["wall_s"]), flush=True)
    global EMU
    if n_req == 0: EMU = "cycles" in kv
    if n_req == 0 and not EMU and not TB_LOG:
        raise SystemExit("this attest_emu is the pre-attest5 build (no 'cycles' line in resp_000.hex). Copy the updated "
                         "attest/emu/attest_emu.rs into $CALIPTRA_SW/hw-model/examples/ and rebuild it (SIMULATION_2X 13.3).")
    open(os.path.join(DIR, "resp_%03d_%s.bin" % (n_req, name)), "wb").write(resp)
    n_req += 1
    return st, resp, fwerr

OK = lambda st: st in (1, 2)      # DATA_READY / CMD_COMPLETE
RESULTS = []
def step(group, name, passed, detail=""):
    RESULTS.append(dict(group=group, step=name, result="PASS" if passed else "FAIL", detail=detail))
    print("[attest6] STEP %-7s %-66s %s %s" % (group, name, "PASS" if passed else "FAIL", detail), flush=True)
    return passed
def expect_fail(group, name, st, fe, code):
    """Rejected with `code` in CPTRA_FW_ERROR_NON_FATAL (or FATAL, e.g. after SHUTDOWN)."""
    fat = int(LAST.get("fw_err_fatal", "0"), 16)
    return step(group, name + " (expect reject %08x %s)" % (code, ERR.get(code, "")), st == 3 and code in (fe, fat),
                "status=%d fwerr=%08x fatal=%08x" % (st, fe, fat))
def u32(*v): return struct.pack("<%dI" % len(v), *v)
def save(name, data): open(os.path.join(DIR, name), "wb").write(data)
def P(name): return os.path.join(DIR, name)
def osl(*a, inp=None):
    r = subprocess.run(["openssl", *a], capture_output=True, input=inp)
    return r.returncode, (r.stdout + r.stderr).decode(errors="replace")
def H384(*parts): return hashlib.sha384(b"".join(parts)).digest()
def T(label, n):                  # deterministic TEST vectors
    out = b""
    while len(out) < n: out += hashlib.sha512(("A5E attest6 TEST " + label).encode() + struct.pack(">I", len(out) // 64)).digest()
    return out[:n]
summary = dict(fw="caliptra-sw fw-2.1.4 (dd1e79d), caliptra-dpe f2b7121", openssl=osl("version")[1].strip())

# ---------------- DER helpers (same parser as analyze.py) ----------------
OID = {"2.23.133.5.4.1": "tcg-dice-TcbInfo", "2.23.133.5.4.5": "tcg-dice-MultiTcbInfo", "2.23.133.5.4.4": "tcg-dice-Ueid",
       "2.5.29.17": "subjectAltName", "2.16.840.1.101.3.4.2.2": "sha384"}
def tlv(b, i):
    t = b[i]; l = b[i + 1]
    if l & 0x80: nb = l & 0x7f; L = int.from_bytes(b[i + 2:i + 2 + nb], "big"); h = 2 + nb
    else: L, h = l, 2
    return t, b[i + h:i + h + L], i + h + L
def children(v):
    i, out = 0, []
    while i < len(v): t, c, i = tlv(v, i); out.append((t, c))
    return out
def oid(v):
    a = [v[0] // 40, v[0] % 40]; x = 0
    for c in v[1:]:
        x = (x << 7) | (c & 0x7f)
        if not c & 0x80: a.append(x); x = 0
    return ".".join(map(str, a))
def tcbinfo(v):
    d = {}
    for t, c in children(v):
        n = t & 0x1f
        if n in (0, 1, 2): d[["vendor", "model", "version"][n]] = c.decode(errors="replace")
        elif n in (3, 4, 5): d[["svn", "layer", "index"][n - 3]] = int.from_bytes(c, "big")
        elif n == 6: d["fwids"] = [children(f)[1][1].hex() for _, f in children(c)]
        elif n == 9: d["type"] = c.decode(errors="replace"); d["type_hex"] = c.hex()
    return d
def cert_exts(der):
    tbs = children(tlv(der, 0)[1])[0][1]
    out = {}
    for t, c in children(tbs):
        if t == 0xa3:
            for _, e in children(children(c)[0][1]):
                parts = children(e); o = oid(parts[0][1]); val = parts[-1][1]
                crit = len(parts) == 3 and parts[1][1] == b"\xff"
                ent = dict(critical=crit, raw=val)
                if o == "2.23.133.5.4.5": ent["multi_tcb_info"] = [tcbinfo(c2) for _, c2 in children(tlv(val, 0)[1])]
                if o == "2.23.133.5.4.1": ent["tcb_info"] = tcbinfo(tlv(val, 0)[1])
                if o == "2.5.29.17":       # GeneralNames: otherName [0] { type-id OID, [0] EXPLICIT value }
                    names = []
                    for gt, gv in children(tlv(val, 0)[1]):
                        if gt == 0xa0:
                            ch = children(gv); inner = tlv(ch[1][1], 0)
                            names.append(dict(oid=oid(ch[0][1]), value_tag=inner[0], value=inner[1].decode(errors="replace")))
                        else: names.append(dict(tag=gt))
                    ent["san"] = names
                out[o] = ent
    return out
def der_len(n):
    if n < 0x80: return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big"); return bytes([0x80 | len(b)]) + b
def der_int(b): b = b.lstrip(b"\0") or b"\0"; b = (b"\0" + b) if b[0] & 0x80 else b; return bytes([2, len(b)]) + b
def ecdsa_sig_der(r, s): body = der_int(r) + der_int(s); return b"\x30" + der_len(len(body)) + body
def cert_spki_tail(pem, n):       # last n bytes of the SubjectPublicKeyInfo DER = raw public key
    rc, _ = osl("x509", "-in", pem, "-noout", "-pubkey", "-out", pem + ".pub.pem")
    rc, _ = osl("pkey", "-pubin", "-in", pem + ".pub.pem", "-outform", "DER", "-out", pem + ".pub.der")
    d = open(pem + ".pub.der", "rb").read(); os.remove(pem + ".pub.pem"); os.remove(pem + ".pub.der")
    return d[-n:]
def save_cert(name, der):
    save(name + ".der", der)
    rc, out = osl("x509", "-inform", "DER", "-in", P(name + ".der"), "-out", P(name + ".pem"))
    osl("x509", "-inform", "DER", "-in", P(name + ".der"), "-noout", "-text", "-out", P(name + ".txt"))
    return rc == 0
def verify_by(issuer, leaf):
    rc, out = osl("verify", "-partial_chain", "-CAfile", P(issuer + ".pem"), P(leaf + ".pem"))
    return rc == 0 and out.strip().endswith("OK"), out.strip().splitlines()[-1] if out.strip() else ""
def var_data(r): return r[12:12 + struct.unpack_from("<I", r, 8)[0]]

# ---------------- DPE helpers ----------------
DPE_MAGIC = cmd_id("DPEC"); DPER = cmd_id("DPER"); P384, MLDSA87 = 4, 5
X509, CSR = 0, 1
F_DMTF, F_AXI, F_USE_MLDSA = 1 << 31, 1 << 30, 1 << 31
DC_MAKE_DEFAULT, DC_INPUT_ALLOW_X509, DC_RETAIN_PARENT = 1 << 28, 1 << 25, 1 << 29
DEFAULT_HANDLE = b"\0" * 16
def ck_cmd(fmt, label, handle=DEFAULT_HANDLE, flags=0): return handle + u32(flags, fmt) + label
def dpe(name, cmd, body, profile=P384):
    pkt = struct.pack("<III", DPE_MAGIC, cmd, profile) + body
    pre = b"" if profile == P384 else u32(0, 0, 0, 0)
    st, r, fe = mbox(name, CMD["DPEC" if profile == P384 else "DPEM"], pre + u32(len(pkt)) + pkt)
    if st != 1: return st, None, fe, None
    d = var_data(r); magic, status, prof = struct.unpack_from("<III", d)
    return st, d, fe, status
def derive(name, data, tci_type, svn=0, flags=DC_MAKE_DEFAULT | DC_INPUT_ALLOW_X509):
    return dpe(name, 0x08, DEFAULT_HANDLE + data + u32(flags, tci_type, 0, svn))
def parse_ck(d, alg):
    """DPE CertifyKey response (with DPER header) -> (handle, pub, cert)."""
    magic, status, prof = struct.unpack_from("<III", d)
    h = d[12:28]; pl = 96 if alg == "ecc" else 2592
    pub = d[28:28 + pl]; n = struct.unpack_from("<I", d, 28 + pl)[0]
    return magic, status, h, pub, d[32 + pl:32 + pl + n]
def ckx(name, alg, fmt, label, flags=0, handle=DEFAULT_HANDLE):
    if alg == "ecc": st, r, fe = mbox(name, CMD["CKEX"], u32(flags) + ck_cmd(fmt, label, handle))
    else: st, r, fe = mbox(name, CMD["CKXM"], u32(flags) + u32(0, 0, 0) + ck_cmd(fmt, label, handle))
    if st != 1: return st, fe, None
    size = struct.unpack_from("<I", r, 8)[0]
    return st, fe, r[12:12 + size]

def quote(tag, which="ecc"):
    nonce = H384(b"attest6 nonce " + tag.encode())[:32]
    st, r, fe = mbox("QUOTE_PCRS_%s_%s" % (which.upper(), tag), CMD["PCRQ" if which == "ecc" else "PCRM"], nonce)
    if st != 1: return dict(status=st, fwerr="%08x" % fe)
    off = 8; pcrs = [r[off + 48 * i: off + 48 * (i + 1)] for i in range(32)]; off += 48 * 32 + 32
    ctrs = list(struct.unpack_from("<32I", r, off)); off += 128
    dl = 48 if which == "ecc" else 64
    digest = r[off:off + dl]; sig = r[off + dl:]
    return dict(status=st, pcrs=pcrs, ctrs=ctrs, digest=digest, sig=sig, nonce=nonce)
def quote_sig_ok(q, which, signer):
    td = tempfile.mkdtemp(dir=DIR)
    open(td + "/d", "wb").write(q["digest"])
    open(td + "/s", "wb").write(ecdsa_sig_der(q["sig"][:48], q["sig"][48:96]) if which == "ecc" else q["sig"][:4627])
    rc, pub = osl("x509", "-in", P(signer + ".pem"), "-noout", "-pubkey"); open(td + "/k.pem", "w").write(pub)
    rc, out = osl("pkeyutl", "-verify", "-pubin", "-inkey", td + "/k.pem", "-in", td + "/d", "-sigfile", td + "/s")
    for f in os.listdir(td): os.remove(os.path.join(td, f))
    os.rmdir(td)
    return rc == 0



# ======================= helpers shared with attest4 =======================
import shutil
HERE = os.path.dirname(os.path.abspath(__file__))
FW2X = os.path.abspath(os.path.join(HERE, "..", "..", "fw_2x"))
CA_DIR = os.path.abspath(os.environ.get("ATTEST_CA_DIR", os.path.join(HERE, "testca")))
def mk(t, v): return bytes([t]) + der_len(len(v)) + v
def ecc_spki(x, y):
    return mk(0x30, mk(0x30, bytes.fromhex("06072a8648ce3d0201") + bytes.fromhex("06052b81040022")) + mk(0x03, b"\0\x04" + x + y))
def mldsa_spki(pk): return mk(0x30, mk(0x30, bytes.fromhex("0609608648016503040313")) + mk(0x03, b"\0" + pk))
def swap_words(b): return b"".join(b[i:i + 4][::-1] for i in range(0, len(b), 4))   # caliptra "hw format" <-> bytes
def pub_pem(name, alg, raw):
    save(name + ".der", ecc_spki(raw[:48], raw[48:96]) if alg == "ecc" else mldsa_spki(raw))
    rc, out = osl("pkey", "-pubin", "-inform", "DER", "-in", P(name + ".der"), "-out", P(name + ".pem"))
    return P(name + ".pem")
def v_ecdsa_msg(pem, msg, r, s, tag):
    save(tag + ".msg", msg); save(tag + ".sig.der", ecdsa_sig_der(r, s))
    rc, out = osl("dgst", "-sha384", "-verify", pem, "-signature", P(tag + ".sig.der"), P(tag + ".msg"))
    return rc == 0
def v_ecdsa_digest(pem, dig, r, s, tag):
    save(tag + ".digest", dig); save(tag + ".sig.der", ecdsa_sig_der(r, s))
    rc, out = osl("pkeyutl", "-verify", "-pubin", "-inkey", pem, "-in", P(tag + ".digest"), "-sigfile", P(tag + ".sig.der"))
    return rc == 0
def v_mldsa_msg(pem, msg, sig, tag):
    save(tag + ".msg", msg); save(tag + ".sig", sig)
    rc, out = osl("pkeyutl", "-verify", "-pubin", "-inkey", pem, "-rawin", "-in", P(tag + ".msg"), "-sigfile", P(tag + ".sig"))
    return rc == 0
def split_der(chain):
    i, out = 0, []
    while i < len(chain):
        t, v, nxt = tlv(chain, i); out.append(chain[i:nxt]); i = nxt
    return out
def dpe_chain(alg, tag):
    prof = P384 if alg == "ecc" else MLDSA87; chain = b""; off = 0
    while True:
        st, d, fe, ds = dpe("DPE_%s_GET_CERT_CHAIN_%s_%d" % (alg.upper(), tag, off), 0x10, u32(off, 2048), prof)
        if st != 1 or ds != 0: break
        sz = struct.unpack_from("<I", d, 12)[0]; chain += d[16:16 + sz]; off += sz
        if sz < 2048: break
    save("dpe_%s_chain_%s.bin" % (alg, tag), chain)
    certs = split_der(chain)
    for k, c in enumerate(certs): save_cert("dpe_%s_chain_%s_%d" % (alg, tag, k), c)
    return certs
def certify(alg, tag, label=None):
    prof = P384 if alg == "ecc" else MLDSA87
    st, d, fe, ds = dpe("DPE_%s_CERTIFY_KEY_%s" % (alg.upper(), tag), 0x09, ck_cmd(X509, label or LABEL), prof)
    if st != 1 or ds != 0: return dict(status=st, fwerr=fe, dpe=ds)
    magic, dst, h, pub, cert = parse_ck(d, alg)
    nm = "leaf_%s_%s" % (alg, tag); save_cert(nm, cert)
    ex = cert_exts(cert)
    mt = ex.get("2.23.133.5.4.5", {}).get("multi_tcb_info", [])
    return dict(status=st, fwerr=fe, dpe=ds, name=nm, cert=cert, pub=pub, exts=ex, tcb=mt)
def tcb_find(leaf, type_raw):
    return [t for t in leaf.get("tcb", []) if t.get("type_hex") == type_raw.hex()]
def tcb_types(leaf): return [t.get("type_hex") for t in leaf.get("tcb", [])]
def verify_chain(ca_pem, inter_names, leaf_name, tag):
    with open(P(tag + "_untrusted.pem"), "w") as f:
        for n in inter_names: f.write(open(P(n + ".pem")).read())
    rc, out = osl("verify", "-show_chain", "-CAfile", ca_pem, "-untrusted", P(tag + "_untrusted.pem"), P(leaf_name + ".pem"))
    open(P(tag + "_verify.txt"), "w").write(out)
    depth = len([l for l in out.splitlines() if l.startswith("depth=")])
    return rc == 0 and ": OK" in out, depth, out.strip().splitlines()[0] if out.strip() else ""
def pcr31(q): return q["pcrs"][31]
def rdcert(name): return open(P(name + ".der"), "rb").read()
# ---------------- command IDs used by attest5 (housekeeping) ----------------
CMD.update({k: cmd_id(k) for k in ("FPVR", "CAPS", "IME0", "IDCR", "IDMR", "FMCR", "FMDR", "AECR", "AMCR", "FWVR", "FWLD", "FPSD")})
# fw-2.1.4 quirk: SELF_TEST_START / SELF_TEST_GET_RESULTS are commented "FPST" / "FPGR" in api/src/mailbox.rs but the
# values are 0x46504C54 = "FPLT" and 0x46504C67 = "FPLg". Use the numbers.
CMD["FPST"], CMD["FPGR"] = 0x46504C54, 0x46504C67
E = {n: c for c, n in ERR.items()}          # name -> code
def code(n): return E[n]

BUNDLE = open(os.path.join(FW2X, "caliptra-fw-bundle.bin"), "rb").read()
MAN_SIZE = struct.unpack_from("<I", BUNDLE, 4)[0]
TOC = {}
for nm, off in (("fmc", 16748), ("rt", 16852)):
    TOC[nm] = dict(zip(("id", "type"), struct.unpack_from("<2I", BUNDLE, off)))
    TOC[nm].update(version=struct.unpack_from("<I", BUNDLE, off + 28)[0], load=struct.unpack_from("<I", BUNDLE, off + 40)[0],
                   offset=struct.unpack_from("<I", BUNDLE, off + 48)[0], size=struct.unpack_from("<I", BUNDLE, off + 52)[0],
                   digest=BUNDLE[off + 56:off + 104])
def img(nm): t = TOC[nm]; return BUNDLE[t["offset"]:t["offset"] + t["size"]]
summary["bundle"] = dict(size=len(BUNDLE), manifest_size=MAN_SIZE, sha384=H384(BUNDLE).hex(),
                         toc={k: dict(v, digest=v["digest"].hex()) for k, v in TOC.items()})

def fw_info(tag):
    st, r, fe = mbox("FW_INFO_" + tag, CMD["INFO"])
    if st != 1: return dict(status=st, fwerr=fe)
    f = dict(status=st, chk=LAST["resp_checksum_ok"])
    f["pl0_pauser"], f["fw_svn"], f["min_fw_svn"], f["cold_boot_fw_svn"], f["attestation_disabled"] = struct.unpack_from("<5I", r, 8)
    f["rom_rev"], f["fmc_rev"], f["rt_rev"] = r[28:48].hex(), r[48:68].hex(), r[68:88].hex()
    f["rom_sha256"], f["fmc_sha384"], f["rt_sha384"] = r[88:120], r[120:168], r[168:216]
    f["owner_pk_hash"], f["authman_sha384"] = r[216:264], r[264:312]
    f["most_recent_fw_error"] = struct.unpack_from("<I", r, 312)[0]
    return f
def same_info(a, b, keys=("fw_svn", "rom_rev", "fmc_rev", "rt_rev", "rom_sha256", "fmc_sha384", "rt_sha384", "owner_pk_hash")):
    return all(a.get(k) == b.get(k) for k in keys)

# ---------------- vendor CA / IDevID (same procedure and cache as attest4) ----------------
def ptlv(b, i):
    t, v, nxt = tlv(b, i); return t, nxt - len(v), len(v), nxt
def make_ca(alg):
    key, crt = os.path.join(CA_DIR, "test_mfg_ca_%s.key" % alg), os.path.join(CA_DIR, "test_mfg_ca_%s.pem" % alg)
    if os.path.exists(crt) and not os.path.exists(key):
        raise SystemExit("IDevID key not in %s and the TEST CA private key %s is not available (never committed). "
                         "Set ATTEST_CA_DIR to an empty directory to create a new local TEST CA." % (CA_DIR, key))
    if not os.path.exists(crt):
        os.makedirs(CA_DIR, exist_ok=True)
        subprocess.run(["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-384", "-out", key] if alg == "ecc"
                       else ["openssl", "genpkey", "-algorithm", "ML-DSA-87", "-out", key], check=True, capture_output=True)
        subprocess.run(["openssl", "req", "-x509", "-new", "-key", key, "-out", crt, "-days", "36500", "-subj",
                        "/O=TEST ONLY Nios-A5E Mfg/CN=TEST Mfg CA ECC" if alg == "ecc" else "/CN=CA",
                        "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign",
                        *(["-sha384"] if alg == "ecc" else [])], check=True, capture_output=True)
    return key, crt
def idev_cert(alg, spki_der, ldev_der):
    """Same procedure (and cache) as attest_driver.build_idev_tbs: subject = LDevID issuer DN, SKI = LDevID AKI."""
    tag = hashlib.sha256(spki_der).hexdigest()[:16]
    cache = os.path.join(CA_DIR, "idev_%s_%s" % (alg, tag))
    if not os.path.exists(cache + ".cert.der"):
        key, crt = make_ca(alg)
        open(cache + ".pub.der", "wb").write(spki_der)
        subprocess.run(["openssl", "pkey", "-pubin", "-inform", "DER", "-in", cache + ".pub.der", "-out", cache + ".pub.pem"], check=True)
        issuer = subprocess.run(["openssl", "x509", "-inform", "DER", "-in", ldev_der, "-noout", "-issuer", "-nameopt", "RFC2253"],
                                capture_output=True, text=True, check=True).stdout.strip()[len("issuer="):]
        txt = subprocess.run(["openssl", "x509", "-inform", "DER", "-in", ldev_der, "-noout", "-ext", "authorityKeyIdentifier"],
                             capture_output=True, text=True).stdout
        aki = [l.strip() for l in txt.splitlines() if ":" in l and "Authority" not in l][-1].replace("keyid:", "")
        ext = cache + ".ext.cnf"
        open(ext, "w").write("[v3]\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign\nsubjectKeyIdentifier=%s\n"
                             "authorityKeyIdentifier=keyid\n" % aki if alg == "ecc" else
                             "[v3]\nbasicConstraints=CA:TRUE\nsubjectKeyIdentifier=none\nauthorityKeyIdentifier=none\n")
        subprocess.run(["openssl", "x509", "-new", "-force_pubkey", cache + ".pub.pem", "-subj", "/" + "/".join(reversed(issuer.split(","))),
                        "-CA", crt, "-CAkey", key, "-extfile", ext, "-extensions", "v3", "-days", "36500" if alg == "ecc" else "3650",
                        "-set_serial", "0x" + (tag if alg == "ecc" else "01"), "-outform", "DER", "-out", cache + ".cert.der",
                        *(["-sha384"] if alg == "ecc" else [])], check=True, capture_output=True)
    c = open(cache + ".cert.der", "rb").read()
    _, v, L, _ = ptlv(c, 0); _, tv, tl, nxt = ptlv(c, v); tbs = c[v:nxt]
    _, av, al, nxt2 = ptlv(c, nxt); _, sv, sl, _ = ptlv(c, nxt2)
    return c, tbs, c[sv + 1:sv + sl], cache

# ======================= attest6 =======================
CMD.update({k: cmd_id(k) for k in ("ECV2", "MLV2", "IDEP", "IDMP", "IDEI", "IDMI")})
E = {n: c for c, n in ERR.items()}
def code(n): return E[n]
summary["test"] = "attest6: end-to-end measured boot (Caliptra boot, SoC TCB, OS hand-off, user mode) + remote attestation with an independent verifier"
LABEL = H384(b"attest6 certify-key label (DPE attestation key)")
FUSE = {}
for l in open(os.path.join(FW2X, "fuse_image_2x.hex")):
    v = int(l.strip(), 16); FUSE[(v >> 32) - 0x30000] = v & 0xFFFFFFFF
def fusew(off, n): return [FUSE.get(off + 4 * i, 0) for i in range(n)]
FLOW_READY_FOR_RT = 1 << 29
EVENT_LOG = []                     # the host's own event log (Caliptra does not log runtime STASH / EXTEND_PCR)
def log_event(kind, pcr, digest, desc, **kw):
    e = dict(seq=len(EVENT_LOG), kind=kind, pcr=pcr, digest=digest.hex(), desc=desc, req=n_req - 1, **kw)
    EVENT_LOG.append(e); return e

def quote_n(tag, nonce, which="ecc"):
    st, r, fe = mbox("QUOTE_PCRS_%s_%s" % (which.upper(), tag), CMD["PCRQ" if which == "ecc" else "PCRM"], nonce)
    if st != 1: return dict(status=st, fwerr="%08x" % fe)
    off = 8; pcrs = [r[off + 48 * i: off + 48 * (i + 1)] for i in range(32)]; off += 48 * 32
    qn = r[off:off + 32]; off += 32
    ctrs = list(struct.unpack_from("<32I", r, off)); off += 128
    dl = 48 if which == "ecc" else 64
    return dict(status=st, alg=which, pcrs=pcrs, ctrs=ctrs, nonce=qn, digest=r[off:off + dl], sig=r[off + dl:], req=n_req - 1)

PCR_LOG_IDS = {1: "DeviceStatus", 2: "VendorPubKeyInfoHash", 3: "OwnerPubKeyHash", 4: "FmcTci", 5: "StashMeasurement",
               6: "RtTci", 7: "FwImageManifest"}
PCR_LOG_LEN = {1: 18}
def parse_pcr_log(raw):
    out = []
    for i in range(0, len(raw) - 55, 56):
        eid, pids = struct.unpack_from("<H2xI", raw, i)
        if eid == 0: continue
        out.append(dict(id=eid, name=PCR_LOG_IDS.get(eid, "?"), pcr_ids=pids, pcrs=[b for b in range(32) if pids >> b & 1],
                        data=raw[i + 8:i + 8 + PCR_LOG_LEN.get(eid, 48)]))
    return out
def get_pcr_log(tag):
    st, r, fe = mbox("GET_PCR_LOG_" + tag, CMD["PLOG"])
    return st, (var_data(r) if st == 1 else b""), fe
DEV_STATUS_FIELDS = ("owner_pk_hash_in_fuses", "anti_rollback_disable", "vendor_ecc_revocation", "lms_revocation_0",
                     "lms_revocation_1", "lms_revocation_2", "lms_revocation_3", "vendor_mldsa_revocation", "fw_fuse_svn",
                     "soc_manifest_fuse_svn", "max_soc_manifest_fuse_svn", "pqc_key_type", "lifecycle", "debug_locked",
                     "cold_boot_fw_svn", "vendor_ecc_pk_index", "vendor_pqc_pk_index", "subsystem_mode")

def replay(caliptra_log, host_log):
    """Recompute all 32 PCRs from zero: Caliptra's own log (ROM/FMC) + the host event log (runtime)."""
    pc = [b"\0" * 48 for _ in range(32)]
    for e in caliptra_log:
        for i in e["pcrs"]: pc[i] = H384(pc[i], e["data"])
    for e in host_log:
        if e.get("pcr") is not None: pc[e["pcr"]] = H384(pc[e["pcr"]], bytes.fromhex(e["digest"]))
    return pc
def nonce_emu(n): return b"".join(n[i:i + 4][::-1] for i in range(0, 32, 4))      # emulator: NONCE[0] first (bswap32)
def nonce_rtl(n): return b"".join(n[i:i + 4] for i in range(28, -1, -4))           # RTL pv_gen_hash: NONCE[7] first
def quote_digest_order(q):
    pc = b"".join(q["pcrs"]); f = (lambda d: d[:48]) if q["alg"] == "ecc" else (lambda d: d[::-1])
    for nm, nf in (("emu", nonce_emu), ("rtl", nonce_rtl)):
        if f(hashlib.sha512(pc + nf(q["nonce"])).digest()) == q["digest"]: return nm
    return None

# ---------------- verifier (independent: only the bundle, the reference values and OpenSSL) ----------------
VDIR = os.path.join(DIR, "verifier"); os.makedirs(VDIR, exist_ok=True)
def vfile(tag, name, data):
    p = os.path.join(VDIR, tag + "_" + name); open(p, "wb" if isinstance(data, bytes) else "w").write(data); return p
def der2pem(tag, name, der):
    p = vfile(tag, name + ".der", der)
    subprocess.run(["openssl", "x509", "-inform", "DER", "-in", p, "-out", p[:-4] + ".pem"], capture_output=True)
    return p[:-4] + ".pem"
def transcript(nonce, q_ecc, q_mldsa):
    return b"A5E-ATTEST6 transcript v1" + nonce + q_ecc["digest"] + q_mldsa["digest"]
def verifier(bundle, expected_nonce, refs, tag):
    c = {}; why = []
    qe, qm = bundle["quote_ecc"], bundle["quote_mldsa"]
    # 1. freshness
    c["nonce: both quotes carry the verifier's nonce"] = qe["nonce"] == expected_nonce and qm["nonce"] == expected_nonce
    # 2. quote digests recomputed from the reported PCRs + nonce
    oe, om = quote_digest_order(qe), quote_digest_order(qm)
    c["quote digest == SHA-512(PCR0..31 || nonce) (ECC, ML-DSA)"] = oe is not None and om is not None
    # 3. certificate chains: TEST vendor CA -> IDevID -> LDevID -> FMC Alias (quote key) -> RT Alias -> DPE leaf
    for alg in ("ecc", "mldsa"):
        ch = bundle["dpe_chain_" + alg]; ca = vfile(tag, "vendor_ca_%s.pem" % alg, refs["vendor_ca_" + alg])
        pems = [der2pem(tag, "%s_chain_%d" % (alg, k), d) for k, d in enumerate(ch)]
        unt = vfile(tag, "%s_untrusted.pem" % alg, "".join(open(p).read() for p in pems[:-1]))
        r = subprocess.run(["openssl", "verify", "-CAfile", ca, "-untrusted", unt, pems[2]], capture_output=True, text=True)
        c["%s: quote signer FMC Alias chains to the vendor CA (IDevID, LDevID)" % alg.upper()] = r.returncode == 0
        unt2 = vfile(tag, "%s_untrusted_all.pem" % alg, "".join(open(p).read() for p in pems))
        leaf = der2pem(tag, "%s_leaf" % alg, bundle["dpe_leaf_" + alg])
        r = subprocess.run(["openssl", "verify", "-CAfile", ca, "-untrusted", unt2, leaf], capture_output=True, text=True)
        c["%s: DPE leaf chains to the vendor CA (6 certs)" % alg.upper()] = r.returncode == 0
        # 4. quote signature with the FMC Alias public key taken from the chain
        q = qe if alg == "ecc" else qm
        kp = vfile(tag, "%s_fmc_alias_pub.pem" % alg, subprocess.run(["openssl", "x509", "-in", pems[2], "-noout", "-pubkey"],
                                                                     capture_output=True, text=True).stdout)
        dg = vfile(tag, "%s_quote_digest.bin" % alg, q["digest"])
        sg = vfile(tag, "%s_quote_sig" % alg, ecdsa_sig_der(q["sig"][:48], q["sig"][48:96]) if alg == "ecc" else q["sig"][:4627])
        r = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", kp, "-in", dg, "-sigfile", sg], capture_output=True)
        c["%s: quote signature verifies with the FMC Alias key" % alg.upper()] = r.returncode == 0
        # 5. DPE signature over the transcript that the verifier builds itself (binds the leaf key to this nonce)
        lk = vfile(tag, "%s_leaf_pub.pem" % alg, subprocess.run(["openssl", "x509", "-in", leaf, "-noout", "-pubkey"],
                                                               capture_output=True, text=True).stdout)
        tr = vfile(tag, "transcript.bin", transcript(expected_nonce, qe, qm))
        if alg == "ecc":
            s = bundle["dpe_sig_ecc"]; sf = vfile(tag, "dpe_sig_ecc.der", ecdsa_sig_der(s[:48], s[48:96]))
            r = subprocess.run(["openssl", "dgst", "-sha384", "-verify", lk, "-signature", sf, tr], capture_output=True)
        else:
            sf = vfile(tag, "dpe_sig_mldsa.bin", bundle["dpe_sig_mldsa"][:4627])
            r = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", lk, "-rawin", "-in", tr, "-sigfile", sf], capture_output=True)
        c["%s: DPE Sign over (nonce || quote digests) verifies with the DPE leaf key" % alg.upper()] = r.returncode == 0
        # 6. DPE leaf TCB: the stashed bootloader and the OS context are in the leaf's MultiTcbInfo
        fw = [f for t in cert_exts(bundle["dpe_leaf_" + alg]).get("2.23.133.5.4.5", {}).get("multi_tcb_info", []) for f in t.get("fwids", [])]
        c["%s: DPE leaf TCB has the reference bootloader and OS measurements" % alg.upper()] = refs["bl"].hex() in fw and refs["os"].hex() in fw
    # 7. event-log replay: Caliptra's log (PCR0-3) + host log (PCR8, PCR31) must give every quoted PCR
    clog = parse_pcr_log(bundle["caliptra_pcr_log"])
    exp = replay(clog, bundle["event_log"])
    mism = [i for i in range(32) if exp[i] != qe["pcrs"][i] or qe["pcrs"][i] != qm["pcrs"][i]]
    c["replay of Caliptra log + host event log == all 32 quoted PCRs"] = not mism
    if mism: why.append("PCRs not explained by the logs: %s" % mism)
    # 8. reference values (golden manifest): Caliptra's own TCB and every host-logged measurement must be known
    ids = {e["name"]: e["data"] for e in clog}
    c["Caliptra TCB: FMC / RT digests, vendor and owner key hashes == reference"] = (
        ids.get("FmcTci") == refs["fmc_tci"] and ids.get("RtTci") == refs["rt_tci"] and
        ids.get("VendorPubKeyInfoHash") == refs["vendor_pk_hash"] and ids.get("OwnerPubKeyHash") == refs["owner_pk_hash"])
    ds = dict(zip(DEV_STATUS_FIELDS, ids.get("DeviceStatus", b"")))
    c["device status: production lifecycle, debug locked"] = ds.get("lifecycle") == refs["lifecycle"] and ds.get("debug_locked") == 1
    unknown = [e["desc"] for e in bundle["event_log"] if e["digest"] not in refs["golden"]]
    c["every host-logged measurement is in the reference manifest"] = not unknown
    if unknown: why.append("unknown measurements: %s" % unknown)
    c["PCR8 == golden PCR8 (app, driver, config)"] = qe["pcrs"][8] == refs["pcr8"]
    c["PCR31 == golden PCR31 (bootloader stash)"] = qe["pcrs"][31] == refs["pcr31"]
    c["PCR reset counters all 0"] = not any(qe["ctrs"])
    why += [k for k, v in c.items() if not v and k not in ("replay of Caliptra log + host event log == all 32 quoted PCRs",
                                                             "every host-logged measurement is in the reference manifest")]
    ok = all(c.values())
    res = dict(tag=tag, verdict="ACCEPT" if ok else "REJECT", checks=c, reasons=why, digest_order=dict(ecc=oe, mldsa=om))
    json.dump(res, open(os.path.join(VDIR, tag + "_result.json"), "w"), indent=1)
    print("[attest6] VERIFIER %-28s %s %s" % (tag, res["verdict"], "; ".join(why)[:200]), flush=True)
    return res

# ======================= Phase 1: Caliptra boot (ROM FIRMWARE_LOAD done by the boot path) =======================
G = "boot"
INFO0 = fw_info("start")
step(G, "runtime answers after the ROM-phase FIRMWARE_LOAD (FW_INFO ok, checksum valid, PL0 = Nios)",
     INFO0.get("status") == 1 and INFO0["chk"] and INFO0["pl0_pauser"] == 1, "fw_svn=%s" % INFO0.get("fw_svn"))
if EMU:
    fl = int(LAST.get("flow_status") or "0", 16)
    step(G, "CPTRA_FLOW_STATUS.ready_for_runtime (bit 29) set = RDY_FOR_RT", fl & FLOW_READY_FOR_RT != 0, "flow=%08x" % fl)
fmc_d, rt_d = TOC["fmc"]["digest"], TOC["rt"]["digest"]
step(G, "FW_INFO FMC / RT SHA-384 == bundle TOC digests == SHA-384 of the loaded images",
     INFO0.get("fmc_sha384") in (fmc_d, swap_words(fmc_d)) and INFO0.get("rt_sha384") in (rt_d, swap_words(rt_d)) and
     H384(img("fmc")) in (fmc_d, swap_words(fmc_d)) and H384(img("rt")) in (rt_d, swap_words(rt_d)))
st, PLOG0, fe = get_pcr_log("boot")
CLOG0 = parse_pcr_log(PLOG0)
save("caliptra_pcr_log_boot.bin", PLOG0)
summary["caliptra_pcr_log_boot"] = [dict(e, data=e["data"].hex()) for e in CLOG0]
step(G, "GET_PCR_LOG (PLOG) exists in fw-2.1.4: %d B = 17 x 56-B entries, %d used" % (len(PLOG0), len(CLOG0)),
     st == 1 and len(PLOG0) == 17 * 56 and len(CLOG0) >= 5, "ids=%s" % [e["name"] for e in CLOG0])
names = [(e["name"], e["pcrs"]) for e in CLOG0]
step(G, "ROM logged DeviceStatus, VendorPubKeyInfoHash, OwnerPubKeyHash, FmcTci into PCR0+PCR1; FMC logged RtTci into PCR2+PCR3",
     names[:5] == [("DeviceStatus", [0, 1]), ("VendorPubKeyInfoHash", [0, 1]), ("OwnerPubKeyHash", [0, 1]), ("FmcTci", [0, 1]), ("RtTci", [2, 3])],
     str(names))
L = {e["name"]: e["data"] for e in CLOG0}
REF_FMC, REF_RT = H384(img("fmc")), H384(img("rt"))       # reference = SHA-384 of the released FMC / runtime images
summary["tci_vs_toc"] = dict(fmc="toc" if L.get("FmcTci") == fmc_d else "toc word-swapped" if L.get("FmcTci") == swap_words(fmc_d) else "none",
                             rt="toc" if L.get("RtTci") == rt_d else "toc word-swapped" if L.get("RtTci") == swap_words(rt_d) else "none")
step(G, "log FmcTci == SHA-384(FMC image), RtTci == SHA-384(runtime image) (what the ROM/FMC loaded and measured)",
     L.get("FmcTci") == REF_FMC and L.get("RtTci") == REF_RT, "vs bundle TOC digest: %s" % summary["tci_vs_toc"])
VEND_HASH = H384(BUNDLE[12:1748]); OWN_HASH = H384(BUNDLE[9168:11856])
step(G, "log VendorPubKeyInfoHash == fuse = SHA-384(bundle vendor key descriptors); OwnerPubKeyHash == SHA-384(owner keys)",
     L.get("VendorPubKeyInfoHash") == VEND_HASH and L.get("OwnerPubKeyHash") == OWN_HASH and
     fusew(0x260, 12) == list(struct.unpack(">12I", VEND_HASH)))
DS = dict(zip(DEV_STATUS_FIELDS, L.get("DeviceStatus", b"")))
summary["device_status"] = DS
step(G, "DeviceStatus decoded: lifecycle %s, debug_locked %s, pqc_key_type %s, subsystem_mode %s (passive)" % (
     DS.get("lifecycle"), DS.get("debug_locked"), DS.get("pqc_key_type"), DS.get("subsystem_mode")),
     DS.get("debug_locked") == 1 and DS.get("subsystem_mode") == 0 and DS.get("pqc_key_type") == 1)
NB = os.urandom(32)
QB = quote_n("boot", NB)
exp0 = replay(CLOG0, [])
step(G, "QUOTE at boot: PCR0..3 == replay of GET_PCR_LOG; PCR4..31 all zero",
     QB.get("status") == 1 and QB["pcrs"][:4] == exp0[:4] and all(p == b"\0" * 48 for p in QB["pcrs"][4:]),
     "nonzero=%s" % [i for i in range(32) if QB.get("pcrs") and any(QB["pcrs"][i])])
step(G, "PCR0 (FMC current) == PCR1 (FMC journey) and PCR2 (RT current) == PCR3 (RT journey) on a cold boot",
     QB["pcrs"][0] == QB["pcrs"][1] and QB["pcrs"][2] == QB["pcrs"][3])
D_LOCK = H384(b"attest6 try to extend a Caliptra-owned PCR")
for idx in (0, 1, 2, 3):
    st, r, fe = mbox("EXTEND_PCR_%d_reserved" % idx, CMD["PCRE"], u32(idx) + D_LOCK)
    expect_fail(G, "EXTEND_PCR PCR%d refused (Caliptra-owned)" % idx, st, fe, code("RUNTIME_PCR_RESERVED"))
summary["pcr_boot"] = [p.hex() for p in QB["pcrs"][:4]]

# ======================= provisioning: IDevID certificate (as attest4) =======================
G = "prov"
for nm, c in (("ldevid_ecc384", "LDEV"), ("fmc_alias_ecc384", "CERF"), ("rt_alias_ecc384", "CERR"),
              ("ldevid_mldsa87", "LDMC"), ("fmc_alias_mldsa87", "CMCF"), ("rt_alias_mldsa87", "CMCR")):
    st, r, fe = mbox("GET_" + nm.upper() + "_CERT", CMD[c])
    step(G, "%s certificate read" % nm, st == 1 and save_cert(nm, var_data(r)), "%d B" % len(var_data(r)) if st == 1 else "status=%d" % st)
st, r, fe = mbox("GET_IDEV_ECC384_INFO", CMD["IDEI"]); IDEV_E_PUB = r[8:104]
st2, r2, fe2 = mbox("GET_IDEV_MLDSA87_INFO", CMD["IDMI"]); IDEV_M_PUB = r2[8:8 + 2592]
IDEV = {}
for alg, pub, n in (("ecc", IDEV_E_PUB, 96), ("mldsa", IDEV_M_PUB, 2592)):
    sfx = "ecc384" if alg == "ecc" else "mldsa87"
    spki = ecc_spki(pub[:48], pub[48:]) if alg == "ecc" else mldsa_spki(pub)
    cert, tbs, sig, cache = idev_cert(alg, spki, P("ldevid_%s.der" % sfx))
    shutil.copy(os.path.join(CA_DIR, "test_mfg_ca_%s.pem" % alg), P("vendor_ca_%s.pem" % sfx))
    save_cert("idevid_%s_vendor_ca" % sfx, cert); IDEV[alg] = cert
    ok, msg = verify_by("vendor_ca_" + sfx, "idevid_%s_vendor_ca" % sfx)
    step(G, "TEST vendor CA -> IDevID %s (cached %s), key == GET_IDEV_%s_INFO" % (alg.upper(), os.path.basename(cache), sfx.upper()),
         ok and cert_spki_tail(P("idevid_%s_vendor_ca.pem" % sfx), n) == pub, msg)
st, r, fe = mbox("POPULATE_IDEV_ECC384_CERT", CMD["IDEP"], u32(len(IDEV["ecc"])) + IDEV["ecc"])
step(G, "POPULATE_IDEV_ECC384_CERT", OK(st), "status=%d fwerr=%08x" % (st, fe))
st, r, fe = mbox("POPULATE_IDEV_MLDSA87_CERT", CMD["IDMP"], u32(len(IDEV["mldsa"])) + IDEV["mldsa"])
step(G, "POPULATE_IDEV_MLDSA87_CERT", OK(st), "status=%d fwerr=%08x" % (st, fe))

# ======================= Phase 2: SoC TCB boot (bootloader) =======================
G = "soctcb"
KEY_E, KEY_M = P("soc_signing_ecc384.key"), P("soc_signing_mldsa87.key")
KEY_X = P("attacker_ecc384.key")
for k, a in ((KEY_E, ["-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-384"]), (KEY_X, ["-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-384"]),
             (KEY_M, ["-algorithm", "ML-DSA-87"])):
    if not os.path.exists(k): subprocess.run(["openssl", "genpkey", *a, "-out", k], check=True, capture_output=True)
subprocess.run(["openssl", "pkey", "-in", KEY_E, "-pubout", "-out", P("soc_signing_ecc384.pub.pem")], check=True)
subprocess.run(["openssl", "pkey", "-in", KEY_M, "-pubout", "-out", P("soc_signing_mldsa87.pub.pem")], check=True)
_d = subprocess.run(["openssl", "pkey", "-in", KEY_E, "-pubout", "-outform", "DER"], capture_output=True).stdout
SOC_X, SOC_Y = _d[-96:-48], _d[-48:]
SOC_MPK = subprocess.run(["openssl", "pkey", "-in", KEY_M, "-pubout", "-outform", "DER"], capture_output=True).stdout[-2592:]
def ecdsa_rs(der):
    ch = children(tlv(der, 0)[1]); return [int.from_bytes(v, "big").to_bytes(48, "big") for _, v in ch]
def soc_sign(key, path, suffix=".sig.der"):
    sig = subprocess.run(["openssl", "dgst", "-sha384", "-sign", key, path], capture_output=True, check=True).stdout
    open(path + suffix, "wb").write(sig); return ecdsa_rs(sig)
def ecv2(tag, digest, r_, s_, x=None, y=None):
    return mbox("ECDSA384_SIG_VERIFY_" + tag, CMD["ECV2"], (x or SOC_X) + (y or SOC_Y) + r_ + s_ + digest)
BL = T("SoC bootloader (BL2) v2.3.0 for Agilex 5E", 96 * 1024); save("soc_bootloader.bin", BL)
OS_IMG = T("OS kernel / hypervisor image v6.12-a5e", 512 * 1024); save("os_kernel.bin", OS_IMG)
H_BL, H_OS = H384(BL), H384(OS_IMG)
bl_r, bl_s = soc_sign(KEY_E, P("soc_bootloader.bin"))
st, r, fe = ecv2("bootloader", H_BL, bl_r, bl_s)
BL_OK = step(G, "ECDSA384_SIGNATURE_VERIFY bootloader: host sends SoC pubkey + r,s + SHA-384(BL) -> accepted", OK(st), "status=%d fwerr=%08x" % (st, fe))
BL_T = bytearray(BL); BL_T[4096] ^= 0x40; BL_T = bytes(BL_T); save("soc_bootloader_tampered.bin", BL_T)
st, r, fe = ecv2("bootloader_tampered", H384(BL_T), bl_r, bl_s)
expect_fail(G, "ECDSA384_SIGNATURE_VERIFY tampered bootloader (1 bit) -> host must NOT stash", st, fe, code("RUNTIME_ECDSA_VERIFY_FAILED"))
xr, xs = soc_sign(KEY_X, P("soc_bootloader.bin"), ".attacker.sig.der")
st, r, fe = ecv2("bootloader_attacker_key", H_BL, xr, xs)
expect_fail(G, "ECDSA384_SIGNATURE_VERIFY bootloader signed by an attacker key (verified with the SoC key)", st, fe, code("RUNTIME_ECDSA_VERIFY_FAILED"))
_dx = subprocess.run(["openssl", "pkey", "-in", KEY_X, "-pubout", "-outform", "DER"], capture_output=True).stdout
st, r, fe = ecv2("bootloader_attacker_pubkey", H_BL, xr, xs, _dx[-96:-48], _dx[-48:])
step(G, "quirk: the same attacker signature PASSES if the host sends the attacker's public key (Caliptra holds no SoC key)",
     OK(st), "status=%d fwerr=%08x" % (st, fe))
q_pre = quote_n("before_stash", os.urandom(32))
CTX_BL = H384(b"bootloader context: loaded at 0x0, from QSPI slot A")
st, r, fe = mbox("STASH_MEASUREMENT_bootloader", CMD["MEAS"], b"SBL0" + H_BL + CTX_BL + u32(1))
dres = struct.unpack_from("<I", r, 8)[0] if st == 1 and len(r) >= 12 else None
step(G, "STASH_MEASUREMENT bootloader (fw_id 'SBL0', svn 1) -> dpe_result 0", st == 1 and dres == 0, "status=%d dpe_result=%s" % (st, dres))
log_event("STASH_MEASUREMENT", 31, H_BL, "SoC bootloader v2.3.0 (SBL0)", svn=1, tci_type="SBL0")
q_post = quote_n("after_stash", os.urandom(32))
step(G, "PCR31 == SHA-384(PCR31_old || SHA-384(BL)), no other PCR changed",
     q_post["pcrs"][31] == H384(q_pre["pcrs"][31], H_BL) and all(q_post["pcrs"][i] == q_pre["pcrs"][i] for i in range(31)))
st, PLOG1, fe = get_pcr_log("after_stash")
step(G, "runtime STASH_MEASUREMENT is NOT in GET_PCR_LOG (log unchanged; the host must log it itself)", st == 1 and PLOG1 == PLOG0)

# ======================= Phase 3: OS hand-off =======================
G = "os"
os_r, os_s = soc_sign(KEY_E, P("os_kernel.bin"))
st, r, fe = ecv2("os_kernel", H_OS, os_r, os_s)
step(G, "ECDSA384_SIGNATURE_VERIFY OS kernel -> accepted", OK(st), "status=%d fwerr=%08x" % (st, fe))
OS_T = bytearray(OS_IMG); OS_T[-1] ^= 1; OS_T = bytes(OS_T)
st, r, fe = ecv2("os_kernel_tampered", H384(OS_T), os_r, os_s)
expect_fail(G, "ECDSA384_SIGNATURE_VERIFY tampered OS kernel", st, fe, code("RUNTIME_ECDSA_VERIFY_FAILED"))
save("os_kernel.sha384", H_OS)
msig = subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", KEY_M, "-rawin", "-in", P("os_kernel.sha384")], capture_output=True).stdout
save("os_kernel.sha384.mldsa.sig", msig)
st, r, fe = mbox("MLDSA87_SIG_VERIFY_os_kernel", CMD["MLV2"], SOC_MPK + msig + b"\0" + u32(48) + H_OS)
step(G, "MLDSA87_SIGNATURE_VERIFY OS kernel digest (hybrid PQC signature, SoC ML-DSA-87 key) -> accepted", OK(st), "status=%d fwerr=%08x" % (st, fe))
st, r, fe = mbox("MLDSA87_SIG_VERIFY_os_kernel_tampered", CMD["MLV2"], SOC_MPK + msig + b"\0" + u32(48) + H384(OS_T))
expect_fail(G, "MLDSA87_SIGNATURE_VERIFY tampered OS kernel digest", st, fe, code("RUNTIME_MLDSA_VERIFY_FAILED"))
q_pre = quote_n("before_derive", os.urandom(32))
OS_TYPE = tt("OSK0")
st, d, fe, ds = derive("DPE_DERIVE_CONTEXT_os", H_OS, OS_TYPE, svn=2)
step(G, "INVOKE_DPE DeriveContext OS (MAKE_DEFAULT, type 'OSK0', svn 2, data = SHA-384(kernel))", st == 1 and ds == 0, "status=%d dpe=%s" % (st, ds))
log_event("DPE_DERIVE_CONTEXT", None, H_OS, "OS kernel v6.12-a5e (OSK0)", svn=2, tci_type="OSK0")
OS_TAG = tt("OS01")
st, r, fe = mbox("DPE_TAG_TCI_os", CMD["TAGT"], DEFAULT_HANDLE + u32(OS_TAG))
step(G, "DPE_TAG_TCI (0x54514754) OS context with tag 'OS01'", OK(st), "status=%d fwerr=%08x" % (st, fe))
log_event("DPE_TAG_TCI", None, H_OS, "tag OS01 -> OS context", tag="OS01")
st, r, fe = mbox("DPE_GET_TAGGED_TCI_os", CMD["GTGD"], u32(OS_TAG))
TCI = dict(cum=r[8:56], cur=r[56:104]) if st == 1 else {}
step(G, "DPE_GET_TAGGED_TCI 'OS01': tci_current == SHA-384(kernel), tci_cumulative == SHA-384(0^48 || it)",
     TCI.get("cur") == H_OS and TCI.get("cum") == H384(b"\0" * 48, H_OS))
q_post = quote_n("after_derive", os.urandom(32))
step(G, "DeriveContext / TAG change no PCR (DPE measurements live in the DPE tree, not in PCRs)", q_post["pcrs"] == q_pre["pcrs"])

# ======================= Phase 4: user mode =======================
G = "user"
APP = T("user-mode application v1.4", 32 * 1024); DRV = T("FPGA fabric driver v3.1", 24 * 1024); CFG = T("runtime config {secure_boot:1}", 2048)
for nm, b in (("app_v1.4.bin", APP), ("driver_v3.1.ko", DRV), ("config.json", CFG)): save(nm, b)
q_pre = quote_n("before_user", os.urandom(32))
for nm, b, desc in (("app", APP, "application v1.4"), ("driver", DRV, "FPGA driver v3.1"), ("config", CFG, "runtime config")):
    st, r, fe = mbox("EXTEND_PCR_8_" + nm, CMD["PCRE"], u32(8) + H384(b))
    step(G, "EXTEND_PCR PCR8 with SHA-384(%s)" % nm, OK(st), "status=%d fwerr=%08x" % (st, fe))
    log_event("EXTEND_PCR", 8, H384(b), desc)
q_post = quote_n("after_user", os.urandom(32))
GOLD_PCR8 = H384(H384(H384(b"\0" * 48, H384(APP)), H384(DRV)), H384(CFG))
step(G, "PCR8 == SHA-384(SHA-384(SHA-384(0 || app) || driver) || config); no other PCR changed",
     q_post["pcrs"][8] == GOLD_PCR8 and all(q_post["pcrs"][i] == q_pre["pcrs"][i] for i in range(32) if i != 8))
st, r, fe = mbox("EXTEND_PCR_32", CMD["PCRE"], u32(32) + H384(APP))
expect_fail(G, "EXTEND_PCR index 32 (allowed range is 4..31)", st, fe, code("RUNTIME_PCR_INVALID_INDEX"))
st, PLOG2, fe = get_pcr_log("after_user")
step(G, "EXTEND_PCR is NOT in GET_PCR_LOG either (only ROM/FMC entries)", st == 1 and PLOG2 == PLOG0)
save("host_event_log.json", json.dumps(EVENT_LOG, indent=1).encode())

# ======================= Phase 5: attestation =======================
G = "attest"
def collect(tag, nonce):
    """Host side of one attestation round: everything the verifier needs, for this nonce."""
    b = {}
    st, b["caliptra_pcr_log"], fe = get_pcr_log(tag)
    b["quote_ecc"] = quote_n(tag, nonce, "ecc"); b["quote_mldsa"] = quote_n(tag, nonce, "mldsa")
    for alg in ("ecc", "mldsa"):
        b["dpe_chain_" + alg] = dpe_chain(alg, tag)
        lf = certify(alg, tag); b["dpe_leaf_" + alg] = lf.get("cert")
        b["dpe_leaf_pub_" + alg] = lf.get("pub")
    tr = transcript(nonce, b["quote_ecc"], b["quote_mldsa"])
    st, d, fe, ds = dpe("DPE_ECC_SIGN_" + tag, 0x0A, DEFAULT_HANDLE + LABEL + u32(0) + H384(tr), P384)
    b["dpe_sig_ecc"] = d[28:124] if st == 1 and ds == 0 else b""; b["dpe_sign_ecc_status"] = (st, ds)
    # ML-DSA: the IS_RAW form (1096-B DPE command) exceeds INVOKE_DPE's 512-B data limit in fw-2.1.4, so the host
    # sends the 64-B external mu = SHAKE256(SHAKE256(pk, 64) || 0x00 || 0x00 || transcript, 64) (FIPS 204, empty context).
    mpk = b["dpe_leaf_pub_mldsa"] or b""
    mu = hashlib.shake_256(hashlib.shake_256(mpk).digest(64) + b"\0\0" + tr).digest(64)
    st, d, fe, ds = dpe("DPE_MLDSA_SIGN_MU_" + tag, 0x0A, DEFAULT_HANDLE + LABEL + u32(0) + mu, MLDSA87)
    b["dpe_sig_mldsa"] = d[28:28 + 4627] if st == 1 and ds == 0 else b""; b["dpe_sign_mldsa_status"] = (st, ds)
    b["event_log"] = json.loads(json.dumps(EVENT_LOG))
    b["nonce"] = nonce
    return b
def save_bundle(name, b):
    json.dump(b, open(P(name), "w"), indent=1, default=lambda o: o.hex() if isinstance(o, bytes) else str(o))
N1 = os.urandom(32)
summary["nonce_1"] = N1.hex()
B1 = collect("round1", N1)
save_bundle("attestation_bundle_round1.json", B1)
step(G, "GET_PCR_LOG + QUOTE_PCRS_ECC384 + QUOTE_PCRS_MLDSA87 with the verifier nonce", B1["quote_ecc"].get("status") == 1 and
     B1["quote_mldsa"].get("status") == 1 and len(B1["caliptra_pcr_log"]) == 952)
step(G, "ECC and ML-DSA quotes report the same PCRs and echo the nonce", B1["quote_ecc"]["pcrs"] == B1["quote_mldsa"]["pcrs"] and
     B1["quote_ecc"]["nonce"] == N1 == B1["quote_mldsa"]["nonce"])
step(G, "DPE GetCertificateChain: [IDevID, LDevID, FMC Alias, RT Alias] for ECC and ML-DSA",
     B1["dpe_chain_ecc"][0] == IDEV["ecc"] and B1["dpe_chain_mldsa"][0] == IDEV["mldsa"] and len(B1["dpe_chain_ecc"]) == 4 == len(B1["dpe_chain_mldsa"]))
step(G, "DPE CertifyKey ECC + ML-DSA (X.509 leaf, label = attestation key label)", bool(B1["dpe_leaf_ecc"]) and bool(B1["dpe_leaf_mldsa"]))
step(G, "DPE Sign ECC (P-384, digest = SHA-384(transcript)) and ML-DSA (external mu of the transcript)",
     len(B1["dpe_sig_ecc"]) == 96 and len(B1["dpe_sig_mldsa"]) == 4627, "ecc=%s mldsa=%s" % (B1["dpe_sign_ecc_status"], B1["dpe_sign_mldsa_status"]))
for alg in ("ecc", "mldsa"):
    fw = [(t.get("type"), t.get("svn"), t.get("fwids", [])) for t in cert_exts(B1["dpe_leaf_" + alg]).get("2.23.133.5.4.5", {}).get("multi_tcb_info", [])]
    summary["leaf_tcb_" + alg] = [dict(type=a, svn=b_, fwids=c_) for a, b_, c_ in fw]
    bl = [x for x in fw if H_BL.hex() in x[2]]; os_ = [x for x in fw if H_OS.hex() in x[2]]
    step(G, "%s DPE leaf MultiTcbInfo: %d TCBs; bootloader (type %s, svn %s) and OS (type %s, svn %s) present" % (
        alg.upper(), len(fw), bl and bl[0][0], bl and bl[0][1], os_ and os_[0][0], os_ and os_[0][1]), bool(bl) and bool(os_))
# quirk: the IS_RAW ML-DSA Sign (raw message up to 1024 B) does not fit INVOKE_DPE_MLDSA87 (data max 512 B)
TR_RAW = b"attest6 raw ML-DSA message"
st, d, fe, ds = dpe("DPE_MLDSA_SIGN_IS_RAW", 0x0A, DEFAULT_HANDLE + LABEL + u32(1) + u32(len(TR_RAW)) + TR_RAW.ljust(1024, b"\0"), MLDSA87)
summary["dpe_mldsa_sign_is_raw"] = dict(status=st, fwerr="%08x" % fe)
expect_fail(G, "quirk: DPE Sign ML-DSA IS_RAW form (1096-B DPE command > 512-B INVOKE_DPE limit)", st, fe, code("RUNTIME_INSUFFICIENT_MEMORY"))

# ======================= verifier =======================
G = "verify"
REFS = dict(vendor_ca_ecc=open(os.path.join(CA_DIR, "test_mfg_ca_ecc.pem")).read(),
            vendor_ca_mldsa=open(os.path.join(CA_DIR, "test_mfg_ca_mldsa.pem")).read(),
            fmc_tci=REF_FMC, rt_tci=REF_RT, vendor_pk_hash=VEND_HASH, owner_pk_hash=OWN_HASH, lifecycle=DS.get("lifecycle"),
            bl=H_BL, os=H_OS, pcr8=GOLD_PCR8, pcr31=H384(b"\0" * 48, H_BL),
            golden={H_BL.hex(): "bootloader v2.3.0", H_OS.hex(): "OS kernel v6.12-a5e", H384(APP).hex(): "app v1.4",
                    H384(DRV).hex(): "driver v3.1", H384(CFG).hex(): "config"})
summary["reference_values"] = {k: (v.hex() if isinstance(v, bytes) else v) for k, v in REFS.items() if not k.startswith("vendor_ca")}
V1 = verifier(B1, N1, REFS, "round1")
for k, v in V1["checks"].items(): step(G, "verifier: " + k, v)
step(G, "verifier verdict round 1: ACCEPT", V1["verdict"] == "ACCEPT", "; ".join(V1["reasons"]))
summary["quote_nonce_order"] = V1["digest_order"]
step(G, "quote digest nonce order = %s (emulator NONCE[0] first, RTL NONCE[7] first)" % V1["digest_order"],
     V1["digest_order"]["ecc"] == ("emu" if EMU else "rtl") == V1["digest_order"]["mldsa"])
summary["verifier_round1"] = V1

# ======================= negatives =======================
G = "neg"
import copy
def neg(name, b, nonce, expect_reason):
    v = verifier(b, nonce, REFS, name)
    failed = [k for k, x in v["checks"].items() if not x]
    step(G, "verifier REJECTS %s (fails: %s)" % (name, ", ".join(failed)[:150]), v["verdict"] == "REJECT" and any(expect_reason in k for k in failed))
    return v
N2 = os.urandom(32)
summary["neg"] = {}
summary["neg"]["replayed_nonce"] = neg("replay_old_bundle", B1, N2, "nonce")
B2 = collect("round2", N2)
V2 = verifier(B2, N2, REFS, "round2")
step(G, "the same device answering the NEW nonce N2 is ACCEPTED (freshness, not a stuck verifier)", V2["verdict"] == "ACCEPT", "; ".join(V2["reasons"]))
bt = copy.deepcopy(B2); [e for e in bt["event_log"] if e["desc"] == "FPGA driver v3.1"][0]["digest"] = H384(DRV + b"evil").hex()
summary["neg"]["tampered_event_log"] = neg("tampered_event_log", bt, N2, "replay")
bt = copy.deepcopy(B2); bt["event_log"] = [e for e in bt["event_log"] if e["desc"] != "runtime config"]
summary["neg"]["dropped_log_entry"] = neg("dropped_log_entry", bt, N2, "replay")
bt = copy.deepcopy(B2); qq = dict(bt["quote_ecc"]); qq["pcrs"] = list(qq["pcrs"]); qq["pcrs"][8] = GOLD_PCR8[:-1] + bytes([GOLD_PCR8[-1] ^ 1]); bt["quote_ecc"] = qq
summary["neg"]["tampered_quote_pcr8"] = neg("tampered_quote_pcr8", bt, N2, "quote digest")
bt = copy.deepcopy(B2); bt["dpe_leaf_ecc"] = B2["dpe_leaf_ecc"][:-5] + bytes([B2["dpe_leaf_ecc"][-5] ^ 1]) + B2["dpe_leaf_ecc"][-4:]
summary["neg"]["tampered_dpe_leaf"] = neg("tampered_dpe_leaf", bt, N2, "DPE leaf chains")
# real device-side attack 1: an unknown driver measured into PCR8 (logged honestly) -> replay OK, policy fails
ROGUE = T("unsigned debug driver", 8192); save("rogue_driver.ko", ROGUE)
st, r, fe = mbox("EXTEND_PCR_8_rogue_driver", CMD["PCRE"], u32(8) + H384(ROGUE))
step(G, "EXTEND_PCR PCR8 with an unknown (rogue) driver hash", OK(st))
log_event("EXTEND_PCR", 8, H384(ROGUE), "unsigned debug driver")
N3 = os.urandom(32); B3 = collect("round3_rogue", N3)
v = neg("rogue_driver_in_pcr8", B3, N3, "PCR8 == golden")
step(G, "  ... with the honest log the replay still matches (the quote is genuine, the TCB is not trusted)",
     v["checks"]["replay of Caliptra log + host event log == all 32 quoted PCRs"])
summary["neg"]["rogue_driver_in_pcr8"] = v
# real device-side attack 2: EXTEND_PCR 31 directly (not reserved!) and not logged -> replay mismatch on PCR31
st, r, fe = mbox("EXTEND_PCR_31_hidden", CMD["PCRE"], u32(31) + H384(b"hidden measurement"))
step(G, "quirk: EXTEND_PCR PCR31 is ACCEPTED (only PCR0-3 are reserved; PCR31 is shared with STASH_MEASUREMENT)", OK(st), "status=%d fwerr=%08x" % (st, fe))
N4 = os.urandom(32); B4 = collect("round4_hidden31", N4)
summary["neg"]["hidden_pcr31_extend"] = neg("hidden_pcr31_extend", B4, N4, "replay")
summary["event_log"] = EVENT_LOG
summary["final_pcrs"] = [p.hex() for p in B4["quote_ecc"]["pcrs"]]
# ---------------- end of stream ----------------
with open(os.path.join(DIR, ".req.tmp"), "w") as f: f.write("00000000\n00000000\n")
os.rename(os.path.join(DIR, ".req.tmp"), os.path.join(DIR, "req_%03d.hex" % n_req))
# ---------------- cycles per command from the RTL TB log ----------------
if TB_LOG and os.path.exists(TB_LOG):
    time.sleep(2)
    req, rsp = {}, {}
    for l in open(TB_LOG, errors="replace"):
        m = re.match(r"\[(\d+)\] ATTEST req (\d+) ", l)
        if m: req[int(m.group(2))] = int(m.group(1))
        m = re.match(r"\[(\d+)\] ATTEST resp (\d+) ", l)
        if m: rsp[int(m.group(2))] = int(m.group(1))
    for e in LOG:
        if e["n"] in req and e["n"] in rsp:
            e["cycles"] = rsp[e["n"]] - req[e["n"]]; e["cyc_req"] = req[e["n"]]
summary["backend"] = "attest_emu" if EMU else "rtl"
summary["steps"] = RESULTS; summary["log"] = LOG
summary["wall_s"] = round(time.time() - T_START, 1)
summary["all_pass"] = bool(RESULTS) and all(s["result"] == "PASS" for s in RESULTS)
groups = {}
for s in RESULTS:
    g = groups.setdefault(s["group"], [0, 0]); g[0 if s["result"] == "PASS" else 1] += 1
summary["groups"] = {k_: dict(passed=v[0], failed=v[1]) for k_, v in groups.items()}
json.dump(summary, open(os.path.join(DIR, "attest6_summary.json"), "w"), indent=1, default=lambda o: o.hex() if isinstance(o, bytes) else str(o))
for e in LOG: print("[attest6]   %03d %-44s status=%d fwerr=%s fatal=%s boot=%s cycles=%s" % (e["n"], e["name"], e["status"], e["fw_err_non_fatal"],
                    e["fw_err_fatal"], e["boot_status"], e.get("cycles", e["emu_cycles"] + max(e["lockwait_cycles"], 0) + max(e["post_cycles"], 0))))
print("[attest6] per group: " + ", ".join("%s %d/%d" % (k_, v[0], v[0] + v[1]) for k_, v in groups.items()))
fails = [s["step"] for s in RESULTS if s["result"] != "PASS"]
for f in fails: print("[attest6] FAILED: " + f)
print("[attest6] done, %d commands, %d steps, %.1f s; %s" % (n_req, len(RESULTS), summary["wall_s"],
      "ATTEST6 PASS" if summary["all_pass"] else "ATTEST6 FAIL (%d)" % len(fails)))
sys.exit(0 if summary["all_pass"] else 1)

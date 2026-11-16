#!/usr/bin/env python3
"""Caliptra 2.x exercise 5 (Nios-host side): housekeeping commands + FIRMWARE_VERIFY + runtime FIRMWARE_LOAD, in the
order a real product uses them:
  0 info      FW_INFO, VERSION (FPVR), CAPABILITIES (CAPS)                       - who are you, what can you do
  1 imginfo   SET_AUTH_MANIFEST + GET_IMAGE_INFO (IME0)                          - where does SoC image <fw_id> live
  2 selftest  SELF_TEST_START / SELF_TEST_GET_RESULTS (values "FPLT" / "FPLg")   - FIPS periodic self-test
  3 csr       GET_IDEV_{ECC384,MLDSA87}_CSR, GET_FMC_ALIAS_{ECC384,MLDSA87}_CSR, GET_ATTESTED_{ECC384,MLDSA87}_CSR
  4 fwverify  FIRMWARE_VERIFY (FWVR): real bundle + 11 tampered / wrong-size variants (no state change)
  5 fwload    runtime FIRMWARE_LOAD (FWLD) = impactless update (update reset): 3 rejected images, then the real one;
              FW_INFO / PCR quote / RT Alias cert / DPE leaf before and after
  6 shutdown  SHUTDOWN (FPSD), then every command must fail with RUNTIME_SHUTDOWN
Same file protocol / mailbox framing as attest4_driver.py: req_NNN.hex -> resp_NNN.hex + resp_NNN.done, cmd 0 ends.
FIRMWARE_LOAD / FIRMWARE_VERIFY carry the raw image (no checksum header). Needs the attest5 build of attest_emu
(attest/emu/attest_emu.rs: mailbox-lock polling, settle cycles, wait for runtime after FWLD) and the attest4 manifest
generator ($ATTEST4_MANIFEST_TOOL or $CALIPTRA_SW/target/release/examples/attest4_manifest).
Usage: attest5_driver.py DIR [TB_LOG]     (TB_LOG = the RTL run log: RTL mode, per-command cycles from the log)
Commands per caliptra-sw fw-2.1.4 (dd1e79d) api/src/mailbox.rs + runtime/src/*.rs; error names from
attest/caliptra_errors_fw214.json (extracted from caliptra-sw error/src/lib.rs). TEST material only.
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
EMU = True     # attest5 attest_emu build (extra resp lines); False on the RTL testbench (pass TB_LOG as argv[2])
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
    print("[attest5] req %03d %-34s cmd=%08x dlen=%d" % (n_req, name, cmd, len(data)), flush=True)
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
    print("[attest5]   -> status=%d len=%d fwerr=%08x%s%s chk=%s boot=%s cyc=%s%s (%.2fs)" % (st, dlen, fwerr,
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
    print("[attest5] STEP %-7s %-66s %s %s" % (group, name, "PASS" if passed else "FAIL", detail), flush=True)
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
    while len(out) < n: out += hashlib.sha512(("A5E attest5 TEST " + label).encode() + struct.pack(">I", len(out) // 64)).digest()
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
    nonce = H384(b"attest5 nonce " + tag.encode())[:32]
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
TOOL = os.environ.get("ATTEST4_MANIFEST_TOOL") or os.path.join(os.environ.get("CALIPTRA_SW", "/nonexistent"),
                                                              "target", "release", "examples", "attest4_manifest")
if not os.access(TOOL, os.X_OK):
    raise SystemExit("manifest generator not found: build attest/emu/attest4_manifest.rs (see SIMULATION_2X 12.3 / 13.3) and set "
                     "CALIPTRA_SW or ATTEST4_MANIFEST_TOOL")
summary["manifest_tool"] = TOOL
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
# ======================= attest5 command IDs =======================
CMD.update({k: cmd_id(k) for k in ("FPVR", "CAPS", "IME0", "IDCR", "IDMR", "FMCR", "FMDR", "AECR", "AMCR", "FWVR", "FWLD", "FPSD")})
# fw-2.1.4 quirk: SELF_TEST_START / SELF_TEST_GET_RESULTS are commented "FPST" / "FPGR" in api/src/mailbox.rs but the
# values are 0x46504C54 = "FPLT" and 0x46504C67 = "FPLg". Use the numbers.
CMD["FPST"], CMD["FPGR"] = 0x46504C54, 0x46504C67
E = {n: c for c, n in ERR.items()}          # name -> code
def code(n): return E[n]
summary["test"] = "attest5: housekeeping (VERSION, CAPABILITIES, GET_IMAGE_INFO, FIPS self-test, CSRs, SHUTDOWN) + FIRMWARE_VERIFY + runtime FIRMWARE_LOAD"

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
def osl_out(*a):                  # stdout only (openssl warns on stderr for null-signature CSRs)
    r = subprocess.run(["openssl", *a], capture_output=True)
    return r.returncode, r.stdout.decode(errors="replace")
def pemkey_of_cert(name):
    rc, pub = osl("x509", "-in", P(name + ".pem"), "-noout", "-pubkey"); open(P(name + ".pubkey.pem"), "w").write(pub); return pub
def csr_check(name, der, cert_name):
    """openssl req -verify (self-signature) + CSR public key == certificate public key + subject == cert subject."""
    save(name + ".der", der)
    rc, out = osl("req", "-inform", "DER", "-in", P(name + ".der"), "-noout", "-verify")
    sig_ok = rc == 0 and "verify OK" in out.replace("Certificate request self-signature verify OK", "verify OK")
    osl("req", "-inform", "DER", "-in", P(name + ".der"), "-out", P(name + ".pem"))
    osl("req", "-inform", "DER", "-in", P(name + ".der"), "-noout", "-text", "-out", P(name + ".txt"))
    rc2, pub = osl_out("req", "-inform", "DER", "-in", P(name + ".der"), "-noout", "-pubkey")
    rc3, subj = osl_out("req", "-inform", "DER", "-in", P(name + ".der"), "-noout", "-subject", "-nameopt", "RFC2253")
    rc4, csubj = osl_out("x509", "-in", P(cert_name + ".pem"), "-noout", "-subject", "-nameopt", "RFC2253")
    key_ok = pub.strip() == pemkey_of_cert(cert_name).strip()
    subj_ok = subj.strip().split("=", 1)[-1] == csubj.strip().split("=", 1)[-1]
    return sig_ok, key_ok, subj_ok, subj.strip()

# ---------------- minimal CBOR decoder (for the attested-CSR COSE_Sign1 / EAT) ----------------
class Tag:
    def __init__(s, t, v): s.tag, s.value = t, v
    def __repr__(s): return "Tag(%d,%r)" % (s.tag, s.value)
def cbor(b, i=0):
    ib = b[i]; mt, ai = ib >> 5, ib & 31; i += 1
    if ai < 24: n = ai
    elif ai in (24, 25, 26, 27): k = 1 << (ai - 24); n = int.from_bytes(b[i:i + k], "big"); i += k
    else: raise ValueError("indefinite CBOR not supported")
    if mt == 0: return n, i
    if mt == 1: return -1 - n, i
    if mt == 2: return bytes(b[i:i + n]), i + n
    if mt == 3: return b[i:i + n].decode(errors="replace"), i + n
    if mt == 4:
        out = []
        for _ in range(n): v, i = cbor(b, i); out.append(v)
        return out, i
    if mt == 5:
        out = {}
        for _ in range(n):
            k_, i = cbor(b, i); v, i = cbor(b, i); out[k_ if not isinstance(k_, (list, dict)) else repr(k_)] = v
        return out, i
    if mt == 6: v, i = cbor(b, i); return Tag(n, v), i
    return {20: False, 21: True, 22: None}.get(n, n), i
def cbor_hdr(mt, n):
    if n < 24: return bytes([mt << 5 | n])
    for ai, k in ((24, 1), (25, 2), (26, 4)):
        if n < (1 << (8 * k)): return bytes([mt << 5 | ai]) + n.to_bytes(k, "big")
def walk(o):
    yield o
    if isinstance(o, Tag): yield from walk(o.value)
    elif isinstance(o, list):
        for x in o: yield from walk(x)
    elif isinstance(o, dict):
        for x in o.values(): yield from walk(x)
def jsonable(o):
    if isinstance(o, Tag): return {"tag": o.tag, "value": jsonable(o.value)}
    if isinstance(o, bytes): return o.hex() if len(o) <= 64 else "%s..(%d B)" % (o[:16].hex(), len(o))
    if isinstance(o, list): return [jsonable(x) for x in o]
    if isinstance(o, dict): return {str(k): jsonable(v) for k, v in o.items()}
    return o

# ======================= 0. housekeeping: who are you, what can you do =======================
G = "info"
INFO0 = fw_info("start")
step(G, "FW_INFO: runtime up, pl0_pauser = 1, response checksum valid", INFO0.get("status") == 1 and INFO0["chk"] and INFO0["pl0_pauser"] == 1,
     "fw_svn=%s rt_rev=%s.." % (INFO0.get("fw_svn"), INFO0.get("rt_rev", "")[:12]))
step(G, "FW_INFO runtime SHA-384 == bundle runtime TOC digest == SHA-384(runtime image)",
     INFO0.get("rt_sha384") in (TOC["rt"]["digest"], swap_words(TOC["rt"]["digest"])) and TOC["rt"]["digest"] in (H384(img("rt")), swap_words(H384(img("rt")))),
     H384(img("rt")).hex()[:24] + "..")
step(G, "FW_INFO FMC SHA-384 == bundle FMC TOC digest == SHA-384(FMC image)",
     INFO0.get("fmc_sha384") in (TOC["fmc"]["digest"], swap_words(TOC["fmc"]["digest"])) and TOC["fmc"]["digest"] in (H384(img("fmc")), swap_words(H384(img("fmc")))),
     H384(img("fmc")).hex()[:24] + "..")
st, r, fe = mbox("VERSION", CMD["FPVR"])
ver = {}
if st == 1 and len(r) >= 36:
    ver = dict(fips_status=struct.unpack_from("<I", r, 4)[0], mode=struct.unpack_from("<I", r, 8)[0],
               fips_rev=list(struct.unpack_from("<3I", r, 12)), name=r[24:36])
summary["version"] = dict(ver, name=ver.get("name", b"").decode(errors="replace"), fips_rev=["%08x" % x for x in ver.get("fips_rev", [])])
step(G, "VERSION (FPVR): 36-B response, checksum valid, fips_status = 0 (FIPS_STATUS_APPROVED)",
     st == 1 and len(r) == 36 and LAST["resp_checksum_ok"] and ver.get("fips_status") == 0, "len=%d" % len(r))
step(G, "VERSION mode = 0x46495053 ('FIPS'), name = 'Caliptra RTM'", ver.get("mode") == 0x46495053 and ver.get("name") == b"Caliptra RTM",
     "mode=%08x name=%r" % (ver.get("mode", 0), ver.get("name")))
fr = ver.get("fips_rev", [0, 0, 0])
step(G, "VERSION fips_rev[1] = FMC version (bundle FMC TOC) << 16 | ROM version; fips_rev[2] = runtime version (bundle RT TOC)",
     fr[1] >> 16 == TOC["fmc"]["version"] & 0xFFFF and fr[2] == TOC["rt"]["version"],
     "hw_rev=%08x fmc=%04x rom=%04x rt=%08x" % (fr[0], fr[1] >> 16, fr[1] & 0xFFFF, fr[2]))
summary["version"]["decoded"] = dict(hw_rev_id="%08x" % fr[0], fmc_version="%04x" % (fr[1] >> 16), rom_version="%04x" % (fr[1] & 0xFFFF),
                                     rt_version="%08x" % fr[2])
st, r, fe = mbox("CAPABILITIES", CMD["CAPS"])
caps = int.from_bytes(r[8:24], "big") if st == 1 and len(r) == 24 else None
summary["capabilities"] = dict(raw=r[8:24].hex() if caps is not None else None,
                               bits=[n for b, n in ((0, "ROM_BASE"), (1, "ROM_OCP_LOCK"), (2, "ROM_STABLE_OWNER_KEY"),
                                                    (64, "RT_BASE"), (65, "RT_OCP_LOCK")) if caps and caps >> b & 1])
step(G, "CAPABILITIES (CAPS): 24-B response, checksum valid, u128 big-endian = RT_BASE (bit 64) only; RT_OCP_LOCK clear (no ocp-lock)",
     caps == 1 << 64 and LAST["resp_checksum_ok"], "caps=%s %s" % (r[8:24].hex() if caps is not None else None, summary["capabilities"]["bits"]))
st, r, fe = mbox("VERSION_bad_checksum", CMD["FPVR"], chk=0x12345678)
expect_fail(G, "VERSION with a wrong request checksum", st, fe, code("RUNTIME_INVALID_CHECKSUM"))
st, r, fe = mbox("VERSION_extra_bytes", CMD["FPVR"], b"\0" * 4)
step(G, "VERSION with 4 extra request bytes (record behaviour)", True, "status=%d fwerr=%08x %s" % (st, fe, ERR.get(fe, "")))
summary["version_extra_bytes"] = dict(status=st, fwerr="%08x" % fe, name=ERR.get(fe))

# ======================= 1. GET_IMAGE_INFO: where does SoC image <fw_id> live? =======================
G = "imginfo"
APP = T("Nios V application image v1.0.0", 64 * 1024); BIT = T("Agilex 5E core bitstream rev A", 128 * 1024)
save("nios_app_v1.bin", APP); save("bitstream_revA.rbf", BIT)
D_APP, D_BIT = H384(APP), H384(BIT)
FW_APP, FW_BIT, FW_UNKNOWN = 0x1001, 0x1002, 0x2000
IMF_SRC_REQ = 1
def image_info(name, fw_id, flags=0):
    st, r, fe = mbox("GET_IMAGE_INFO_" + name, CMD["IME0"], u32(fw_id, flags))
    if st != 1: return st, fe, None
    v = struct.unpack_from("<6I", r, 8)
    return st, fe, dict(component_id=v[0], flags=v[1], load=(v[2] << 32) | v[3], staging=(v[4] << 32) | v[5], digest=r[32:80], chk=LAST["resp_checksum_ok"])
st, fe, ii = image_info("app_before_manifest", FW_APP)
expect_fail(G, "GET_IMAGE_INFO Nios app before any SoC manifest", st, fe, code("RUNTIME_IMAGE_METADATA_NOT_FOUND"))
args = [TOOL, P("manifest_m5.bin"), "1", "0", "1", "good", "0x%x:0x10:0x%x:%s" % (FW_APP, IMF_SRC_REQ, D_APP.hex()),
        "0x%x:0x20:0x%x:%s" % (FW_BIT, IMF_SRC_REQ, D_BIT.hex())]
rr = subprocess.run(args, capture_output=True, text=True)
if rr.returncode: raise SystemExit("manifest generator failed: " + rr.stderr)
M5 = open(P("manifest_m5.bin"), "rb").read()
step(G, "SoC manifest M5 built (caliptra-auth-man-gen): 'ATM2', 2 entries (Nios app 0x1001 -> comp 0x10, bitstream 0x1002 -> comp 0x20)",
     M5[:4] == b"ATM2", "%d B" % len(M5))
st, r, fe = mbox("SET_AUTH_MANIFEST_m5", CMD["ATMN"], u32(len(M5)) + M5)
step(G, "SET_AUTH_MANIFEST M5 accepted", OK(st), "status=%d fwerr=%08x" % (st, fe))
for nm, fid, comp, dig in (("app", FW_APP, 0x10, D_APP), ("bitstream", FW_BIT, 0x20, D_BIT)):
    st, fe, ii = image_info(nm, fid)
    summary.setdefault("image_info", {})[nm] = dict(ii, digest=ii["digest"].hex()) if ii else dict(status=st, fwerr="%08x" % fe)
    step(G, "GET_IMAGE_INFO fw_id 0x%x (%s): component_id 0x%x, flags = 1 (InRequest), digest == SHA-384(image), checksum valid" % (fid, nm, comp),
         ii is not None and ii["component_id"] == comp and ii["flags"] == IMF_SRC_REQ and ii["digest"] == dig and ii["chk"],
         ("comp=%x flags=%x load=%x staging=%x digest=%s.." % (ii["component_id"], ii["flags"], ii["load"], ii["staging"], ii["digest"].hex()[:16])) if ii else "status=%d fwerr=%08x" % (st, fe))
    if ii: step(G, "GET_IMAGE_INFO 0x%x: load / staging address = 0 (attest4_manifest leaves them 0; set them for DMA sources)" % fid,
                ii["load"] == 0 and ii["staging"] == 0)
st, fe, ii = image_info("unknown", FW_UNKNOWN)
expect_fail(G, "GET_IMAGE_INFO unknown fw_id 0x2000", st, fe, code("RUNTIME_IMAGE_METADATA_NOT_FOUND"))
st, fe, ii = image_info("owner_source", FW_APP, 1 << 1)
expect_fail(G, "GET_IMAGE_INFO flags = owner-manifest source (no owner manifest set)", st, fe, code("RUNTIME_IMAGE_METADATA_NOT_FOUND"))
st, fe, ii = image_info("bad_flags", FW_APP, 1 << 7)
expect_fail(G, "GET_IMAGE_INFO undefined flag bit 7", st, fe, code("RUNTIME_MAILBOX_INVALID_PARAMS"))

# ======================= 2. FIPS self-test =======================
G = "selftest"
st, r, fe = mbox("SELF_TEST_GET_RESULTS_before_start", CMD["FPGR"])
expect_fail(G, "SELF_TEST_GET_RESULTS before SELF_TEST_START", st, fe, code("RUNTIME_SELF_TEST_NOT_STARTED"))
st, r, fe = mbox("SELF_TEST_START", CMD["FPST"])
step(G, "SELF_TEST_START ('FPLT' 0x46504C54) accepted; the test runs in the background when the runtime goes idle", OK(st),
     "status=%d len=%d fwerr=%08x" % (st, len(r), fe))
st, r, fe = mbox("SELF_TEST_START_again", CMD["FPST"])
lw = LAST["lockwait_cycles"]
summary["self_test"] = dict(lockwait_cycles=lw, boot_status_after=LAST["boot_status"])
if EMU:
    step(G, "host waited for the mailbox lock while Caliptra ran the self-test (KATs + ROM integrity + image re-verify)", lw > 0,
         "lock held %d emulator cycles" % lw)
    step(G, "CPTRA_BOOT_STATUS = 0x602 (RtFipSelfTestComplete) after the self-test (emulator register view)", LAST["boot_status"] == "00000602", "boot=%s" % LAST["boot_status"])
expect_fail(G, "second SELF_TEST_START before the results are read", st, fe, code("RUNTIME_SELF_TEST_IN_PROGRESS"))
st, r, fe = mbox("SELF_TEST_GET_RESULTS", CMD["FPGR"])
step(G, "SELF_TEST_GET_RESULTS ('FPLg' 0x46504C67) = pass (status OK, no fatal error)", OK(st) and int(LAST["fw_err_fatal"], 16) == 0,
     "status=%d len=%d fwerr=%08x" % (st, len(r), fe))
st, r, fe = mbox("SELF_TEST_GET_RESULTS_again", CMD["FPGR"])
expect_fail(G, "SELF_TEST_GET_RESULTS again (result already consumed, state back to Idle)", st, fe, code("RUNTIME_SELF_TEST_NOT_STARTED"))
INFO_ST = fw_info("after_selftest")
step(G, "runtime still serving after the self-test; FW_INFO unchanged", same_info(INFO0, INFO_ST))

# ======================= 3. CSRs: certificate signing requests for the device keys =======================
G = "csr"
for nm, c in (("ldevid_ecc384", "LDEV"), ("fmc_alias_ecc384", "CERF"), ("rt_alias_ecc384", "CERR"),
              ("ldevid_mldsa87", "LDMC"), ("fmc_alias_mldsa87", "CMCF"), ("rt_alias_mldsa87", "CMCR")):
    st, r, fe = mbox("GET_" + nm.upper() + "_CERT", CMD[c])
    step(G, "%s certificate read (reference for the CSR key checks)" % nm, st == 1 and save_cert(nm, var_data(r)), "%d B" % len(var_data(r)) if st == 1 else "status=%d" % st)
CSR = {}
for nm, c, alg in (("GET_IDEV_ECC384_CSR", "IDCR", "ecc"), ("GET_IDEV_MLDSA87_CSR", "IDMR", "mldsa")):
    st, r, fe = mbox(nm, CMD[c])
    CSR[nm] = dict(status=st, fwerr="%08x" % fe, name=ERR.get(fe))
    expect_fail(G, "%s: no IDevID CSR (CSR generation was not requested at cold boot, Production lifecycle)" % nm, st, fe,
                code("RUNTIME_GET_IDEV_ID_UNPROVISIONED"))
for nm, c, alg, cert in (("GET_FMC_ALIAS_ECC384_CSR", "FMCR", "ecc", "fmc_alias_ecc384"), ("GET_FMC_ALIAS_MLDSA87_CSR", "FMDR", "mldsa", "fmc_alias_mldsa87")):
    st, r, fe = mbox(nm, CMD[c])
    if st == 1:
        der = var_data(r); sig_ok, key_ok, subj_ok, subj = csr_check(nm.lower(), der, cert)
        CSR[nm] = dict(status=st, size=len(der), subject=subj, self_sig=sig_ok, key_matches_cert=key_ok, subject_matches_cert=subj_ok)
        step(G, "%s: %d-B PKCS#10, openssl req -verify OK, checksum valid" % (nm, len(der)), sig_ok and LAST["resp_checksum_ok"], subj)
        step(G, "%s: CSR public key == %s certificate key, same subject" % (nm, cert), key_ok and subj_ok)
    else:
        CSR[nm] = dict(status=st, fwerr="%08x" % fe, name=ERR.get(fe))
        step(G, "%s returned a CSR" % nm, False, "status=%d fwerr=%08x %s" % (st, fe, ERR.get(fe)))
NONCE = H384(b"attest5 attested CSR nonce")[:32]
KEYS = {1: "ldevid", 2: "fmc_alias", 3: "rt_alias"}
def attested(alg, key_id, nonce=NONCE):
    sfx = "ecc384" if alg == "ecc" else "mldsa87"; nm = "GET_ATTESTED_%s_CSR_key%d" % (sfx.upper(), key_id)
    st, r, fe = mbox(nm, CMD["AECR" if alg == "ecc" else "AMCR"], u32(key_id) + nonce)
    if st != 1: return dict(status=st, fwerr="%08x" % fe, name=ERR.get(fe))
    blob = var_data(r); save(nm.lower() + ".cose", blob)
    obj, end = cbor(blob)
    tags, cose = [], obj
    while isinstance(cose, Tag): tags.append(cose.tag); cose = cose.value      # 61 (CWT) -> 18 (COSE_Sign1)
    out = dict(status=st, size=len(blob), chk=LAST["resp_checksum_ok"], cbor_tags=tags, whole=end == len(blob))
    prot_b, unprot, payload, sig = cose
    prot = cbor(prot_b)[0]
    out.update(alg=prot.get(1), content_type=prot.get(3), kid=(prot.get(4) or unprot.get(4) or b"").hex(), sig_len=len(sig))
    tbs = cbor_hdr(4, 4) + cbor_hdr(3, 10) + b"Signature1" + cbor_hdr(2, len(prot_b)) + prot_b + b"\x40" + cbor_hdr(2, len(payload)) + payload
    save(nm.lower() + ".sig_structure", tbs)
    pem = P("rt_alias_%s.pubkey.pem" % sfx); pemkey_of_cert("rt_alias_" + sfx)
    if alg == "ecc":
        out["sig_ok"] = v_ecdsa_msg(pem, tbs, sig[:48], sig[48:96], nm.lower())
    else:
        out["sig_ok"] = v_mldsa_msg(pem, tbs, sig, nm.lower())
    claims = cbor(payload)[0]
    while isinstance(claims, Tag): claims = claims.value
    out["claims"] = jsonable(claims)
    out["nonce_ok"] = any(isinstance(x, bytes) and x == nonce for x in walk(claims))
    csrs = [x for x in walk(claims) if isinstance(x, bytes) and len(x) > 64 and x[0] == 0x30]
    if key_id and csrs:
        sig2, key_ok, subj_ok, subj = csr_check(nm.lower() + "_csr", csrs[0], "%s_%s" % (KEYS[key_id], sfx))
        sigval = children(tlv(csrs[0], 0)[1])[2][1][1:]          # BIT STRING minus the unused-bits byte
        out["csr_null_sig"] = sigval == bytes.fromhex("3006020100020100") or not any(sigval)
        out.update(csr_size=len(csrs[0]), csr_self_sig=sig2, csr_key_matches_cert=key_ok, csr_subject_matches_cert=subj_ok, csr_subject=subj)
    # kid = the RT Alias subject key identifier?
    ski = cert_exts(rdcert("rt_alias_" + sfx)).get("2.5.29.14", {}).get("raw")
    out["kid_is_rt_ski"] = ski is not None and tlv(ski, 0)[1].hex() == out["kid"]
    return out
ATT = {}
for alg in ("ecc", "mldsa"):
    for kid in (1, 2, 3):
        a = ATT["%s_%d" % (alg, kid)] = attested(alg, kid)
        what = "GET_ATTESTED_%s_CSR key_id %d (%s)" % ("ECC384" if alg == "ecc" else "MLDSA87", kid, KEYS[kid])
        if a["status"] != 1: step(G, what, False, "status=%d fwerr=%s %s" % (a["status"], a["fwerr"], a["name"])); continue
        step(G, what + ": COSE_Sign1 signed by the RT Alias %s key (openssl), nonce echoed, checksum valid" % alg.upper(),
             a["sig_ok"] and a["nonce_ok"] and a["chk"], "%d B, alg=%s, tags=%s" % (a["size"], a["alg"], a["cbor_tags"]))
        if kid == 1:   # the LDevID private key no longer exists at runtime: the CSR carries an all-zero signature
            step(G, what + ": embedded CSR has a NULL signature (r=s=0 / zero ML-DSA sig), key == ldevid cert key, same subject",
                 a.get("csr_null_sig") and not a.get("csr_self_sig") and a.get("csr_key_matches_cert") and a.get("csr_subject_matches_cert"),
                 "%s B CSR" % a.get("csr_size"))
        else:
            step(G, what + ": embedded CSR self-signature OK, key == %s cert key, same subject" % KEYS[kid],
                 a.get("csr_self_sig") and a.get("csr_key_matches_cert") and a.get("csr_subject_matches_cert"),
                 "%s B CSR" % a.get("csr_size"))
    a = ATT["%s_0" % alg] = attested(alg, 0)
    step(G, "GET_ATTESTED_%s_CSR key_id 0 (key-pair inventory EAT, no CSR): signed by RT Alias, nonce echoed" % ("ECC384" if alg == "ecc" else "MLDSA87"),
         a["status"] == 1 and a["sig_ok"] and a["nonce_ok"], "%s B" % a.get("size"))
    a = attested(alg, 4)
    expect_fail(G, "GET_ATTESTED_%s_CSR key_id 4 (no such key)" % ("ECC384" if alg == "ecc" else "MLDSA87"), a["status"], int(a.get("fwerr", "0"), 16),
                code("RUNTIME_MAILBOX_INVALID_PARAMS"))
step(G, "attested-CSR COSE kid == RT Alias subjectKeyIdentifier (ECC and ML-DSA)", ATT["ecc_1"].get("kid_is_rt_ski") and ATT["mldsa_1"].get("kid_is_rt_ski"),
     ATT["ecc_1"].get("kid", "")[:16] + "..")
summary["csr"] = CSR; summary["attested_csr"] = ATT

# ======================= 4. FIRMWARE_VERIFY: is this update image good? (no state change) =======================
G = "fwverify"
FV_OK, FV_FAIL = 0xDEADC0DE, 0x21523F21
def flip(b, off, x=0x01): b = bytearray(b); b[off] ^= x; return bytes(b)
RT_OFF = TOC["rt"]["offset"]; FMC_OFF = TOC["fmc"]["offset"]
VARIANTS = [
    ("bad_vendor_ecc_sig", flip(BUNDLE, 4444 + 20), "vendor ECC P-384 signature byte flipped"),
    ("bad_vendor_mldsa_sig", flip(BUNDLE, 4444 + 96 + 100), "vendor ML-DSA-87 signature byte flipped"),
    ("bad_owner_ecc_sig", flip(BUNDLE, 11856 + 20), "owner ECC P-384 signature byte flipped"),
    ("bad_header_svn", flip(BUNDLE, 16664), "header SVN changed (signed data)"),
    ("bad_toc", flip(BUNDLE, 16852 + 28), "runtime TOC version changed (TOC digest mismatch)"),
    ("bad_fmc_digest", flip(BUNDLE, FMC_OFF + 0x100), "FMC image byte flipped"),
    ("bad_rt_digest", flip(BUNDLE, RT_OFF + 0x100), "runtime image byte flipped"),
    ("bad_marker", flip(BUNDLE, 0), "manifest marker 'CMN2' broken"),
    ("truncated_4k", BUNDLE[:-4096], "last 4 KiB cut (image shorter than manifest + FMC + RT)"),
    ("truncated_manifest", BUNDLE[:MAN_SIZE - 4], "only part of the manifest (shorter than ImageManifest)"),
    ("padded_4k", BUNDLE + b"\0" * 4096, "4 KiB of zeros appended (wrong size, longer)"),
]
def fwverify(name, image):
    st, r, fe = mbox("FIRMWARE_VERIFY_" + name, CMD["FWVR"], image, raw=True)
    res = struct.unpack_from("<I", r, 8)[0] if st == 1 and len(r) >= 12 else None
    return st, fe, res, LAST["resp_checksum_ok"]
FV = {}
st, fe, res, ck = fwverify("good", BUNDLE)
FV["good"] = dict(status=st, fwerr="%08x" % fe, result=res and "%08x" % res)
step(G, "FIRMWARE_VERIFY real bundle (%d B, raw image in the mailbox, no header) -> 0xDEADC0DE success" % len(BUNDLE),
     st == 1 and res == FV_OK and ck, "status=%d result=%s fwerr=%08x cycles=%d" % (st, res and "%08x" % res, fe, LAST["emu_cycles"]))
# fw-2.1.4: FIRMWARE_VERIFY reads the manifest from the whole mailbox SRAM (raw_mailbox_contents), not just dlen, so a
# request shorter than ImageManifest does NOT get IMAGE_VERIFIER_ERR_MANIFEST_SIZE_MISMATCH: it is verified and fails (0x21523F21).
EXPECT_FV = {"padded_4k": "accept"}
for nm, im, desc in VARIANTS:
    save("bundle_%s.bin" % nm, im)
    st, fe, res, ck = fwverify(nm, im)
    FV[nm] = dict(desc=desc, size=len(im), status=st, fwerr="%08x" % fe, fwerr_name=ERR.get(fe), result=res and "%08x" % res)
    exp = EXPECT_FV.get(nm, "fail")
    if exp == "fail":
        step(G, "FIRMWARE_VERIFY %s -> 0x21523F21 failure (status OK)" % desc, st == 1 and res == FV_FAIL,
             "status=%d result=%s fwerr=%08x %s" % (st, res and "%08x" % res, fe, ERR.get(fe, "")))
    elif exp == "accept":
        step(G, "FIRMWARE_VERIFY %s -> still 0xDEADC0DE (the verifier only needs manifest + FMC + RT <= dlen)" % desc,
             st == 1 and res == FV_OK, "status=%d result=%s fwerr=%08x" % (st, res and "%08x" % res, fe))
    else:
        expect_fail(G, "FIRMWARE_VERIFY %s" % desc, st, fe, code("IMAGE_VERIFIER_ERR_MANIFEST_SIZE_MISMATCH"))
INFO_FV = fw_info("after_verify")
step(G, "FIRMWARE_VERIFY changed nothing: FW_INFO identical, runtime still serving", same_info(INFO0, INFO_FV))
summary["firmware_verify"] = FV

# ======================= 5. runtime FIRMWARE_LOAD (impactless update = update reset) =======================
G = "fwload"
LABEL = H384(b"attest5 certify-key label")
def quote_ok(tag):
    q = quote(tag); return q, q.get("status") == 1 and quote_sig_ok(q, "ecc", "fmc_alias_ecc384")
q0, ok0 = quote_ok("before_update")
step(G, "QUOTE_PCRS_ECC384 before the update verifies with the FMC Alias ECC key", ok0)
LE0 = certify("ecc", "before_update")
step(G, "DPE CertifyKey ECC leaf before the update", LE0.get("cert") is not None, "%d TCB entries" % len(LE0.get("tcb", [])))
rt_cert0 = rdcert("rt_alias_ecc384")
def fwload(name, image):
    st, r, fe = mbox("FIRMWARE_LOAD_" + name, CMD["FWLD"], image, raw=True)
    return st, fe, LAST
FL = {}
for nm, code_name in (("bad_vendor_ecc_sig", "IMAGE_VERIFIER_ERR_VENDOR_ECC_SIGNATURE_INVALID"),
                      ("bad_rt_digest", "IMAGE_VERIFIER_ERR_RUNTIME_DIGEST_MISMATCH"),
                      ("truncated_4k", None)):
    im = dict((v[0], v[1]) for v in VARIANTS)[nm]
    st, fe, L = fwload(nm, im)
    FL[nm] = dict(status=st, fwerr="%08x" % fe, fwerr_name=ERR.get(fe), fatal=L["fw_err_fatal"], boot=L["boot_status"], flow=L["flow_status"],
                  cycles=L["emu_cycles"], post_cycles=L["post_cycles"])
    if code_name: expect_fail(G, "FIRMWARE_LOAD %s rejected by ROM (update reset)" % nm, st, fe, code(code_name))
    else: step(G, "FIRMWARE_LOAD %s rejected by ROM (record code)" % nm, st == 3 and fe != 0, "status=%d fwerr=%08x %s" % (st, fe, ERR.get(fe)))
    step(G, "after the rejected %s: no fatal error; ROM goes on to FMC -> old runtime, back in its command loop" % nm,
         int(L["fw_err_fatal"], 16) == 0 and (not EMU or 0 < L["post_cycles"] < 400_000_000),
         "post_cycles=%d flow=%s boot=%s" % (L["post_cycles"], L["flow_status"], L["boot_status"]))
    inf = fw_info("after_bad_" + nm)
    step(G, "FW_INFO after rejected %s: same firmware, runtime serving" % nm, same_info(INFO0, inf), "most_recent_fw_error=%08x" % inf.get("most_recent_fw_error", 0))
    FL[nm]["most_recent_fw_error"] = "%08x" % inf.get("most_recent_fw_error", 0)
q1, ok1 = quote_ok("after_rejects")
step(G, "PCRs after the rejected loads == before (nothing measured)", ok1 and q1["pcrs"] == q0["pcrs"],
     "changed: %s" % [i for i in range(32) if q1["pcrs"][i] != q0["pcrs"][i]])
st, fe, L = fwload("good", BUNDLE)
FL["good"] = dict(status=st, fwerr="%08x" % fe, fatal=L["fw_err_fatal"], boot=L["boot_status"], cycles=L["emu_cycles"], post_cycles=L["post_cycles"])
step(G, "FIRMWARE_LOAD the same signed bundle: ROM verifies + loads it (mailbox completes OK)", OK(st) and fe == 0,
     "status=%d fwerr=%08x cycles=%d" % (st, fe, L["emu_cycles"]))
step(G, "runtime back in its command loop after update reset -> ROM -> FMC -> runtime, no fatal error",
     int(L["fw_err_fatal"], 16) == 0 and (not EMU or L["post_cycles"] < 400_000_000), "post_cycles=%d flow=%s" % (L["post_cycles"], L["flow_status"]))
INFO1 = fw_info("after_update")
step(G, "FW_INFO after the update: same ROM / FMC / runtime revisions and digests, same SVNs", same_info(INFO0, INFO1) and INFO1["cold_boot_fw_svn"] == INFO0["cold_boot_fw_svn"],
     "fw_svn=%s min=%s cold=%s" % (INFO1.get("fw_svn"), INFO1.get("min_fw_svn"), INFO1.get("cold_boot_fw_svn")))
q2, ok2 = quote_ok("after_update")
chg = [i for i in range(32) if q2["pcrs"][i] != q0["pcrs"][i]] if ok2 else None
summary["pcr_changes_after_update"] = chg
save("pcrs_before_update.bin", b"".join(q0["pcrs"])); save("pcrs_after_update.bin", b"".join(q2.get("pcrs", [])))
step(G, "PCR quote after the update verifies (FMC Alias key unchanged)", ok2)
step(G, "PCR0 (current FMC/RT measurement) unchanged: same image -> same value", ok2 and q2["pcrs"][0] == q0["pcrs"][0])
step(G, "PCR1 (journey, never reset except cold boot) extended again; every other PCR unchanged", ok2 and chg == [1],
     "pcrs changed: %s" % chg)
st, r, fe = mbox("GET_RT_ALIAS_ECC384_CERT_after_update", CMD["CERR"])
step(G, "RT Alias ECC certificate after the update == before (same runtime image -> same RT Alias key)", st == 1 and var_data(r) == rt_cert0)
LE1 = certify("ecc", "after_update")
dif = [i for i, (a, b) in enumerate(zip(LE0.get("tcb", []), LE1.get("tcb", []))) if a != b]
summary["dpe_tcb_changed_after_update"] = [dict(before=LE0["tcb"][i], after=LE1["tcb"][i]) for i in dif]
step(G, "DPE leaf after the update: same TCB entries (RMTR fwid = current runtime measurement, same image -> same value)",
     LE1.get("cert") is not None and LE1["tcb"] == LE0["tcb"], "types %s" % [t.get("type") for t in LE1.get("tcb", [])])
ok, msg = verify_by("rt_alias_ecc384", LE1["name"]) if LE1.get("cert") else (False, "")
step(G, "openssl: RT Alias ECC -> DPE leaf after the update", ok, msg)
st, fe, ii = image_info("app_after_update", FW_APP)
summary["image_info_after_update"] = dict(status=st, fwerr="%08x" % fe, kept=ii is not None)
step(G, "SoC auth manifest survives the update reset (persistent data): GET_IMAGE_INFO 0x1001 still returns comp 0x10", ii is not None and ii["component_id"] == 0x10,
     "status=%d fwerr=%08x %s" % (st, fe, "kept" if ii else ERR.get(fe)))
summary["firmware_load"] = FL

# ======================= 6. SHUTDOWN (last) =======================
G = "shutdown"
st, r, fe = mbox("SHUTDOWN", CMD["FPSD"])
step(G, "SHUTDOWN (FPSD) accepted: checksum valid, fips_status 0", OK(st) and (st == 2 or (LAST["resp_checksum_ok"] and struct.unpack_from("<I", r, 4)[0] == 0)),
     "status=%d len=%d" % (st, len(r)))
for nm, c in (("VERSION", "FPVR"), ("FW_INFO", "INFO"), ("CAPABILITIES", "CAPS")):
    st, r, fe = mbox(nm + "_after_shutdown", CMD[c])
    expect_fail(G, "%s after SHUTDOWN" % nm, st, fe, code("RUNTIME_SHUTDOWN"))
summary["after_shutdown"] = dict(fatal=LAST["fw_err_fatal"], fatal_name=LAST["fw_err_fatal_name"], boot=LAST["boot_status"])

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
json.dump(summary, open(os.path.join(DIR, "attest5_summary.json"), "w"), indent=1, default=lambda o: o.hex() if isinstance(o, bytes) else str(o))
for e in LOG: print("[attest5]   %03d %-44s status=%d fwerr=%s fatal=%s boot=%s cycles=%s" % (e["n"], e["name"], e["status"], e["fw_err_non_fatal"],
                    e["fw_err_fatal"], e["boot_status"], e.get("cycles", e["emu_cycles"] + max(e["lockwait_cycles"], 0) + max(e["post_cycles"], 0))))
print("[attest5] per group: " + ", ".join("%s %d/%d" % (k_, v[0], v[0] + v[1]) for k_, v in groups.items()))
fails = [s["step"] for s in RESULTS if s["result"] != "PASS"]
for f in fails: print("[attest5] FAILED: " + f)
print("[attest5] done, %d commands, %d steps, %.1f s; %s" % (n_req, len(RESULTS), summary["wall_s"],
      "ATTEST5 PASS" if summary["all_pass"] else "ATTEST5 FAIL (%d)" % len(fails)))
sys.exit(0 if summary["all_pass"] else 1)

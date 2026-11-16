#!/usr/bin/env python3
"""Caliptra 2.x attestation exercise 4 (Nios-host side): an end-to-end attestation use case with 8 more fw-2.1.4
runtime commands.
  Phase 1  manufacturing / provisioning : the vendor (manufacturing) TEST CA certifies the IDevID keys, the SoC hands
           the certs to Caliptra (POPULATE_IDEV_ECC384_CERT / POPULATE_IDEV_MLDSA87_CERT) and a verifier checks the
           full chain vendor CA -> IDevID -> LDevID -> FMC Alias -> RT Alias -> DPE leaf with openssl.
  Phase 2  image authorization : a real SoC auth manifest ("ATM2", caliptra-auth-man-gen) signed with the vendor and
           owner ECC P-384 + ML-DSA-87 keys -> VERIFY_AUTH_MANIFEST, SET_AUTH_MANIFEST, AUTHORIZE_AND_STASH (stash into
           DPE + PCR31, SKIP_STASH, wrong digest, unknown FW ID, ignore_auth_check), tampered / mis-signed manifests.
  Phase 3  exported CDI signing : DPE DeriveContext with EXPORT_CDI | CREATE_CERTIFICATE, SIGN_WITH_EXPORTED_ECDSA,
           SIGN_WITH_EXPORTED_MLDSA (raw and mu), REVOKE_EXPORTED_CDI_HANDLE and the revocation lifecycle.
Same file protocol / mailbox framing as attest3_driver.py (tb_nios2x_top_fw +test=attest, or the sw-emulator
attest_emu example):  req_NNN.hex -> resp_NNN.hex + resp_NNN.done, cmd 0 ends the stream.
Commands (caliptra-sw fw-2.1.4 = dd1e79d, api/src/mailbox.rs + runtime/src/*.rs, caliptra-dpe f2b7121). u32 = LE.
  POPULATE_IDEV_ECC384_CERT "IDEP" cert_size | cert[<=1024]    POPULATE_IDEV_MLDSA87_CERT "IDMP" cert_size | cert[<=8192]
       (prepends the cert to the DPE cert chain; PL0 only; no "already populated" guard)
  SET_AUTH_MANIFEST "ATMN" / VERIFY_AUTH_MANIFEST "ATVM"  manifest_size | AuthorizationManifest (<= 34 KiB)
  AUTHORIZE_AND_STASH "ATSH" fw_id[4] | measurement[48] | context[48] | svn | flags(bit0 SKIP_STASH, bits2:1 source
       0 vendor+owner / 1 owner-only) | source(1 InRequest, 2 LoadAddress, 3 StagingAddress) | image_size
       -> auth_req_result 0xDEADC0DE authorized / 0x21523F21 not authorized / 0x8BFB95CB hash mismatch
  SIGN_WITH_EXPORTED_ECDSA "SWEE" exported_cdi_handle[32] | tbs digest[48] -> pub x[48] y[48] | r[48] s[48]
  SIGN_WITH_EXPORTED_MLDSA "SWML" exported_cdi_handle[32] | sign_type(0 mu, 1 raw) | tbs_size | tbs[1024]
       -> pub[2592] | sig[4627] | pad
  REVOKE_EXPORTED_CDI_HANDLE "RVCH" exported_cdi_handle[32]
  DPE DeriveContext flags: EXPORT_CDI 1<<23, CREATE_CERTIFICATE 1<<22, RETAIN_PARENT 1<<29 ->
       resp hdr | handle[16] | parent_handle[16] | exported_cdi[32] | cert_size | cert
Usage: attest4_driver.py DIR [TB_LOG]
Needs the manifest generator built from caliptra-sw (attest/emu/attest4_manifest.rs): $ATTEST4_MANIFEST_TOOL or
$CALIPTRA_SW/target/release/examples/attest4_manifest. Host side otherwise: openssl >= 3.5 + Python 3 stdlib only.
TEST material only (caliptra-sw public fake keys, gitignored TEST CA private keys).
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

# fw-2.1.4 quirk: api/src/mailbox.rs comments DPE_TAG_TCI as "TAGT" but the value is 0x54514754 = "TQGT".
# Sending "TAGT" (0x54414754) returns RUNTIME_UNIMPLEMENTED_COMMAND (0x000E0002).
CMD["TAGT"] = 0x54514754
def tt(s): return struct.unpack("<I", s.encode())[0]   # tci_type: stored/encoded little-endian (see 'RMTR' quirk)

def checksum(cmd, data):          # caliptra-sw api/src/checksum.rs
    return (-(sum(struct.pack("<I", cmd)) + sum(data))) & 0xFFFFFFFF

n_req = 0
def mbox(name, cmd, payload=b"", timeout_s=float(os.environ.get("CRYPTO_TIMEOUT_H", "72")) * 3600):
    """Send one mailbox command (checksum prepended); return (status, resp bytes, fw_err_non_fatal)."""
    global n_req
    name = re.sub(r"[^A-Za-z0-9_]", "", name.replace(" ", "_").replace("-", "_"))
    data = struct.pack("<I", checksum(cmd, payload)) + payload
    words = [struct.unpack_from("<I", data + b"\0" * 3, i)[0] for i in range(0, len(data), 4)]
    tmp = os.path.join(DIR, ".req.tmp")
    with open(tmp, "w") as f:
        f.write("%08x\n%08x\n" % (cmd, len(data)) + "".join("%08x\n" % w for w in words))
    os.rename(tmp, os.path.join(DIR, "req_%03d.hex" % n_req))
    t0 = time.time(); done = os.path.join(DIR, "resp_%03d.done" % n_req)
    print("[attest4] req %03d %-34s cmd=%08x dlen=%d" % (n_req, name, cmd, len(data)), flush=True)
    while not os.path.exists(done):
        if time.time() - t0 > timeout_s: raise SystemExit("timeout waiting for " + done)
        time.sleep(0.05)
    time.sleep(0.05)
    lines = open(os.path.join(DIR, "resp_%03d.hex" % n_req)).read().split("\n")
    st, dlen = int(lines[0], 16), int(lines[1], 16)
    fwerr = int([l for l in lines if l.startswith("fwerr")][0].split()[1], 16)
    resp = b"".join(struct.pack("<I", int(l, 16)) for l in lines[2:2 + (dlen + 3) // 4])[:dlen]
    ok_ck = None
    if st == 1 and dlen >= 8:
        ok_ck = struct.unpack_from("<I", resp)[0] == checksum(0, resp[4:])
    ent = dict(n=n_req, name=name, cmd="%08x" % cmd, req_len=len(data), status=st, resp_len=dlen,
               fw_err_non_fatal="%08x" % fwerr, fw_err_name=ERR.get(fwerr), resp_checksum_ok=ok_ck,
               wall_s=round(time.time() - t0, 2))
    LOG.append(ent)
    print("[attest4]   -> status=%d len=%d fwerr=%08x%s chk=%s (%.2fs)" % (st, dlen, fwerr,
          " (%s)" % ERR[fwerr] if fwerr in ERR else "", ok_ck, ent["wall_s"]), flush=True)
    open(os.path.join(DIR, "resp_%03d_%s.bin" % (n_req, name)), "wb").write(resp)
    n_req += 1
    return st, resp, fwerr

OK = lambda st: st in (1, 2)      # DATA_READY / CMD_COMPLETE
RESULTS = []
def step(group, name, passed, detail=""):
    RESULTS.append(dict(group=group, step=name, result="PASS" if passed else "FAIL", detail=detail))
    print("[attest4] STEP %-7s %-66s %s %s" % (group, name, "PASS" if passed else "FAIL", detail), flush=True)
    return passed
def expect_fail(group, name, st, fe, code):
    return step(group, name + " (expect reject %08x)" % code, st == 3 and fe == code, "status=%d fwerr=%08x" % (st, fe))
def u32(*v): return struct.pack("<%dI" % len(v), *v)
def save(name, data): open(os.path.join(DIR, name), "wb").write(data)
def P(name): return os.path.join(DIR, name)
def osl(*a, inp=None):
    r = subprocess.run(["openssl", *a], capture_output=True, input=inp)
    return r.returncode, (r.stdout + r.stderr).decode(errors="replace")
def H384(*parts): return hashlib.sha384(b"".join(parts)).digest()
def T(label, n):                  # deterministic TEST vectors
    out = b""
    while len(out) < n: out += hashlib.sha512(("A5E attest4 TEST " + label).encode() + struct.pack(">I", len(out) // 64)).digest()
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
    nonce = H384(b"attest4 nonce " + tag.encode())[:32]
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


# ======================= attest4 helpers =======================
import shutil
HERE = os.path.dirname(os.path.abspath(__file__))
FW2X = os.path.abspath(os.path.join(HERE, "..", "..", "fw_2x"))
CA_DIR = os.path.abspath(os.environ.get("ATTEST_CA_DIR", os.path.join(HERE, "testca")))
TOOL = os.environ.get("ATTEST4_MANIFEST_TOOL") or os.path.join(os.environ.get("CALIPTRA_SW", "/nonexistent"),
                                                              "target", "release", "examples", "attest4_manifest")
if not os.access(TOOL, os.X_OK):
    raise SystemExit("manifest generator not found: build attest/emu/attest4_manifest.rs (see SIMULATION_2X 12.3) and set "
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

LABEL = H384(b"attest4 certify-key label")
# ======================= 0. info, reference certs, key / fuse configuration =======================
G = "info"
st, r, fe = mbox("FW_INFO_start", CMD["INFO"])
pl0_pauser, fw_svn, _, _, att_dis0 = struct.unpack_from("<5I", r, 8) if st == 1 else (None,) * 5
step(G, "FW_INFO: pl0_pauser = 1 (Nios is PL0), attestation_disabled = 0", pl0_pauser == 1 and att_dis0 == 0,
     "pl0_pauser=%s attestation_disabled=%s" % (pl0_pauser, att_dis0))
for nm, c in (("ldevid_ecc384", "LDEV"), ("fmc_alias_ecc384", "CERF"), ("rt_alias_ecc384", "CERR"),
              ("ldevid_mldsa87", "LDMC"), ("fmc_alias_mldsa87", "CMCF"), ("rt_alias_mldsa87", "CMCR")):
    st, r, fe = mbox("GET_" + nm.upper() + "_CERT", CMD[c])
    step(G, "%s certificate read" % nm, st == 1 and save_cert(nm, var_data(r)), "%d B" % len(var_data(r)) if st == 1 else "status=%d" % st)
st, r, fe = mbox("GET_IDEV_ECC384_INFO", CMD["IDEI"]); IDEV_E_PUB = r[8:104]
st2, r2, fe2 = mbox("GET_IDEV_MLDSA87_INFO", CMD["IDMI"]); IDEV_M_PUB = r2[8:8 + 2592]
step(G, "GET_IDEV_ECC384_INFO / GET_IDEV_MLDSA87_INFO return the IDevID public keys", st == 1 and st2 == 1 and len(IDEV_M_PUB) == 2592)
pub_pem("idevid_ecc384_pub", "ecc", IDEV_E_PUB); pub_pem("idevid_mldsa87_pub", "mldsa", IDEV_M_PUB)

G = "keys"   # manifest-key requirements vs. our fuse image and firmware bundle
FUSE = {}
for l in open(os.path.join(FW2X, "fuse_image_2x.hex")):
    v = int(l.strip(), 16); FUSE[(v >> 32) - 0x30000] = v & 0xFFFFFFFF
def fw(off, n): return [FUSE.get(off + 4 * i, 0) for i in range(n)]
BUNDLE = open(os.path.join(FW2X, "caliptra-fw-bundle.bin"), "rb").read()
vend_hash = hashlib.sha384(BUNDLE[12:1748]).digest(); own_hash = hashlib.sha384(BUNDLE[9168:11856]).digest()
step(G, "fuse FUSE_VENDOR_PK_HASH == SHA-384(bundle vendor key descriptors)", fw(0x260, 12) == list(struct.unpack(">12I", vend_hash)))
step(G, "fuse CPTRA_OWNER_PK_HASH == SHA-384(bundle owner ECC + ML-DSA keys)", fw(0x140, 12) == list(struct.unpack(">12I", own_hash)))
step(G, "fuse PQC key type == bundle pqc_key_type == 1 (ML-DSA-87) -> manifest PQC = ML-DSA", fw(0x38c, 1)[0] == 1 and BUNDLE[8] == 1)
vidx_e, vidx_p = struct.unpack_from("<I", BUNDLE, 1748)[0], struct.unpack_from("<I", BUNDLE, 1848)[0]
step(G, "bundle active vendor key index ECC 0 / PQC 0 (caliptra-sw VENDOR_*_KEY_0)", vidx_e == 0 and vidx_p == 0, "%d/%d" % (vidx_e, vidx_p))
SOC_MAX_SVN = fw(0x3a0, 1)[0]
summary["fuses"] = dict(vendor_pk_hash=vend_hash.hex(), owner_pk_hash=own_hash.hex(), pqc_key_type=fw(0x38c, 1)[0],
                        soc_manifest_max_svn=SOC_MAX_SVN, lifecycle="Production (attest_emu / RTL straps)",
                        anti_rollback_disable=0)
FW_VENDOR_ECC = swap_words(BUNDLE[1752:1848]); FW_VENDOR_MLDSA = BUNDLE[1852:4444]
FW_OWNER_ECC = swap_words(BUNDLE[9168:9264]); FW_OWNER_MLDSA = BUNDLE[9264:11856]
PEM_FVE = pub_pem("fw_vendor_ecc_key0", "ecc", FW_VENDOR_ECC); PEM_FVM = pub_pem("fw_vendor_mldsa_key0", "mldsa", FW_VENDOR_MLDSA)
PEM_FOE = pub_pem("fw_owner_ecc", "ecc", FW_OWNER_ECC); PEM_FOM = pub_pem("fw_owner_mldsa", "mldsa", FW_OWNER_MLDSA)
step(G, "manifest SVN rule: Production + anti-rollback on -> SVN must be <= max SoC-manifest fuse SVN (%d) and >= fuse SVN (0)" % SOC_MAX_SVN,
     SOC_MAX_SVN == 0, "max_svn=%d" % SOC_MAX_SVN)

# ======================= 1. manufacturing / provisioning =======================
G = "prov"
q0 = quote("base")
step(G, "QUOTE_PCRS_ECC384 baseline verifies with FMC Alias ECC key", q0["status"] == 1 and quote_sig_ok(q0, "ecc", "fmc_alias_ecc384"))
che0 = dpe_chain("ecc", "before"); chm0 = dpe_chain("mldsa", "before")
step(G, "DPE GetCertificateChain ECC before: [LDevID, FMC Alias, RT Alias]",
     che0 == [rdcert("ldevid_ecc384"), rdcert("fmc_alias_ecc384"), rdcert("rt_alias_ecc384")], "%d certs" % len(che0))
step(G, "DPE GetCertificateChain ML-DSA before: [LDevID, FMC Alias, RT Alias]",
     chm0 == [rdcert("ldevid_mldsa87"), rdcert("fmc_alias_mldsa87"), rdcert("rt_alias_mldsa87")], "%d certs" % len(chm0))
# --- vendor CA issues the IDevID certificates (cached by public key; CA private keys gitignored) ---
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
IDEV = {}
for alg, pub, n, ca in (("ecc", IDEV_E_PUB, 96, "ecc"), ("mldsa", IDEV_M_PUB, 2592, "mldsa")):
    sfx = "ecc384" if alg == "ecc" else "mldsa87"
    spki = ecc_spki(pub[:48], pub[48:]) if alg == "ecc" else mldsa_spki(pub)
    cert, tbs, sig, cache = idev_cert(alg, spki, P("ldevid_%s.der" % sfx))
    shutil.copy(os.path.join(CA_DIR, "test_mfg_ca_%s.pem" % ca), P("vendor_ca_%s.pem" % sfx))
    save_cert("idevid_%s_vendor_ca" % sfx, cert)
    IDEV[alg] = dict(cert=cert, tbs=tbs, sig=sig, cache=os.path.basename(cache))
    step(G, "vendor CA %s IDevID cert: subject key == GET_IDEV_%s_INFO key" % (alg.upper(), sfx.upper()),
         cert_spki_tail(P("idevid_%s_vendor_ca.pem" % sfx), n) == pub, os.path.basename(cache))
    ok, msg = verify_by("vendor_ca_" + sfx, "idevid_%s_vendor_ca" % sfx)
    step(G, "openssl: vendor CA -> IDevID %s" % alg.upper(), ok, msg)
    ok, msg = verify_by("idevid_%s_vendor_ca" % sfx, "ldevid_" + sfx)
    step(G, "openssl: IDevID -> LDevID %s (the ROM-issued LDevID is signed by the IDevID key)" % alg.upper(), ok, msg)
# GET_IDEV_*_CERT: Caliptra assembles the same cert from TBS + vendor-CA signature
t = IDEV["ecc"]; ri = int.from_bytes(children(tlv(t["sig"], 0)[1])[0][1], "big").to_bytes(48, "big")
si = int.from_bytes(children(tlv(t["sig"], 0)[1])[1][1], "big").to_bytes(48, "big")
st, r, fe = mbox("GET_IDEV_ECC384_CERT", CMD["IDEC"], u32(len(t["tbs"])) + ri + si + t["tbs"])
step(G, "GET_IDEV_ECC384_CERT (TBS + r,s) == vendor CA cert, byte for byte", st == 1 and var_data(r) == t["cert"], "%d B" % len(var_data(r)) if st == 1 else "st=%d" % st)
t = IDEV["mldsa"]
st, r, fe = mbox("GET_IDEV_MLDSA87_CERT", CMD["IDMC"], u32(len(t["tbs"])) + t["sig"] + b"\0" + t["tbs"])
step(G, "GET_IDEV_MLDSA87_CERT (TBS + sig) == vendor CA cert, byte for byte", st == 1 and var_data(r) == t["cert"], "%d B" % len(var_data(r)) if st == 1 else "st=%d" % st)
# --- POPULATE: rejects first ---
CE, CM = IDEV["ecc"]["cert"], IDEV["mldsa"]["cert"]
st, r, fe = mbox("POPULATE_IDEV_ECC384_CERT_size_1025", CMD["IDEP"], u32(1025) + CE.ljust(1024, b"\0"))
expect_fail(G, "POPULATE_IDEV_ECC384_CERT cert_size 1025 > 1024", st, fe, 0x000E0009)
st, r, fe = mbox("POPULATE_IDEV_ECC384_CERT_oversize", CMD["IDEP"], u32(len(CE)) + CE.ljust(1028, b"\0"))
expect_fail(G, "POPULATE_IDEV_ECC384_CERT request longer than the struct", st, fe, 0x000E0003)
st, r, fe = mbox("POPULATE_IDEV_MLDSA87_CERT_size_8193", CMD["IDMP"], u32(8193) + CM)
expect_fail(G, "POPULATE_IDEV_MLDSA87_CERT cert_size 8193 > 8192", st, fe, 0x000E0009)
# --- POPULATE both certs ---
st, r, fe = mbox("POPULATE_IDEV_ECC384_CERT", CMD["IDEP"], u32(len(CE)) + CE)
step(G, "POPULATE_IDEV_ECC384_CERT (%d B)" % len(CE), OK(st), "status=%d fwerr=%08x" % (st, fe))
st, r, fe = mbox("POPULATE_IDEV_MLDSA87_CERT", CMD["IDMP"], u32(len(CM)) + CM)
step(G, "POPULATE_IDEV_MLDSA87_CERT (%d B)" % len(CM), OK(st), "status=%d fwerr=%08x" % (st, fe))
che1 = dpe_chain("ecc", "after"); chm1 = dpe_chain("mldsa", "after")
step(G, "DPE GetCertificateChain ECC after: [IDevID, LDevID, FMC Alias, RT Alias]", che1 == [CE] + che0, "%d certs, %d B" % (len(che1), sum(map(len, che1))))
step(G, "DPE GetCertificateChain ML-DSA after: [IDevID, LDevID, FMC Alias, RT Alias]", chm1 == [CM] + chm0, "%d certs, %d B" % (len(chm1), sum(map(len, chm1))))
summary["chain_bytes"] = dict(ecc_before=sum(map(len, che0)), ecc_after=sum(map(len, che1)), mldsa_before=sum(map(len, chm0)), mldsa_after=sum(map(len, chm1)))
# --- the verifier's view: full chain from the vendor CA down to a DPE leaf ---
LE0 = certify("ecc", "provisioned"); LM0 = certify("mldsa", "provisioned")
for alg, lf in (("ecc", LE0), ("mldsa", LM0)):
    sfx = "ecc384" if alg == "ecc" else "mldsa87"
    if lf.get("cert") is None: step(G, "DPE CertifyKey %s leaf" % alg.upper(), False, str(lf)); continue
    ok, depth, msg = verify_chain(P("vendor_ca_%s.pem" % sfx), ["dpe_%s_chain_after_%d" % (alg, k) for k in range(4)], lf["name"], "fullchain_" + alg)
    step(G, "openssl verify %s: vendor CA -> IDevID -> LDevID -> FMC Alias -> RT Alias -> DPE leaf (6 certs)" % alg.upper(),
         ok and depth == 6, "%s, %d certs" % (msg, depth))
UEID = None
ue = cert_exts(rdcert("rt_alias_ecc384")).get("2.23.133.5.4.4")
if ue: UEID = tlv(tlv(ue["raw"], 0)[1], 0)[1]
step(G, "device UEID read from the RT Alias cert tcg-dice-Ueid extension (17 B: type byte + 4 serial-number fuse words)",
     UEID is not None and len(UEID) == 17, UEID.hex() if UEID else "")
lu = LE0.get("exts", {}).get("2.23.133.5.4.4") if LE0.get("exts") else None
LEAF_UEID = tlv(tlv(lu["raw"], 0)[1], 0)[1] if lu else None
step(G, "quirk: the DPE CertifyKey leaf's tcg-dice-Ueid extension carries the 48-B CertifyKey label, not the device UEID",
     LEAF_UEID == LABEL, LEAF_UEID.hex()[:24] + ".." if LEAF_UEID else "")
summary["ueid"] = UEID.hex() if UEID else None

# ======================= 2. owner / vendor image authorization =======================
G = "authz"
APP = T("Nios V application image v1.0.0", 64 * 1024); BIT = T("Agilex 5E core bitstream rev A", 128 * 1024)
BIT2 = T("Agilex 5E core bitstream rev B", 128 * 1024)
for nm, b in (("nios_app_v1.bin", APP), ("bitstream_revA.rbf", BIT), ("bitstream_revB.rbf", BIT2)): save(nm, b)
D_APP, D_BIT, D_BIT2 = H384(APP), H384(BIT), H384(BIT2)
FW_APP, FW_BIT, FW_DBG, FW_LOAD, FW_UEID, FW_UNKNOWN = 0x1001, 0x1002, 0x1003, 0x1004, 0xFFF, 0x2000
IMF_SRC_REQ, IMF_SRC_LOAD, IMF_IGNORE = 1, 2, 1 << 2
E_APP = (FW_APP, 0x0010, IMF_SRC_REQ, D_APP); E_BIT = (FW_BIT, 0x0020, IMF_SRC_REQ, D_BIT)
E_DBG = (FW_DBG, 0x0030, IMF_SRC_REQ | IMF_IGNORE, b"\0" * 48); E_LOAD = (FW_LOAD, 0x0040, IMF_SRC_LOAD, hashlib.sha384(b"").digest())
E_UEID = (FW_UEID, 0xFFFFFFFF, 0, (UEID or b"").ljust(48, b"\0"))
def gen(name, entries, svn=0, flags=1, keymode="good"):
    args = [TOOL, P(name + ".bin"), "1", str(svn), str(flags), keymode] + ["0x%x:0x%x:0x%x:%s" % (a, b, c, d.hex()) for a, b, c, d in entries]
    rr = subprocess.run(args, capture_output=True, text=True)
    if rr.returncode: raise SystemExit("manifest generator failed: " + rr.stderr)
    return open(P(name + ".bin"), "rb").read()
M1 = gen("manifest_m1", [E_APP, E_BIT, E_DBG, E_LOAD, E_UEID])
step(G, "manifest M1 built by caliptra-auth-man-gen: 'ATM2', 30,696 B, version 2, svn 0, flags 1, 5 entries",
     M1[:4] == b"ATM2" and len(M1) == 30696 and struct.unpack_from("<4I", M1, 4) == (24292, 2, 0, 1) and struct.unpack_from("<I", M1, 24292)[0] == 5,
     "%d B" % len(M1))
IMC = M1[24292:]
MVE, MVM = swap_words(M1[20:116]), M1[116:2708]; MOE, MOM = swap_words(M1[7432:7528]), M1[7528:10120]
PEM_MVE = pub_pem("man_vendor_ecc", "ecc", MVE); PEM_MVM = pub_pem("man_vendor_mldsa", "mldsa", MVM)
PEM_MOE = pub_pem("man_owner_ecc", "ecc", MOE); PEM_MOM = pub_pem("man_owner_mldsa", "mldsa", MOM)
def ecs(m, off): return swap_words(m[off:off + 48]), swap_words(m[off + 48:off + 96])
sigchk = [
    ("vendor FW ECC key 0 endorses manifest vendor keys (+version/svn/flags)", lambda: v_ecdsa_msg(PEM_FVE, M1[8:2708], *ecs(M1, 2708), "m1_vendor_endorse_ecc")),
    ("vendor FW ML-DSA key 0 endorses manifest vendor keys", lambda: v_mldsa_msg(PEM_FVM, M1[8:2708], M1[2804:2804 + 4627], "m1_vendor_endorse_mldsa")),
    ("owner FW ECC key endorses manifest owner keys", lambda: v_ecdsa_msg(PEM_FOE, M1[7432:10120], *ecs(M1, 10120), "m1_owner_endorse_ecc")),
    ("owner FW ML-DSA key endorses manifest owner keys", lambda: v_mldsa_msg(PEM_FOM, M1[7432:10120], M1[10216:10216 + 4627], "m1_owner_endorse_mldsa")),
    ("manifest vendor ECC key signs the IMC", lambda: v_ecdsa_msg(PEM_MVE, IMC, *ecs(M1, 14844), "m1_imc_vendor_ecc")),
    ("manifest vendor ML-DSA key signs the IMC", lambda: v_mldsa_msg(PEM_MVM, IMC, M1[14940:14940 + 4627], "m1_imc_vendor_mldsa")),
    ("manifest owner ECC key signs the IMC", lambda: v_ecdsa_msg(PEM_MOE, IMC, *ecs(M1, 19568), "m1_imc_owner_ecc")),
    ("manifest owner ML-DSA key signs the IMC", lambda: v_mldsa_msg(PEM_MOM, IMC, M1[19664:19664 + 4627], "m1_imc_owner_mldsa")),
]
for nm, fn in sigchk: step(G, "host openssl: " + nm, fn())
step(G, "manifest vendor keys (VENDOR_*_KEY_1) differ from the FW vendor key 0; manifest owner keys == FW owner keys",
     MVE != FW_VENDOR_ECC and MVM != FW_VENDOR_MLDSA and MOE == FW_OWNER_ECC and MOM == FW_OWNER_MLDSA)
RES = {0xDEADC0DE: "IMAGE_AUTHORIZED", 0x21523F21: "IMAGE_NOT_AUTHORIZED", 0x8BFB95CB: "IMAGE_HASH_MISMATCH", 0xC0DEDEAD: "IMAGE_AUTHORIZED_OWNER_ONLY"}
AUTH_OK, AUTH_NO, AUTH_MISMATCH = 0xDEADC0DE, 0x21523F21, 0x8BFB95CB
SKIP = 1
CTX = H384(b"attest4 AUTHORIZE_AND_STASH context")
def authz(name, fw_id, meas, flags=0, source=1, svn=0, size=0, raw=None):
    payload = raw if raw is not None else u32(fw_id) + meas + CTX + u32(svn, flags, source, size)
    st, r, fe = mbox("AUTHORIZE_AND_STASH_" + name, CMD["ATSH"], payload)
    res = struct.unpack_from("<I", r, 8)[0] if st == 1 and len(r) >= 12 else None
    return st, fe, res
def a_step(G, desc, got, want):
    st, fe, res = got
    return step(G, "%s -> %s" % (desc, RES.get(want, "%08x" % want)), st == 1 and res == want,
                "status=%d fwerr=%08x result=%s" % (st, fe, ("%08x %s" % (res, RES.get(res, "?"))) if res is not None else None))
def man(name, m, verify=True, size=None):
    st, r, fe = mbox(("VERIFY" if verify else "SET") + "_AUTH_MANIFEST_" + name, CMD["ATVM" if verify else "ATMN"],
                     u32(len(m) if size is None else size) + m)
    return st, fe
a_step(G, "AUTHORIZE_AND_STASH Nios app before any manifest", authz("before_manifest", FW_APP, D_APP, SKIP), AUTH_NO)
st, fe = man("m1", M1, verify=True)
step(G, "VERIFY_AUTH_MANIFEST M1 accepted", OK(st), "status=%d fwerr=%08x" % (st, fe))
a_step(G, "AUTHORIZE_AND_STASH Nios app after VERIFY only (VERIFY does not store the IMC)", authz("after_verify", FW_APP, D_APP, SKIP), AUTH_NO)
st, fe = man("m1", M1, verify=False)
step(G, "SET_AUTH_MANIFEST M1 accepted", OK(st), "status=%d fwerr=%08x" % (st, fe))
LE1 = certify("ecc", "after_set")
somx = [t for t in tcb_types(LE1) if t in (b"SOMV".hex(), b"VMOS".hex(), b"SOMO".hex(), b"OMOS".hex())]
step(G, "passive mode: SET_AUTH_MANIFEST creates no SOMV/SOMO DPE contexts (UpdateExisting only)",
     LE1.get("cert") is not None and not somx and len(LE1["tcb"]) == len(LE0["tcb"]), "%d TCB entries" % len(LE1.get("tcb", [])))
qa = quote("authz_before")
a_step(G, "AUTHORIZE_AND_STASH Nios app, correct digest, svn 1 (stash)", authz("app", FW_APP, D_APP, 0, svn=1), AUTH_OK)
qb = quote("authz_app")
save("pcr31_before_app.bin", pcr31(qa)); save("pcr31_after_app.bin", pcr31(qb))
step(G, "PCR31 == SHA-384(PCR31_old || D_app)", pcr31(qb) == H384(pcr31(qa), D_APP), pcr31(qb).hex()[:24] + "..")
step(G, "all other PCRs unchanged; quote verifies with FMC Alias ECC key",
     all(qa["pcrs"][i] == qb["pcrs"][i] for i in range(31)) and quote_sig_ok(qb, "ecc", "fmc_alias_ecc384"))
LE2 = certify("ecc", "after_app")
hit = tcb_find(LE2, u32(FW_APP))
step(G, "DPE leaf MultiTcbInfo: new entry type = fw_id 0x1001 (LE bytes 01100000), fwid = D_app, svn 1",
     len(hit) == 1 and D_APP.hex() in hit[0].get("fwids", []) and hit[0].get("svn") == 1, "%d TCB entries" % len(LE2.get("tcb", [])))
ok, msg = verify_by("rt_alias_ecc384", LE2.get("name", "x")) if LE2.get("cert") else (False, "")
step(G, "DPE leaf after stash still verifies against RT Alias ECC", ok, msg)
TAG = tt("AUTH")
st, r, fe = mbox("DPE_TAG_TCI_default_AUTH", CMD["TAGT"], DEFAULT_HANDLE + u32(TAG))
step(G, "DPE_TAG_TCI default (stashed app) context with tag 'AUTH'", OK(st), "status=%d fwerr=%08x" % (st, fe))
def get_tci(name, tag):
    st, r, fe = mbox(name, CMD["GTGD"], u32(tag))
    if st != 1: return None
    return dict(cum=r[8:56], cur=r[56:104], svn=struct.unpack_from("<I", r, 104)[0] if len(r) >= 108 else None)
tA = get_tci("DPE_GET_TAGGED_TCI_AUTH", TAG)
step(G, "DPE_GET_TAGGED_TCI 'AUTH': tci_current == D_app, tci_cumulative == SHA-384(0^48 || D_app), svn 1",
     tA is not None and tA["cur"] == D_APP and tA["cum"] == H384(b"\0" * 48, D_APP) and tA["svn"] == 1)
a_step(G, "AUTHORIZE_AND_STASH bitstream, correct digest, SKIP_STASH", authz("bit_skip", FW_BIT, D_BIT, SKIP), AUTH_OK)
qc = quote("authz_skip")
tA2 = get_tci("DPE_GET_TAGGED_TCI_AUTH_after_skip", TAG)
step(G, "SKIP_STASH: PCR31 unchanged and the default context is still the app context ('AUTH' still default)",
     qc["pcrs"] == qb["pcrs"] and tA2 == tA and certify("ecc", "after_skip").get("tcb") is not None and
     len(certify("ecc", "after_skip2")["tcb"]) == len(LE2["tcb"]))
a_step(G, "AUTHORIZE_AND_STASH bitstream, WRONG digest (rev B image)", authz("bit_wrong", FW_BIT, D_BIT2, 0, svn=2), AUTH_MISMATCH)
a_step(G, "AUTHORIZE_AND_STASH unknown FW ID 0x2000", authz("unknown_fwid", FW_UNKNOWN, D_APP, 0), AUTH_NO)
a_step(G, "AUTHORIZE_AND_STASH FW ID 0xFFF (device-UEID binding entry, never authorizable)", authz("ueid_fwid", FW_UEID, E_UEID[3], SKIP), AUTH_NO)
qd = quote("authz_rejects")
step(G, "denied requests (mismatch / unknown) stashed nothing: PCRs unchanged", qd["pcrs"] == qb["pcrs"])
a_step(G, "AUTHORIZE_AND_STASH FW ID 0x1003 (ignore_auth_check), arbitrary digest, SKIP_STASH", authz("ignore_auth", FW_DBG, T("any", 48), SKIP), AUTH_OK)
a_step(G, "AUTHORIZE_AND_STASH FW ID 0x1004 source=LoadAddress, image_size 0 (FW short-circuits to SHA-384(\"\"), no DMA)",
       authz("load_size0", FW_LOAD, b"\0" * 48, SKIP, source=2), AUTH_OK)
a_step(G, "AUTHORIZE_AND_STASH Nios app, manifest source = owner-only collection (none loaded)", authz("owner_src", FW_APP, D_APP, SKIP | (1 << 1)), AUTH_NO)
st, fe, res = authz("source_invalid_flags", FW_APP, D_APP, SKIP | (2 << 1))
expect_fail(G, "AUTHORIZE_AND_STASH manifest source 2 in flags bits 2:1", st, fe, 0x000E0009)
st, fe, res = authz("source_0", FW_APP, D_APP, SKIP, source=0)
expect_fail(G, "AUTHORIZE_AND_STASH image source 0 (Invalid)", st, fe, 0x000E004E)
st, fe, res = authz("short", 0, b"", raw=u32(FW_APP) + D_APP)
expect_fail(G, "AUTHORIZE_AND_STASH request too short", st, fe, 0x000E0003)
a_step(G, "AUTHORIZE_AND_STASH bitstream, correct digest, svn 2 (stash)", authz("bit", FW_BIT, D_BIT, 0, svn=2), AUTH_OK)
qe = quote("authz_bit")
step(G, "PCR31 == SHA-384(PCR31_prev || D_bitstream)", pcr31(qe) == H384(pcr31(qd), D_BIT))
LE3 = certify("ecc", "after_bit")
hb = tcb_find(LE3, u32(FW_BIT))
step(G, "DPE leaf: app (svn 1) and bitstream (svn 2) TCB entries, bitstream fwid = D_bitstream",
     len(hb) == 1 and D_BIT.hex() in hb[0].get("fwids", []) and hb[0].get("svn") == 2 and len(tcb_find(LE3, u32(FW_APP))) == 1,
     "types=%s" % tcb_types(LE3))
LM3 = certify("mldsa", "after_bit")
step(G, "ML-DSA DPE leaf shows the same two stashed measurements and verifies against RT Alias ML-DSA",
     LM3.get("cert") is not None and len(tcb_find(LM3, u32(FW_BIT))) == 1 and len(tcb_find(LM3, u32(FW_APP))) == 1
     and verify_by("rt_alias_mldsa87", LM3["name"])[0])
# STASH_MEASUREMENT contrast: unverified measurement accepted, reserved MCU RT FW ID refused
st, r, fe = mbox("STASH_MEASUREMENT_unverified", CMD["MEAS"], b"UNVF" + H384(b"unverified blob") + CTX + u32(0))
step(G, "contrast: STASH_MEASUREMENT accepts an arbitrary, unverified measurement (no manifest check)",
     st == 1 and struct.unpack_from("<I", r, 8)[0] == 0, "status=%d dpe_result=%s" % (st, struct.unpack_from("<I", r, 8)[0] if st == 1 else None))
st, r, fe = mbox("STASH_MEASUREMENT_mcu_rt_fwid", CMD["MEAS"], u32(2) + H384(b"forged MCU RT") + CTX + u32(0))
expect_fail(G, "contrast: STASH_MEASUREMENT with the reserved MCU RT FW ID 2 (only AUTHORIZE_AND_STASH may use it)", st, fe, 0x000E00B0)
summary["authz"] = dict(d_app=D_APP.hex(), d_bit=D_BIT.hex(), d_bit2=D_BIT2.hex(), pcr31_base=pcr31(qa).hex(),
                        pcr31_after_app=pcr31(qb).hex(), pcr31_after_bit=pcr31(qe).hex(), leaf_types=tcb_types(LE3),
                        tagged_auth=dict(cur=tA and tA["cur"].hex(), cum=tA and tA["cum"].hex(), svn=tA and tA["svn"]))

G = "tamper"
def flip(m, off, x=0x01): b = bytearray(m); b[off] ^= x; return bytes(b)
def setu32(m, off, v): b = bytearray(m); struct.pack_into("<I", b, off, v); return bytes(b)
def zero(m, off, n): b = bytearray(m); b[off:off + n] = b"\0" * n; return bytes(b)
cases = [
    ("marker", "marker byte flipped", flip(M1, 0), 0x000E0045),
    ("preamble_size", "preamble size field changed", flip(M1, 4), 0x000E0046),
    ("truncated_preamble", "manifest cut inside the preamble (24,000 B)", M1[:24000], 0x000E004B),
    ("svn_field", "svn field 0 -> 1 (checked before any signature)", setu32(M1, 12, 1), 0x000B002C),
    ("flags_field", "flags field 1 -> 5 (vendor-signed field)", setu32(M1, 16, 5), 0x000E0047),
    ("vendor_ecc_key", "manifest vendor ECC key byte", flip(M1, 25), 0x000E0047),
    ("vendor_mldsa_key", "manifest vendor ML-DSA key byte (also covered by the ECC endorsement)", flip(M1, 121), 0x000E0047),
    ("vendor_endorse_mldsa_sig", "vendor ML-DSA endorsement signature byte", flip(M1, 2809), 0x000E0065),
    ("owner_ecc_key", "manifest owner ECC key byte", flip(M1, 7437), 0x000E0049),
    ("owner_endorse_mldsa_sig", "owner ML-DSA endorsement signature byte", flip(M1, 10221), 0x000E0068),
    ("imc_digest", "IMC: Nios app digest byte", flip(M1, 24292 + 4 + 32), 0x000E0047),
    ("imc_vendor_mldsa_sig", "IMC vendor ML-DSA signature byte", flip(M1, 14945), 0x000E0065),
    ("imc_owner_ecc_sig", "IMC owner ECC signature byte", flip(M1, 19573), 0x000E0049),
    ("imc_owner_mldsa_sig", "IMC owner ML-DSA signature byte", flip(M1, 19669), 0x000E0068),
    ("imc_vendor_sig_zero", "IMC vendor ECC signature zeroed (flags bit 0 set)", zero(M1, 14844, 96), 0x000E0047),
    ("imc_truncated", "IMC truncated to the 5 used entries (signature covers all 80 slots)", M1[:24292 + 4 + 80 * 5], 0x000E0047),
    ("entry_count_81", "IMC entry_count 81 (> 80)", setu32(M1, 24292, 81), 0x000E004D),
    ("entry_count_0", "IMC entry_count 0", setu32(M1, 24292, 0), 0x000E004D),
]
TAMPER = []
for tag, desc, m, code in cases:
    st, fe = man("tampered_" + tag, m, verify=True)
    expect_fail(G, "VERIFY_AUTH_MANIFEST tampered: " + desc, st, fe, code)
    TAMPER.append(dict(case=tag, desc=desc, status=st, fwerr="%08x" % fe, name=ERR.get(fe)))
st, fe = man("size_gt_max", M1, size=34 * 1024 + 1); expect_fail(G, "VERIFY_AUTH_MANIFEST manifest_size 34 KiB + 1", st, fe, 0x000E0009)
st, fe = man("size_gt_payload", M1, size=len(M1) + 100); expect_fail(G, "VERIFY_AUTH_MANIFEST manifest_size larger than the data sent", st, fe, 0x000E0009)
resigned = [
    ("svn1", "re-signed with svn 1 (> max SoC-manifest fuse SVN 0)", dict(entries=[E_APP], svn=1), 0x000B002C),
    ("wrong_vendor_fw_key", "vendor keys endorsed by VENDOR key 1, not the bundle's key 0", dict(entries=[E_APP], keymode="wrong_vendor_fw"), 0x000E0047),
    ("wrong_owner_fw_key", "owner keys endorsed by a key that is not the bundle owner key", dict(entries=[E_APP], keymode="wrong_owner_fw"), 0x000E0049),
    ("wrong_ueid", "device-binding entry for another device (UEID last byte changed)",
     dict(entries=[E_APP, (FW_UEID, 0xFFFFFFFF, 0, flip((UEID or b"\0" * 17).ljust(48, b"\0"), 16))]), 0x000E00B4),
    ("dup_fwid", "two entries with FW ID 0x1001", dict(entries=[E_APP, (FW_APP, 0x11, 1, D_BIT)]), 0x000E0053),
    ("empty", "no entries", dict(entries=[]), 0x000E004D),
    ("debug_flag", "flags = 3 (DEBUG_IMAGE): needs subsystem mode + SS_DEBUG_INTENT", dict(entries=[E_APP], flags=3), 0x000E00B2),
    ("debug_no_vendor", "flags = 2 (DEBUG_IMAGE without VENDOR_SIGNATURE_REQUIRED)", dict(entries=[E_APP], flags=2), 0x000E00B3),
]
for tag, desc, kw, code in resigned:
    m = gen("manifest_" + tag, **kw)
    st, fe = man(tag, m, verify=True)
    expect_fail(G, "VERIFY_AUTH_MANIFEST " + desc, st, fe, code)
    TAMPER.append(dict(case=tag, desc=desc, status=st, fwerr="%08x" % fe, name=ERR.get(fe)))
M0 = gen("manifest_owner_imc_only", [E_APP], flags=0)
st, fe = man("flags0", M0, verify=True)
step(G, "flags = 0 (vendor IMC signature not required): vendor IMC signature fields are zero and VERIFY passes",
     OK(st) and M0[14844:14844 + 96 + 4628] == b"\0" * (96 + 4628), "status=%d fwerr=%08x" % (st, fe))
st, fe = man("flags0_owner_imc_flip", flip(M0, 19573), verify=True)
expect_fail(G, "flags = 0 but owner IMC ECC signature broken (owner signature always required)", st, fe, 0x000E0049)
# a failed SET leaves the stored manifest in place
st, fe = man("tampered_imc_owner_ecc_sig", flip(M1, 19573), verify=False)
expect_fail(G, "SET_AUTH_MANIFEST tampered (IMC owner ECC signature)", st, fe, 0x000E0049)
a_step(G, "after the rejected SET, M1 is still in force: Nios app (SKIP_STASH)", authz("after_bad_set", FW_APP, D_APP, SKIP), AUTH_OK)
# replacing the manifest: M2 authorizes only bitstream rev B
M2 = gen("manifest_m2", [(FW_BIT, 0x0020, IMF_SRC_REQ, D_BIT2), E_UEID])
st, fe = man("m2", M2, verify=False)
step(G, "SET_AUTH_MANIFEST M2 (bitstream rev B only) replaces M1", OK(st), "status=%d fwerr=%08x" % (st, fe))
a_step(G, "under M2: Nios app", authz("m2_app", FW_APP, D_APP, SKIP), AUTH_NO)
a_step(G, "under M2: bitstream rev A digest", authz("m2_bitA", FW_BIT, D_BIT, SKIP), AUTH_MISMATCH)
a_step(G, "under M2: bitstream rev B digest", authz("m2_bitB", FW_BIT, D_BIT2, SKIP), AUTH_OK)
st, fe = man("m1_again", M1, verify=False)
step(G, "SET_AUTH_MANIFEST M1 again", OK(st), "status=%d fwerr=%08x" % (st, fe))
a_step(G, "under M1 again: Nios app", authz("m1_again_app", FW_APP, D_APP, SKIP), AUTH_OK)
summary["tamper"] = TAMPER

# ======================= 3. exported CDI signing =======================
G = "export"
DC_EXPORT, DC_CREATE_CERT, DC_RETAIN, DC_CHANGE_LOC = 1 << 23, 1 << 22, 1 << 29, 1 << 27
EXP_FLAGS = DC_EXPORT | DC_CREATE_CERT | DC_RETAIN
EXP_DATA = H384(b"attest4 exported-CDI measurement: Nios TLS/SPDM responder key")
def export(name, alg, flags=EXP_FLAGS, data=EXP_DATA, tci=tt("EXPC")):
    prof = P384 if alg == "ecc" else MLDSA87
    st, d, fe, ds = dpe("DPE_%s_DERIVE_EXPORT_CDI_%s" % (alg.upper(), name), 0x08, DEFAULT_HANDLE + data + u32(flags, tci, 0, 0), prof)
    if st != 1 or ds != 0: return dict(status=st, fwerr=fe, dpe=ds)
    n = struct.unpack_from("<I", d, 76)[0]
    e = dict(status=st, fwerr=fe, dpe=ds, handle=d[12:28], parent=d[28:44], cdi=d[44:76], cert=d[80:80 + n])
    e["name"] = "exported_%s_%s" % (alg, name); save_cert(e["name"], e["cert"]); save(e["name"] + "_handle.bin", e["cdi"])
    e["pub"] = cert_spki_tail(P(e["name"] + ".pem"), 96 if alg == "ecc" else 2592)
    return e
def swee(name, cdi, digest, raw=None):
    st, r, fe = mbox("SIGN_WITH_EXPORTED_ECDSA_" + name, CMD["SWEE"], raw if raw is not None else cdi + digest)
    if st != 1: return dict(status=st, fwerr=fe)
    return dict(status=st, fwerr=fe, pub=r[8:104], r=r[104:152], s=r[152:200])
def swml(name, cdi, tbs, sign_type=1, size=None):
    st, r, fe = mbox("SIGN_WITH_EXPORTED_MLDSA_" + name, CMD["SWML"], cdi + u32(sign_type, len(tbs) if size is None else size) + tbs.ljust(1024, b"\0")[:1024])
    if st != 1: return dict(status=st, fwerr=fe)
    return dict(status=st, fwerr=fe, pub=r[8:2600], sig=r[2600:2600 + 4627])
def rvch(name, cdi, raw=None):
    st, r, fe = mbox("REVOKE_EXPORTED_CDI_HANDLE_" + name, CMD["RVCH"], raw if raw is not None else cdi)
    return st, fe
CHAL = H384(b"attest4 verifier nonce")[:32]
TBS = b"attest4 SPDM-style challenge | verifier nonce=" + CHAL.hex().encode() + b" | responder=Nios V on A5E | transcript v1"
save("challenge_tbs.bin", TBS); TBS_D = H384(TBS)
LE4 = certify("ecc", "before_export")
E1 = export("1", "ecc")
ok1 = step(G, "ECC DeriveContext EXPORT_CDI|CREATE_CERTIFICATE|RETAIN_PARENT from PL0 default context: DPE status 0",
           E1.get("cert") is not None, "status=%s dpe=%s" % (E1.get("status"), E1.get("dpe")))
if ok1:
    step(G, "export response: new handle = invalid (all FF), parent handle = default, 32-B exported CDI handle != 0",
         E1["handle"] == b"\xff" * 16 and E1["parent"] == DEFAULT_HANDLE and any(E1["cdi"]),
         "handle=%s parent=%s cdi=%s.." % (E1["handle"].hex()[:8], E1["parent"].hex()[:8], E1["cdi"].hex()[:16]))
    ok, msg = verify_by("rt_alias_ecc384", E1["name"]); step(G, "exported ECC cert chains to RT Alias ECC (openssl)", ok, msg)
    ok, depth, msg = verify_chain(P("vendor_ca_ecc384.pem"), ["dpe_ecc_chain_after_%d" % k for k in range(4)], E1["name"], "fullchain_exported_ecc")
    step(G, "exported ECC cert: full chain vendor CA -> IDevID -> LDevID -> FMC -> RT -> exported cert", ok and depth == 6, msg)
    ex = cert_exts(E1["cert"]); mt = ex.get("2.23.133.5.4.5", {}).get("multi_tcb_info", [])
    summary["exported_ecc_cert_tcb_types"] = [t.get("type_hex") for t in mt]
    step(G, "exported cert MultiTcbInfo == the default context's TCI chain (RTMR, CCIV, app, bitstream, UNVF)",
         [t.get("type_hex") for t in mt] == tcb_types(LE4) and any(D_APP.hex() in t.get("fwids", []) for t in mt)
         and any(D_BIT.hex() in t.get("fwids", []) for t in mt), "%d TCB entries" % len(mt))
    step(G, "quirk: the export DeriveContext 'data' is not measured (no TCB entry for it; the export creates no context)",
         not any(EXP_DATA.hex() in t.get("fwids", []) for t in mt))
    lf = certify("ecc", "after_export")
    step(G, "RETAIN_PARENT: the default context survives the export (CertifyKey default OK, same TCB list)",
         lf.get("cert") is not None and tcb_types(lf) == tcb_types(LE4), "dpe=%s" % lf.get("dpe"))
E1b = export("while_active", "ecc", data=H384(b"second export"), tci=tt("EXP2"))
summary["export_while_active"] = dict(status=E1b.get("status"), dpe="%08x" % E1b["dpe"] if E1b.get("dpe") is not None else None, fwerr="%08x" % E1b.get("fwerr", 0))
step(G, "second export while one exported CDI is active is refused (one exported-CDI slot; DPE crypto error)",
     E1b.get("cert") is None and E1b.get("status") == 1 and E1b.get("dpe") not in (None, 0), "dpe=%s" % summary["export_while_active"]["dpe"])
for tag, fl, desc in (("no_cert", DC_EXPORT | DC_RETAIN, "EXPORT_CDI without CREATE_CERTIFICATE"),
                      ("change_loc", EXP_FLAGS | DC_CHANGE_LOC, "EXPORT_CDI with CHANGE_LOCALITY")):
    e = export(tag, "ecc", flags=fl, tci=tt("EXP3"))
    summary["export_" + tag] = dict(status=e.get("status"), dpe="%08x" % e["dpe"] if e.get("dpe") is not None else None)
    step(G, "DPE rejects %s (DPE InvalidArgument 0x3)" % desc, e.get("status") == 1 and e.get("dpe") == 0x3, "dpe=%s" % summary["export_" + tag]["dpe"])
if ok1:
    s1 = swee("e1", E1["cdi"], TBS_D)
    ok = step(G, "SIGN_WITH_EXPORTED_ECDSA over SHA-384(challenge TBS)", s1["status"] == 1, "status=%d fwerr=%08x" % (s1["status"], s1["fwerr"]))
    if ok:
        step(G, "SIGN_WITH_EXPORTED_ECDSA: returned public key == exported cert public key", s1["pub"] == E1["pub"])
        pem = P(E1["name"] + "_pub.pem"); osl("x509", "-in", P(E1["name"] + ".pem"), "-noout", "-pubkey", "-out", pem)
        step(G, "openssl dgst -sha384 -verify (exported cert key) over the challenge TBS", v_ecdsa_msg(pem, TBS, s1["r"], s1["s"], "swee_e1"))
        save("swee_e1_r.bin", s1["r"]); save("swee_e1_s.bin", s1["s"])
        s1b = swee("e1_again", E1["cdi"], TBS_D)
        summary["ecdsa_deterministic"] = s1b.get("r") == s1["r"]
        step(G, "second signature over the same TBS also verifies", s1b["status"] == 1 and v_ecdsa_msg(pem, TBS, s1b["r"], s1b["s"], "swee_e1b"),
             "same r,s as the first: %s" % summary["ecdsa_deterministic"])
    sm = swml("ecc_handle_raw", E1["cdi"], TBS)
    summary["mldsa_sign_with_ecc_exported_handle"] = dict(status=sm["status"], fwerr="%08x" % sm["fwerr"])
    if sm["status"] == 1:
        SM_PUB = sm["pub"]
        pm = pub_pem("swml_ecc_handle_pub", "mldsa", sm["pub"])
        step(G, "SIGN_WITH_EXPORTED_MLDSA also accepts the ECC-exported handle; signature verifies with the returned ML-DSA key",
             v_mldsa_msg(pm, TBS, sm["sig"], "swml_ecc_handle"))
    else:
        step(G, "SIGN_WITH_EXPORTED_MLDSA with the ECC-exported handle", False, "status=%d fwerr=%08x" % (sm["status"], sm["fwerr"]))
    st = swee("short", None, None, raw=E1["cdi"] + TBS_D[:47])
    expect_fail(G, "SIGN_WITH_EXPORTED_ECDSA request 1 B short", st["status"], st["fwerr"], 0x000E0009)
BAD = T("never exported", 32)
s = swee("bad_handle", BAD, TBS_D); expect_fail(G, "SIGN_WITH_EXPORTED_ECDSA with a handle that was never exported", s["status"], s["fwerr"], 0x000E0057)
s = swml("bad_handle", BAD, TBS); expect_fail(G, "SIGN_WITH_EXPORTED_MLDSA with a handle that was never exported", s["status"], s["fwerr"], 0x000E009C)
G = "revoke"
if ok1:
    st, fe = rvch("e1", E1["cdi"]); step(G, "REVOKE_EXPORTED_CDI_HANDLE E1", OK(st), "status=%d fwerr=%08x" % (st, fe))
    s = swee("e1_revoked", E1["cdi"], TBS_D); expect_fail(G, "SIGN_WITH_EXPORTED_ECDSA with the revoked handle", s["status"], s["fwerr"], 0x000E0057)
    s = swml("e1_revoked", E1["cdi"], TBS); expect_fail(G, "SIGN_WITH_EXPORTED_MLDSA with the revoked handle", s["status"], s["fwerr"], 0x000E009C)
    st, fe = rvch("e1_again", E1["cdi"]); expect_fail(G, "REVOKE_EXPORTED_CDI_HANDLE E1 a second time", st, fe, 0x000E0060)
st, fe = rvch("bad_handle", BAD); expect_fail(G, "REVOKE_EXPORTED_CDI_HANDLE unknown handle", st, fe, 0x000E0060)
st, fe = rvch("short", None, raw=BAD[:31]); expect_fail(G, "REVOKE_EXPORTED_CDI_HANDLE request 1 B short", st, fe, 0x000E0009)
EXP_DATA2 = H384(b"attest4 a different export measurement")
E2 = export("2", "ecc", data=EXP_DATA2)
if step(G, "re-export after revocation succeeds (slot free again)", E2.get("cert") is not None, "dpe=%s" % E2.get("dpe")):
    step(G, "E2: new random handle != E1 handle", ok1 and E2["cdi"] != E1["cdi"])
    summary["reexport_same_key"] = bool(ok1 and E2["pub"] == E1["pub"])
    step(G, "E2 (different DeriveContext data) cert key == E1 cert key: the exported CDI depends only on the parent TCI chain; the handle is random",
         summary["reexport_same_key"])
    s2 = swee("e2", E2["cdi"], TBS_D)
    pem2 = P(E2["name"] + "_pub.pem"); osl("x509", "-in", P(E2["name"] + ".pem"), "-noout", "-pubkey", "-out", pem2)
    step(G, "SIGN_WITH_EXPORTED_ECDSA with E2 verifies", s2["status"] == 1 and v_ecdsa_msg(pem2, TBS, s2["r"], s2["s"], "swee_e2"))
    if ok1:
        s = swee("e1_after_reexport", E1["cdi"], TBS_D)
        expect_fail(G, "old E1 handle stays dead after re-export", s["status"], s["fwerr"], 0x000E0057)
    st, fe = rvch("e2", E2["cdi"]); step(G, "REVOKE_EXPORTED_CDI_HANDLE E2", OK(st), "status=%d fwerr=%08x" % (st, fe))
G = "mldsa"
E3 = export("3", "mldsa")
ok3 = step(G, "ML-DSA DeriveContext EXPORT_CDI|CREATE_CERTIFICATE|RETAIN_PARENT (INVOKE_DPE_MLDSA87)", E3.get("cert") is not None,
           "status=%s dpe=%s fwerr=%s" % (E3.get("status"), E3.get("dpe"), "%08x" % E3.get("fwerr", 0)))
if ok3:
    ok, msg = verify_by("rt_alias_mldsa87", E3["name"]); step(G, "exported ML-DSA cert chains to RT Alias ML-DSA (openssl)", ok, msg)
    ok, depth, msg = verify_chain(P("vendor_ca_mldsa87.pem"), ["dpe_mldsa_chain_after_%d" % k for k in range(4)], E3["name"], "fullchain_exported_mldsa")
    step(G, "exported ML-DSA cert: full chain vendor CA -> IDevID -> LDevID -> FMC -> RT -> exported cert", ok and depth == 6, msg)
    pem3 = P(E3["name"] + "_pub.pem"); osl("x509", "-in", P(E3["name"] + ".pem"), "-noout", "-pubkey", "-out", pem3)
    s3 = swml("e3_raw", E3["cdi"], TBS)
    if step(G, "SIGN_WITH_EXPORTED_MLDSA raw (sign_type 1) over the challenge TBS", s3["status"] == 1, "status=%d fwerr=%08x" % (s3["status"], s3["fwerr"])):
        step(G, "returned ML-DSA public key == exported cert public key", s3["pub"] == E3["pub"])
        step(G, "openssl pkeyutl -verify -rawin (exported cert key) over the TBS", v_mldsa_msg(pem3, TBS, s3["sig"], "swml_e3_raw"))
    tr = hashlib.shake_256(E3["pub"]).digest(64); MU = hashlib.shake_256(tr + b"\x00\x00" + TBS).digest(64)
    save("swml_e3_mu.bin", MU)
    s4 = swml("e3_mu", E3["cdi"], MU, sign_type=0)
    step(G, "SIGN_WITH_EXPORTED_MLDSA mu (sign_type 0, mu = SHAKE256(SHAKE256(pk,64) || 00 00 || TBS)) verifies as a pure ML-DSA signature over TBS",
         s4["status"] == 1 and v_mldsa_msg(pem3, TBS, s4["sig"], "swml_e3_mu"), "status=%d fwerr=%08x" % (s4["status"], s4["fwerr"]))
    s = swml("bad_type", E3["cdi"], TBS, sign_type=2); expect_fail(G, "SIGN_WITH_EXPORTED_MLDSA sign_type 2", s["status"], s["fwerr"], 0x000E0009)
    s = swml("mu_63", E3["cdi"], MU[:63], sign_type=0); expect_fail(G, "SIGN_WITH_EXPORTED_MLDSA mu with tbs_size 63", s["status"], s["fwerr"], 0x000E0009)
    s = swml("size_1025", E3["cdi"], TBS, size=1025); expect_fail(G, "SIGN_WITH_EXPORTED_MLDSA raw tbs_size 1025 > 1024", s["status"], s["fwerr"], 0x000E0009)
    se = swee("mldsa_handle", E3["cdi"], TBS_D)
    step(G, "the ML-DSA key derived from the ECC-exported handle == the key in the ML-DSA export cert (one exported CDI, two labels)",
         sm.get("pub") is not None and sm["pub"] == E3["pub"])
    summary["ecdsa_sign_with_mldsa_exported_handle"] = dict(status=se["status"], same_key_as_ecc_export=bool(se.get("pub") and ok1 and se["pub"] == E1["pub"]))
    if se["status"] == 1:
        pe = pub_pem("swee_mldsa_handle_pub", "ecc", se["pub"])
        step(G, "SIGN_WITH_EXPORTED_ECDSA also accepts the ML-DSA-exported handle; signature verifies with the returned ECC key",
             v_ecdsa_digest(pe, TBS_D, se["r"], se["s"], "swee_mldsa_handle"), "same key as the ECC export: %s" % summary["ecdsa_sign_with_mldsa_exported_handle"]["same_key_as_ecc_export"])
    st, fe = rvch("e3", E3["cdi"]); step(G, "REVOKE_EXPORTED_CDI_HANDLE E3", OK(st), "status=%d fwerr=%08x" % (st, fe))
    s = swml("e3_revoked", E3["cdi"], TBS); expect_fail(G, "SIGN_WITH_EXPORTED_MLDSA with the revoked ML-DSA handle", s["status"], s["fwerr"], 0x000E009C)
# lifecycle detail: export WITHOUT RETAIN_PARENT destroys the (childless) default context
G = "lifecycle"
E4 = export("no_retain", "ecc", flags=DC_EXPORT | DC_CREATE_CERT, tci=tt("EXP4"))
step(G, "export without RETAIN_PARENT succeeds", E4.get("cert") is not None, "dpe=%s" % E4.get("dpe"))
lf = certify("ecc", "after_no_retain")
summary["certify_after_no_retain"] = dict(status=lf.get("status"), dpe="%08x" % lf["dpe"] if lf.get("dpe") is not None else None)
step(G, "...and the default context is gone afterwards (CertifyKey default -> DPE InvalidLocality 0x81: no context left at PL0)",
     lf.get("cert") is None and lf.get("dpe") == 0x81, "dpe=%s" % summary["certify_after_no_retain"]["dpe"])
if E4.get("cert") is not None:
    s = swee("e4", E4["cdi"], TBS_D)
    step(G, "the exported CDI itself still works (SIGN_WITH_EXPORTED_ECDSA)", s["status"] == 1 and s["pub"] == E4["pub"])
    st, fe = rvch("e4", E4["cdi"]); step(G, "REVOKE_EXPORTED_CDI_HANDLE E4", OK(st), "status=%d fwerr=%08x" % (st, fe))
st, r, fe = mbox("STASH_MEASUREMENT_after_no_retain", CMD["MEAS"], b"LATE" + H384(b"late") + CTX + u32(0))
summary["stash_after_no_retain"] = dict(status=st, fwerr="%08x" % fe, dpe_result=struct.unpack_from("<I", r, 8)[0] if st == 1 else None)
step(G, "with no default context left, STASH_MEASUREMENT returns dpe_result 0x81 (InvalidLocality)", st == 1 and struct.unpack_from("<I", r, 8)[0] == 0x81,
     "status=%d fwerr=%08x dpe_result=%s" % (st, fe, summary["stash_after_no_retain"]["dpe_result"]))

# ======================= 4. quirks =======================
G = "quirks"
cap_e = 4096 - sum(map(len, che1)) >= len(CE)
st, r, fe = mbox("POPULATE_IDEV_ECC384_CERT_again", CMD["IDEP"], u32(len(CE)) + CE)
che2 = dpe_chain("ecc", "double")
if cap_e:
    step(G, "POPULATE_IDEV_ECC384_CERT a second time is ACCEPTED (no already-populated guard): chain now has the IDevID twice",
         OK(st) and che2 == [CE, CE] + che0, "status=%d, %d certs, %d B" % (st, len(che2), sum(map(len, che2))))
else:
    expect_fail(G, "POPULATE_IDEV_ECC384_CERT a second time (chain would exceed 4096 B)", st, fe, 0x000E001C)
st, r, fe = mbox("POPULATE_IDEV_MLDSA87_CERT_again", CMD["IDMP"], u32(len(CM)) + CM)
if 32768 - sum(map(len, chm1)) >= len(CM):
    step(G, "POPULATE_IDEV_MLDSA87_CERT a second time accepted", OK(st))
else:
    expect_fail(G, "POPULATE_IDEV_MLDSA87_CERT a second time (chain %d B + %d B > 32 KiB)" % (sum(map(len, chm1)), len(CM)), st, fe, 0x000E001C)
# DMA image source with a non-zero size (last command: the DMA path needs an AXI image the passive setup does not have).
# Sent by default on the emulator only (no TB_LOG); on the RTL set ATTEST4_DMA_PROBE=1 to send it.
if os.environ.get("ATTEST4_DMA_PROBE", "0" if TB_LOG else "1") != "1":
    summary["load_address_dma_probe"] = dict(status=None, note="not sent (ATTEST4_DMA_PROBE != 1)")
else:
  try:
      st, r, fe = mbox("AUTHORIZE_AND_STASH_load_dma_probe", CMD["ATSH"], u32(FW_LOAD) + b"\0" * 48 + CTX + u32(0, SKIP, 2, 4096), timeout_s=30)
      res = struct.unpack_from("<I", r, 8)[0] if st == 1 and len(r) >= 12 else None
      summary["load_address_dma_probe"] = dict(status=st, fwerr="%08x" % fe, name=ERR.get(fe), result=res and "%08x" % res)
  except SystemExit as e:
      summary["load_address_dma_probe"] = dict(status=None, note="no response in 30 s: " + str(e))
print("[attest4] LoadAddress DMA probe (recorded, not a pass/fail check): %s" % summary["load_address_dma_probe"])

# end of command stream
open(os.path.join(DIR, ".req.tmp"), "w").write("00000000\n00000000\n")
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
summary["steps"] = RESULTS; summary["log"] = LOG
summary["wall_s"] = round(time.time() - T_START, 1)
summary["all_pass"] = bool(RESULTS) and all(s["result"] == "PASS" for s in RESULTS)
groups = {}
for s in RESULTS:
    g = groups.setdefault(s["group"], [0, 0]); g[0 if s["result"] == "PASS" else 1] += 1
summary["groups"] = {k_: dict(passed=v[0], failed=v[1]) for k_, v in groups.items()}
json.dump(summary, open(os.path.join(DIR, "attest4_summary.json"), "w"), indent=1, default=lambda o: o.hex() if isinstance(o, bytes) else str(o))
for e in LOG: print("[attest4]   %03d %-44s status=%d fwerr=%s cycles=%s" % (e["n"], e["name"], e["status"], e["fw_err_non_fatal"], e.get("cycles", "-")))
print("[attest4] per group: " + ", ".join("%s %d/%d" % (k_, v[0], v[0] + v[1]) for k_, v in groups.items()))
fails = [s["step"] for s in RESULTS if s["result"] != "PASS"]
for f in fails: print("[attest4] FAILED: " + f)
print("[attest4] done, %d commands, %d steps, %.1f s; %s" % (n_req, len(RESULTS), summary["wall_s"],
      "ATTEST4 PASS" if summary["all_pass"] else "ATTEST4 FAIL (%d)" % len(fails)))
sys.exit(0 if summary["all_pass"] else 1)

#!/usr/bin/env python3
"""Caliptra 2.x attestation/DPE mailbox exercise 3 (Nios-host side): PCR extend + reset counters, DPE TCI tagging,
CERTIFY_KEY_EXTENDED (ECC/ML-DSA, X.509 + CSR), CERTIFY_KEY_CHUNKS, ADD_SUBJECT_ALT_NAME (DMTF OtherName),
REALLOCATE_DPE_CONTEXT_LIMITS and DISABLE_ATTESTATION (run last).
Same file protocol / mailbox framing as crypto2_driver.py (tb_nios2x_top_fw +test=attest, or the sw-emulator
attest_emu example):  req_NNN.hex -> resp_NNN.hex + resp_NNN.done, cmd 0 ends the stream.
Commands (caliptra-sw fw-2.1.4 = dd1e79d, api/src/mailbox.rs + runtime/src/*.rs, caliptra-dpe f2b7121). u32 = LE.
  EXTEND_PCR "PCRE" pcr_idx | data[48]           PCR0-3 reserved (0x000E003C), idx>31 0x000E003D, idx>255 0x000E0009
  INCREMENT_PCR_RESET_COUNTER "PCRR" index       idx>31 -> 0x000E0009
  QUOTE_PCRS_ECC384 "PCRQ" / _MLDSA87 "PCRM" nonce[32] -> pcrs[32][48] | nonce | reset_ctrs[32] | digest | sig
  DPE_TAG_TCI 0x54514754 ("TQGT", commented "TAGT") handle[16] | tag ; DPE_GET_TAGGED_TCI "GTGD" tag -> tci_cumulative[48] | tci_current[48] | svn
  CERTIFY_KEY_EXTENDED_ECC384 "CKEX" flags(bit31 DMTF_OTHER_NAME) | dpe_certify_key_cmd[72]
  CERTIFY_KEY_EXTENDED_MLDSA87 "CKXM" flags(bit30 EXTERNAL_AXI_RESPONSE) | axi_response[12] | dpe_certify_key_cmd[72]
       -> size | DPE CertifyKey resp (DPER hdr | new handle[16] | pub (x,y | ML-DSA pk) | cert_size | cert/CSR)
  CERTIFY_KEY_CHUNKS "CKCH" flags(bit31 USE_MLDSA) | reserved | max_size | offset | dpe_certify_key_cmd[72]
       -> handle[16] | chunk_len | remaining | chunk          (chunks of the same DPE CertifyKey response)
  ADD_SUBJECT_ALT_NAME "ALTN" size | ascii "a:b:c" (exactly 2 ':', <= 128 B)
  REALLOCATE_DPE_CONTEXT_LIMITS "RCTX" pl0_limit -> new_pl0 | new_pl1   (pl0 in [2, 64], pl0 + pl1 = 64)
  DISABLE_ATTESTATION "DSBL" (erases the RT CDI/keys, replaces them with a KDF of zeros, sets FW_INFO flag)
  DPE CertifyKey cmd: handle[16] | flags | format(0 X.509, 1 CSR) | label[48]
  DPE DeriveContext cmd: handle[16] | data[48] | flags | tci_type | target_locality | svn
Usage: attest3_driver.py DIR [TB_LOG]   (TB_LOG: RTL run log, used to extract per-command cycles)
Host side: `openssl` >= 3.5 + Python 3 stdlib only.  TEST material only.
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
                              "GTGD", "CKEX", "CKXM", "CKCH", "ALTN", "RCTX", "DSBL", "DPEC", "DPEM")}
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
       0x000E0001: "RUNTIME_INTERNAL", 0x000E0002: "RUNTIME_UNIMPLEMENTED_COMMAND"}

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
    print("[attest3] req %03d %-34s cmd=%08x dlen=%d" % (n_req, name, cmd, len(data)), flush=True)
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
    print("[attest3]   -> status=%d len=%d fwerr=%08x%s chk=%s (%.2fs)" % (st, dlen, fwerr,
          " (%s)" % ERR[fwerr] if fwerr in ERR else "", ok_ck, ent["wall_s"]), flush=True)
    open(os.path.join(DIR, "resp_%03d_%s.bin" % (n_req, name)), "wb").write(resp)
    n_req += 1
    return st, resp, fwerr

OK = lambda st: st in (1, 2)      # DATA_READY / CMD_COMPLETE
RESULTS = []
def step(group, name, passed, detail=""):
    RESULTS.append(dict(group=group, step=name, result="PASS" if passed else "FAIL", detail=detail))
    print("[attest3] STEP %-7s %-66s %s %s" % (group, name, "PASS" if passed else "FAIL", detail), flush=True)
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
    while len(out) < n: out += hashlib.sha512(("A5E attest3 TEST " + label).encode() + bytes([len(out) // 64])).digest()
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
        elif n == 9: d["type"] = c.decode(errors="replace")
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
    nonce = H384(b"attest3 nonce " + tag.encode())[:32]
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

# ======================= 0. info + reference certificates =======================
G = "info"
st, r, fe = mbox("FW_INFO_start", CMD["INFO"])
pl0_pauser, fw_svn, _, _, att_dis0 = struct.unpack_from("<5I", r, 8) if st == 1 else (None,) * 5
step(G, "FW_INFO: pl0_pauser = 1 (Nios is PL0), attestation_disabled = 0", pl0_pauser == 1 and att_dis0 == 0,
     "pl0_pauser=%s attestation_disabled=%s" % (pl0_pauser, att_dis0))
for nm, c in (("fmc_alias_ecc384", "CERF"), ("rt_alias_ecc384", "CERR"), ("fmc_alias_mldsa87", "CMCF"), ("rt_alias_mldsa87", "CMCR")):
    st, r, fe = mbox("GET_" + nm.upper() + "_CERT", CMD[c])
    step(G, "%s certificate read" % nm, st == 1 and save_cert(nm, var_data(r)), "%d B" % len(var_data(r)) if st == 1 else "status=%d" % st)
RT_E = open(P("rt_alias_ecc384.der"), "rb").read(); RT_M = open(P("rt_alias_mldsa87.der"), "rb").read()

# ======================= 1. EXTEND_PCR =======================
G = "pcr"
q0 = quote("base")
step(G, "QUOTE_PCRS_ECC384 baseline, signature verifies with FMC Alias ECC key", q0["status"] == 1 and quote_sig_ok(q0, "ecc", "fmc_alias_ecc384"))
D1, D2, D3 = T("pcr10 a", 48), T("pcr10 b", 48), T("pcr4", 48)
save("pcr_extend_d1.bin", D1); save("pcr_extend_d2.bin", D2); save("pcr_extend_d3.bin", D3)
ok_ext = True
for idx, d, tag in ((10, D1, "10_a"), (10, D2, "10_b"), (4, D3, "4")):
    st, r, fe = mbox("EXTEND_PCR_" + tag, CMD["PCRE"], u32(idx) + d)
    ok_ext &= step(G, "EXTEND_PCR PCR%d with 48 B (%s)" % (idx, tag), OK(st), "status=%d fwerr=%08x" % (st, fe))
q1 = quote("extended")
exp10 = H384(H384(q0["pcrs"][10], D1), D2); exp4 = H384(q0["pcrs"][4], D3)
save("pcr10_before.bin", q0["pcrs"][10]); save("pcr4_before.bin", q0["pcrs"][4])
save("pcr10_after.bin", q1["pcrs"][10]); save("pcr4_after.bin", q1["pcrs"][4])
step(G, "PCR10 == SHA-384(SHA-384(PCR10_old || D1) || D2)", q1["pcrs"][10] == exp10, q1["pcrs"][10].hex()[:24] + "..")
step(G, "PCR4 == SHA-384(PCR4_old || D3)", q1["pcrs"][4] == exp4, q1["pcrs"][4].hex()[:24] + "..")
others = [i for i in range(32) if i not in (4, 10) and q0["pcrs"][i] != q1["pcrs"][i]]
step(G, "all other PCRs unchanged", not others, "changed=%s" % others)
step(G, "quote after extend: signature verifies with FMC Alias ECC key", quote_sig_ok(q1, "ecc", "fmc_alias_ecc384"))
save("quote_ext_digest.bin", q1["digest"]); save("quote_ext_sig.der", ecdsa_sig_der(q1["sig"][:48], q1["sig"][48:96]))
save("quote_ext_pcrs.bin", b"".join(q1["pcrs"]))
osl("x509", "-in", P("fmc_alias_ecc384.pem"), "-noout", "-pubkey", "-out", P("fmc_alias_ecc384_pub.pem"))
qm = quote("extended", "mldsa")
step(G, "QUOTE_PCRS_MLDSA87 shows the same PCR4/PCR10, ML-DSA signature verifies with FMC Alias ML-DSA key",
     qm["status"] == 1 and qm["pcrs"][10] == exp10 and qm["pcrs"][4] == exp4 and quote_sig_ok(qm, "mldsa", "fmc_alias_mldsa87"))
summary["pcr"] = dict(pcr4_before=q0["pcrs"][4].hex(), pcr4_after=q1["pcrs"][4].hex(), pcr10_before=q0["pcrs"][10].hex(),
                      pcr10_after=q1["pcrs"][10].hex(), d1=D1.hex(), d2=D2.hex(), d3=D3.hex(),
                      nonzero_pcrs_at_boot=[i for i in range(32) if any(q0["pcrs"][i])])
for idx in (0, 1, 2, 3):
    st, r, fe = mbox("EXTEND_PCR_%d_reserved" % idx, CMD["PCRE"], u32(idx) + D1)
    expect_fail(G, "EXTEND_PCR PCR%d (reserved for ROM/FMC/RT journey)" % idx, st, fe, 0x000E003C)
st, r, fe = mbox("EXTEND_PCR_32", CMD["PCRE"], u32(32) + D1); expect_fail(G, "EXTEND_PCR index 32", st, fe, 0x000E003D)
st, r, fe = mbox("EXTEND_PCR_256", CMD["PCRE"], u32(256) + D1); expect_fail(G, "EXTEND_PCR index 256 (> u8)", st, fe, 0x000E0009)
st, r, fe = mbox("EXTEND_PCR_short", CMD["PCRE"], u32(10) + D1[:47])
expect_fail(G, "EXTEND_PCR with 47 B data (size mismatch reported as INSUFFICIENT_MEMORY)", st, fe, 0x000E0003)
summary["extend_short_data"] = dict(status=st, fwerr="%08x" % fe, name=ERR.get(fe))
q2 = quote("after_rejects")
step(G, "rejected extends left every PCR unchanged", q2["pcrs"] == q1["pcrs"])

# ======================= 2. INCREMENT_PCR_RESET_COUNTER =======================
G = "pcrrst"
c0 = q2["ctrs"]
for idx, k in ((10, 2), (31, 1)):
    for j in range(k):
        st, r, fe = mbox("INCREMENT_PCR_RESET_COUNTER_%d_%d" % (idx, j), CMD["PCRR"], u32(idx))
        step(G, "INCREMENT_PCR_RESET_COUNTER PCR%d (#%d)" % (idx, j + 1), OK(st), "status=%d fwerr=%08x" % (st, fe))
q3 = quote("counters")
c1 = q3["ctrs"]
step(G, "QUOTE reset_ctrs[10] rose by 2", c1[10] == c0[10] + 2, "%d -> %d" % (c0[10], c1[10]))
step(G, "QUOTE reset_ctrs[31] rose by 1", c1[31] == c0[31] + 1, "%d -> %d" % (c0[31], c1[31]))
step(G, "other counters unchanged, PCR values unchanged", all(c1[i] == c0[i] for i in range(32) if i not in (10, 31)) and q3["pcrs"] == q2["pcrs"])
step(G, "counter quote signature verifies with FMC Alias ECC key", quote_sig_ok(q3, "ecc", "fmc_alias_ecc384"))
st, r, fe = mbox("INCREMENT_PCR_RESET_COUNTER_32", CMD["PCRR"], u32(32))
expect_fail(G, "INCREMENT_PCR_RESET_COUNTER index 32", st, fe, 0x000E0009)
st, r, fe = mbox("INCREMENT_PCR_RESET_COUNTER_0", CMD["PCRR"], u32(0))
summary["reset_counter_pcr0"] = dict(status=st, fwerr="%08x" % fe)
q4 = quote("counters2")
step(G, "INCREMENT_PCR_RESET_COUNTER PCR0 is allowed (no reserved-PCR check), counter 0 rose by 1",
     OK(st) and q4["ctrs"][0] == c1[0] + 1, "status=%d ctr0 %d -> %d" % (st, c1[0], q4["ctrs"][0]))
summary["reset_ctrs_before"] = c0; summary["reset_ctrs_after"] = q4["ctrs"]

# ======================= 3. DPE_TAG_TCI / DPE_GET_TAGGED_TCI =======================
G = "tag"
TAG1, TAG2, TAG3 = tt("A5E1"), tt("A5E2"), tt("A5E3")
st, r, fe = mbox("DPE_TAG_TCI_as_TAGT_0x54414754", cmd_id("TAGT"), DEFAULT_HANDLE + u32(TAG1))
expect_fail(G, "DPE_TAG_TCI sent as ASCII 'TAGT' 0x54414754 (real ID is 0x54514754)", st, fe, 0x000E0002)
st, r, fe = mbox("DPE_GET_TAGGED_TCI_untagged", CMD["GTGD"], u32(TAG1))
expect_fail(G, "DPE_GET_TAGGED_TCI before any tag", st, fe, 0x000E001E)
st, r, fe = mbox("DPE_TAG_TCI_default_A5E1", CMD["TAGT"], DEFAULT_HANDLE + u32(TAG1))
step(G, "DPE_TAG_TCI default context with tag 'A5E1'", OK(st), "status=%d fwerr=%08x" % (st, fe))
def get_tci(name, tag):
    st, r, fe = mbox(name, CMD["GTGD"], u32(tag))
    if st != 1: return st, fe, None
    return st, fe, dict(cum=r[8:56], cur=r[56:104], svn=struct.unpack_from("<I", r, 104)[0] if len(r) >= 108 else None)
st, fe, t1 = get_tci("DPE_GET_TAGGED_TCI_A5E1", TAG1)
step(G, "DPE_GET_TAGGED_TCI 'A5E1' returns the default (CCIV) context", t1 is not None, "status=%d" % st)
if t1:
    step(G, "CCIV context: tci_cumulative == SHA-384(0^48 || tci_current), svn 0",
         t1["cum"] == H384(b"\0" * 48, t1["cur"]) and t1["svn"] == 0, "cur=%s.. svn=%s" % (t1["cur"].hex()[:16], t1["svn"]))
st, r, fe = mbox("DPE_TAG_TCI_default_again", CMD["TAGT"], DEFAULT_HANDLE + u32(TAG2))
expect_fail(G, "DPE_TAG_TCI default context a second time (new tag)", st, fe, 0x000E0020)
st, r, fe = mbox("DPE_TAG_TCI_duplicate_tag", CMD["TAGT"], b"\x11" * 16 + u32(TAG1))
expect_fail(G, "DPE_TAG_TCI with a tag already in use", st, fe, 0x000E001F)
st, r, fe = mbox("DPE_TAG_TCI_bad_handle", CMD["TAGT"], b"\x11" * 16 + u32(TAG3))
expect_fail(G, "DPE_TAG_TCI on a handle that does not exist", st, fe, 0x000E001E)
# new default context with a known measurement, then tag it
MEAS = H384(b"Nios V application image v3 (attest3 TCI)")
save("tci_measurement.bin", MEAS)
st, d, fe, ds = derive("DPE_DERIVE_CONTEXT_meas", MEAS, tt("NIO3"), svn=3)
step(G, "DPE DeriveContext (MAKE_DEFAULT, svn 3) with measurement M", st == 1 and ds == 0, "status=%d dpe=%s" % (st, ds))
st, r, fe = mbox("DPE_TAG_TCI_child_A5E2", CMD["TAGT"], DEFAULT_HANDLE + u32(TAG2))
step(G, "DPE_TAG_TCI new default context with tag 'A5E2'", OK(st), "status=%d fwerr=%08x" % (st, fe))
st, fe, t2 = get_tci("DPE_GET_TAGGED_TCI_A5E2", TAG2)
if t2:
    save("tci_a5e2_current.bin", t2["cur"]); save("tci_a5e2_cumulative.bin", t2["cum"])
step(G, "'A5E2': tci_current == M", t2 is not None and t2["cur"] == MEAS)
step(G, "'A5E2': tci_cumulative == SHA-384(0^48 || M)", t2 is not None and t2["cum"] == H384(b"\0" * 48, MEAS))
step(G, "'A5E2': svn == 3", t2 is not None and t2["svn"] == 3, "svn=%s" % (t2 and t2["svn"]))
st, fe, t1b = get_tci("DPE_GET_TAGGED_TCI_A5E1_parent", TAG1)
summary["tag_parent_after_derive"] = dict(status=st, fwerr="%08x" % fe, same=bool(t1b and t1 and t1b["cur"] == t1["cur"]))
step(G, "'A5E1' (parent, now retired) still readable and unchanged", t1b is not None and t1 is not None and t1b == t1,
     "status=%d fwerr=%08x" % (st, fe))
summary["tci"] = dict(cciv_current=t1 and t1["cur"].hex(), cciv_cumulative=t1 and t1["cum"].hex(), measurement=MEAS.hex(),
                      a5e2_current=t2 and t2["cur"].hex(), a5e2_cumulative=t2 and t2["cum"].hex(), a5e2_svn=t2 and t2["svn"])

# ======================= 4. CERTIFY_KEY_EXTENDED =======================
G = "ckx"
LABEL = H384(b"attest3 certify-key label")
def check_leaf(G, tag, alg, blob, issuer, label_desc):
    magic, dst, h, pub, cert = parse_ck(blob, alg)
    name = "ckx_%s_%s" % (alg, tag)
    ok = step(G, "%s %s: DPE status 0, cert parses" % (alg.upper(), tag), magic == DPER and dst == 0 and save_cert(name, cert),
              "%d B" % len(cert))
    if not ok: return None
    v, msg = verify_by(issuer, name)
    step(G, "%s %s: openssl verify against %s" % (alg.upper(), tag, issuer), v, msg)
    kp = cert_spki_tail(P(name + ".pem"), len(pub))
    step(G, "%s %s: cert public key == returned derived key" % (alg.upper(), tag), kp == pub)
    ex = cert_exts(cert)
    mt = ex.get("2.23.133.5.4.5", {}).get("multi_tcb_info", [])
    hit = [t for t in mt if MEAS.hex() in t.get("fwids", [])]
    step(G, "%s %s: MultiTcbInfo has the 'NIO3' entry with fwid M and svn 3" % (alg.upper(), tag),
         any(t.get("svn") == 3 and t.get("type") == "NIO3" for t in hit),
         "%d TCB entries, types=%s" % (len(mt), [t.get("type") for t in mt]))
    summary.setdefault("tcb_types_in_leaf", {})[name] = [t.get("type") for t in mt]
    return dict(name=name, cert=cert, pub=pub, exts=ex)
st, fe, b = ckx("CERTIFY_KEY_EXTENDED_ECC384_X509", "ecc", X509, LABEL)
step(G, "CERTIFY_KEY_EXTENDED_ECC384 X.509", st == 1, "status=%d fwerr=%08x" % (st, fe))
ce = check_leaf(G, "x509", "ecc", b, "rt_alias_ecc384", "label") if st == 1 else None
if ce: step(G, "ECC X.509 without DMTF flag: no subjectAltName", "2.5.29.17" not in ce["exts"])
st, fe, b = ckx("CERTIFY_KEY_EXTENDED_MLDSA87_X509", "mldsa", X509, LABEL)
step(G, "CERTIFY_KEY_EXTENDED_MLDSA87 X.509", st == 1, "status=%d fwerr=%08x" % (st, fe))
cm = check_leaf(G, "x509", "mldsa", b, "rt_alias_mldsa87", "label") if st == 1 else None
# CSR format: DPE returns a CMS SignedData (signed by the RT alias key, no signed attributes) wrapping a PKCS#10
# CSR for the derived key. fw-2.1.4 quirk: SignerInfo.sid is [0] { OCTET STRING { SKI } } (80 16 04 14 ..) instead
# of [0] IMPLICIT SKI (80 14 ..), so `openssl cms -verify` reports "signer certificate not found". The driver
# therefore splits the CMS itself and checks the signature over eContent with openssl dgst / pkeyutl.
def cms_split(blob):
    ci = children(tlv(blob, 0)[1]); sd = children(tlv(ci[1][1], 0)[1])
    econt = tlv(children(sd[2][1])[1][1], 0)[1]
    si = children(children(sd[-1][1])[0][1])
    return econt, si[1][0], si[1][1], oid(children(si[3][1])[0][1]), si[-1][1]
def rt_ski(issuer):
    rc, t = osl("x509", "-in", P(issuer + ".pem"), "-noout", "-ext", "subjectKeyIdentifier")
    return bytes.fromhex(t.splitlines()[-1].strip().replace(":", ""))
for alg, issuer in (("ecc", "rt_alias_ecc384"), ("mldsa", "rt_alias_mldsa87")):
    osl("x509", "-in", P(issuer + ".pem"), "-noout", "-pubkey", "-out", P(issuer + "_pub.pem"))
    st, fe, b = ckx("CERTIFY_KEY_EXTENDED_%s_CSR" % ("ECC384" if alg == "ecc" else "MLDSA87"), alg, CSR, LABEL)
    if not step(G, "CERTIFY_KEY_EXTENDED_%s CSR format" % alg.upper(), st == 1, "status=%d fwerr=%08x" % (st, fe)): continue
    magic, dst, h, pub, cms = parse_ck(b, alg)
    save("ckx_%s_csr.p7b" % alg, cms)
    econt, sid_tag, sid, sig_oid, sig = cms_split(cms)
    save("ckx_%s_csr.der" % alg, econt); save("ckx_%s_csr_sig.bin" % alg, sig)
    ski = rt_ski(issuer)
    summary["csr_cms_sid_" + alg] = dict(tag="%02x" % sid_tag, value=sid.hex(), rt_alias_ski=ski.hex())
    step(G, "%s CSR: CMS SignerInfo sid carries the %s SKI (as 04 14 <SKI>, quirk)" % (alg.upper(), issuer),
         sid_tag == 0x80 and sid == b"\x04\x14" + ski, "sid=%s.." % sid.hex()[:20])
    if alg == "ecc":
        rc, out = osl("dgst", "-sha384", "-verify", P(issuer + "_pub.pem"), "-signature", P("ckx_ecc_csr_sig.bin"), P("ckx_ecc_csr.der"))
    else:
        rc, out = osl("pkeyutl", "-verify", "-pubin", "-inkey", P(issuer + "_pub.pem"), "-rawin", "-in", P("ckx_mldsa_csr.der"),
                      "-sigfile", P("ckx_mldsa_csr_sig.bin"))
    step(G, "%s CSR: CMS signature (%s) over the CSR verifies with %s" % (alg.upper(), sig_oid, issuer), rc == 0, out.strip().splitlines()[-1] if out.strip() else "")
    rc2, out2 = osl("req", "-inform", "DER", "-in", P("ckx_%s_csr.der" % alg), "-verify", "-noout")
    step(G, "%s CSR: inner PKCS#10 self-signature verifies" % alg.upper(), rc2 == 0, out2.strip().splitlines()[-1] if out2.strip() else "")
    osl("req", "-inform", "DER", "-in", P("ckx_%s_csr.der" % alg), "-out", P("ckx_%s_csr.pem" % alg))
    rc3, pk = osl("req", "-in", P("ckx_%s_csr.pem" % alg), "-noout", "-pubkey")
    open(P("tmp_k.pem"), "w").write(pk); osl("pkey", "-pubin", "-in", P("tmp_k.pem"), "-outform", "DER", "-out", P("tmp_k.der"))
    kp = open(P("tmp_k.der"), "rb").read()[-len(pub):]; os.remove(P("tmp_k.pem")); os.remove(P("tmp_k.der"))
    ref = (ce if alg == "ecc" else cm)
    step(G, "%s CSR: key == returned key == X.509 cert key (same label)" % alg.upper(), kp == pub and ref is not None and ref["pub"] == pub)
st, fe, b = ckx("CERTIFY_KEY_EXTENDED_ECC384_bad_format", "ecc", 2, LABEL)
expect_fail(G, "CERTIFY_KEY_EXTENDED_ECC384 format 2 (DPE InvalidArgument)", st, fe, 0x000E0040)
st, fe, b = ckx("CERTIFY_KEY_EXTENDED_ECC384_bad_handle", "ecc", X509, LABEL, handle=b"\x22" * 16)
expect_fail(G, "CERTIFY_KEY_EXTENDED_ECC384 unknown context handle", st, fe, 0x000E0040)
st, fe, b = ckx("CERTIFY_KEY_EXTENDED_MLDSA87_axi", "mldsa", X509, LABEL, flags=F_AXI)
expect_fail(G, "CERTIFY_KEY_EXTENDED_MLDSA87 EXTERNAL_AXI_RESPONSE in passive mode", st, fe, 0x000E0009)

# ======================= 5. CERTIFY_KEY_CHUNKS =======================
G = "chunks"
def chunks(tag, alg, max_size, fmt=X509, label=LABEL):
    flags = F_USE_MLDSA if alg == "mldsa" else 0
    off, data, n, handles = 0, b"", 0, set()
    while True:
        st, r, fe = mbox("CERTIFY_KEY_CHUNKS_%s_%s_%d" % (alg.upper(), tag, off), CMD["CKCH"], u32(flags, 0, max_size, off) + ck_cmd(fmt, label))
        if st != 1: return None, n, (st, fe)
        h = r[8:24]; clen, rem = struct.unpack_from("<II", r, 24); data += r[32:32 + clen]; n += 1; handles.add(h)
        off += clen
        if rem == 0 or clen == 0: return data, n, (handles, rem)
for alg, ms in (("ecc", 256), ("mldsa", 4096)):
    data, n, info = chunks("x509", alg, ms)
    if not step(G, "%s CERTIFY_KEY_CHUNKS max_size %d: all chunks returned" % (alg.upper(), ms), data is not None,
                "%d chunks, %d B" % (n, len(data or b""))): continue
    step(G, "%s chunks: every chunk <= max_size, more than one chunk" % alg.upper(), n > 1 and n == -(-len(data) // ms))
    step(G, "%s chunks: context_handle == default handle in every chunk" % alg.upper(), info[0] == {DEFAULT_HANDLE})
    save("chunks_%s_resp.bin" % alg, data)
    ref_st, ref_fe, ref = ckx("CERTIFY_KEY_EXTENDED_%s_ref" % ("ECC384" if alg == "ecc" else "MLDSA87"), alg, X509, LABEL)
    if ref: save("ckx_%s_single_resp.bin" % alg, ref)
    step(G, "%s reassembled chunks == single-shot CERTIFY_KEY_EXTENDED response, byte for byte" % alg.upper(), ref == data,
         "%d vs %d B" % (len(data), len(ref or b"")))
    magic, dst, h, pub, cert = parse_ck(data, alg)
    nm = "chunks_%s" % alg
    if save_cert(nm, cert):
        v, msg = verify_by("rt_alias_ecc384" if alg == "ecc" else "rt_alias_mldsa87", nm)
        step(G, "%s reassembled cert verifies against RT Alias" % alg.upper(), v, msg)
    else: step(G, "%s reassembled cert parses" % alg.upper(), False)
data, n, info = chunks("default", "ecc", 0)
step(G, "ECC max_size 0 (= 15 KiB default): one chunk, remaining 0", data is not None and n == 1, "%d chunks %d B" % (n, len(data or b"")))
st, r, fe = mbox("CERTIFY_KEY_CHUNKS_ECC_offset_past_end", CMD["CKCH"], u32(0, 0, 256, 100000) + ck_cmd(X509, LABEL))
cl = struct.unpack_from("<II", r, 24) if st == 1 else None
step(G, "offset past the end: chunk_len 0, remaining 0 (offset clamped)", st == 1 and cl == (0, 0), "status=%d %s" % (st, cl))
st, r, fe = mbox("CERTIFY_KEY_CHUNKS_bad_format", CMD["CKCH"], u32(0, 0, 256, 0) + ck_cmd(2, LABEL))
expect_fail(G, "CERTIFY_KEY_CHUNKS format 2", st, fe, 0x000E0040)

# ======================= 6. ADD_SUBJECT_ALT_NAME =======================
G = "san"
DEVINFO = b"Intel:A5EC065BB32AE6S:NIOSV-A5E-0001"
DMTF_OID = "1.3.6.1.4.1.412.274.1"
st, r, fe = mbox("ADD_SUBJECT_ALT_NAME", CMD["ALTN"], u32(len(DEVINFO)) + DEVINFO)
step(G, "ADD_SUBJECT_ALT_NAME '%s'" % DEVINFO.decode(), OK(st), "status=%d fwerr=%08x" % (st, fe))
def san_cert(tag, alg, flags):
    st, fe, b = ckx("CERTIFY_KEY_EXTENDED_%s_%s" % ("ECC384" if alg == "ecc" else "MLDSA87", tag), alg, X509, LABEL, flags=flags)
    if st != 1: return None, st, fe
    magic, dst, h, pub, cert = parse_ck(b, alg)
    nm = "san_%s_%s" % (alg, tag); save_cert(nm, cert)
    return nm, st, fe
def san_of(nm): return cert_exts(open(P(nm + ".der"), "rb").read()).get("2.5.29.17")
for alg in ("ecc", "mldsa"):
    nm, st, fe = san_cert("dmtf", alg, F_DMTF)
    if not step(G, "%s CERTIFY_KEY_EXTENDED with DMTF_OTHER_NAME" % alg.upper(), nm is not None, "status=%d fwerr=%08x" % (st, fe)): continue
    s = san_of(nm)
    names = s["san"] if s else []
    step(G, "%s cert has SAN otherName %s = '%s' (UTF8String)" % (alg.upper(), DMTF_OID, DEVINFO.decode()),
         len(names) == 1 and names[0].get("oid") == DMTF_OID and names[0].get("value") == DEVINFO.decode() and names[0].get("value_tag") == 0x0c,
         str(names))
    step(G, "%s SAN extension not critical" % alg.upper(), s is not None and not s["critical"])
    rc, txt = osl("x509", "-in", P(nm + ".pem"), "-noout", "-ext", "subjectAltName")
    step(G, "%s openssl x509 shows the othername" % alg.upper(), DMTF_OID in txt and DEVINFO.decode() in txt, " ".join(txt.split())[:90])
    v, msg = verify_by("rt_alias_ecc384" if alg == "ecc" else "rt_alias_mldsa87", nm)
    step(G, "%s SAN cert verifies against RT Alias" % alg.upper(), v, msg)
nm, st, fe = san_cert("noflag", "ecc", 0)
step(G, "ECC without DMTF_OTHER_NAME after ADD_SUBJECT_ALT_NAME: no SAN", nm is not None and san_of(nm) is None)
for tag, info, code in (("one_colon", b"Intel:A5E-0001", 0x000E003E), ("three_colons", b"a:b:c:d", 0x000E003E),
                        ("non_ascii", b"Intel:A5E\xc3\xa9:0001", 0x000E003E), ("empty", b"", 0x000E003E)):
    st, r, fe = mbox("ADD_SUBJECT_ALT_NAME_" + tag, CMD["ALTN"], u32(len(info)) + info)
    expect_fail(G, "ADD_SUBJECT_ALT_NAME %s" % tag, st, fe, code)
st, r, fe = mbox("ADD_SUBJECT_ALT_NAME_size129", CMD["ALTN"], u32(129) + b"a:b:" + b"c" * 124)
expect_fail(G, "ADD_SUBJECT_ALT_NAME dmtf_device_info_size 129 (> 128)", st, fe, 0x000E0009)
nm, st, fe = san_cert("after_rejects", "ecc", F_DMTF)
s = san_of(nm) if nm else None
step(G, "rejected updates kept the first SAN value", s is not None and s["san"][0].get("value") == DEVINFO.decode())
DEV2 = b"Intel:A5EC065BB32AE6S:NIOSV-A5E-0002"
st, r, fe = mbox("ADD_SUBJECT_ALT_NAME_replace", CMD["ALTN"], u32(len(DEV2)) + DEV2)
nm, st2, fe2 = san_cert("replaced", "ecc", F_DMTF)
s = san_of(nm) if nm else None
step(G, "a second ADD_SUBJECT_ALT_NAME replaces the value", OK(st) and s is not None and s["san"][0].get("value") == DEV2.decode())

# ======================= 7. REALLOCATE_DPE_CONTEXT_LIMITS =======================
G = "ctx"
def realloc(tag, pl0):
    st, r, fe = mbox("REALLOCATE_DPE_CONTEXT_LIMITS_" + tag, CMD["RCTX"], u32(pl0))
    return st, fe, (struct.unpack_from("<II", r, 8) if st == 1 else None)
st, fe, lim = realloc("1", 1); expect_fail(G, "REALLOCATE pl0 = 1 (< min 2)", st, fe, 0x000E0070)
st, fe, lim = realloc("65", 65); expect_fail(G, "REALLOCATE pl0 = 65 (> 64)", st, fe, 0x000E0071)
st, fe, lim = realloc("8", 8)
step(G, "REALLOCATE pl0 = 8 -> new limits PL0 8 / PL1 56", lim == (8, 56), "limits=%s" % (lim,))
k = 0
while k < 20:
    st, d, fe, ds = derive("DPE_DERIVE_CONTEXT_fill_%d" % k, T("fill %d" % k, 48), tt("F%03d" % k))
    if st != 1 or ds != 0: break
    k += 1
step(G, "DeriveContext until PL0 is full: next one rejected with PL0 threshold reached", st == 3 and fe == 0x000E0037,
     "%d succeeded, then status=%d fwerr=%08x" % (k, st, fe))
used = 8
st, fe, lim = realloc("7_below_used", 7); expect_fail(G, "REALLOCATE pl0 = 7 (< %d used)" % used, st, fe, 0x000E0072)
st, fe, lim = realloc("8_again", 8); step(G, "REALLOCATE pl0 = 8 (== used) accepted", lim == (8, 56), "limits=%s" % (lim,))
used0 = 8 - k
summary["dpe_pl0_used_before_fill"] = used0
step(G, "PL0 contexts in use before the fill = 2 base (RTMR root, CCIV) + 'NIO3' = %d (fill added %d)" % (used0, k), used0 == 3, "used0=%d" % used0)
st, fe, lim = realloc("64", 64); step(G, "REALLOCATE pl0 = 64 -> PL1 0 (no PL1 contexts in use)", lim == (64, 0), "limits=%s" % (lim,))
st, fe, lim = realloc("32", 32); step(G, "REALLOCATE back to defaults 32 / 32", lim == (32, 32), "limits=%s" % (lim,))
st, d, fe, ds = derive("DPE_DERIVE_CONTEXT_after_raise", T("after raise", 48), tt("F999"))
step(G, "DeriveContext succeeds again after raising the PL0 limit", st == 1 and ds == 0, "status=%d fwerr=%08x" % (st, fe))
st, fe, b = ckx("CERTIFY_KEY_EXTENDED_ECC384_after_fill", "ecc", X509, LABEL)
if step(G, "CERTIFY_KEY_EXTENDED_ECC384 after the fill", st == 1, "status=%d fwerr=%08x" % (st, fe)):
    magic, dst, h, pub, cert = parse_ck(b, "ecc"); save_cert("ckx_ecc_after_fill", cert)
    mt = cert_exts(cert).get("2.23.133.5.4.5", {}).get("multi_tcb_info", [])
    types = [t.get("type") for t in mt]
    step(G, "leaf MultiTcbInfo lists the whole default-context chain (NIO3, F000..F%03d, F999)" % (k - 1),
         all(("F%03d" % i) in types for i in range(k)) and "NIO3" in types and "F999" in types, "types=%s" % types)
    v, msg = verify_by("rt_alias_ecc384", "ckx_ecc_after_fill"); step(G, "after-fill cert verifies against RT Alias", v, msg)
    PRE_PUB = pub

# ======================= 8. DISABLE_ATTESTATION (last) =======================
G = "disable"
st, fe, b = ckx("CERTIFY_KEY_EXTENDED_MLDSA87_pre_disable", "mldsa", X509, LABEL)
PRE_MPUB = parse_ck(b, "mldsa")[3] if st == 1 else None
st, r, fe = mbox("DISABLE_ATTESTATION", CMD["DSBL"])
step(G, "DISABLE_ATTESTATION", OK(st), "status=%d fwerr=%08x" % (st, fe))
st, r, fe = mbox("FW_INFO_after_disable", CMD["INFO"])
att_dis1 = struct.unpack_from("<I", r, 24)[0] if st == 1 else None
step(G, "FW_INFO attestation_disabled = 1", att_dis1 == 1, "attestation_disabled=%s" % att_dis1)
st, r, fe = mbox("GET_RT_ALIAS_ECC384_CERT_after", CMD["CERR"])
step(G, "RT Alias ECC cert itself is unchanged (byte-identical)", st == 1 and var_data(r) == RT_E)
st, r, fe = mbox("GET_RT_ALIAS_MLDSA87_CERT_after", CMD["CMCR"])
step(G, "RT Alias ML-DSA cert itself is unchanged (byte-identical)", st == 1 and var_data(r) == RT_M)
for alg, issuer, pre in (("ecc", "rt_alias_ecc384", globals().get("PRE_PUB")), ("mldsa", "rt_alias_mldsa87", PRE_MPUB)):
    st, fe, b = ckx("CERTIFY_KEY_EXTENDED_%s_disabled" % ("ECC384" if alg == "ecc" else "MLDSA87"), alg, X509, LABEL)
    summary["certify_after_disable_" + alg] = dict(status=st, fwerr="%08x" % fe)
    if not step(G, "%s CERTIFY_KEY_EXTENDED still answers after disable" % alg.upper(), st == 1, "status=%d fwerr=%08x" % (st, fe)): continue
    magic, dst, h, pub, cert = parse_ck(b, alg); nm = "disabled_%s" % alg; save_cert(nm, cert)
    step(G, "%s derived key changed (CDI replaced by KDF of zeros)" % alg.upper(), pre is not None and pub != pre)
    v, msg = verify_by(issuer, nm)
    step(G, "%s leaf no longer verifies against RT Alias (attestation broken by design)" % alg.upper(), not v, msg)
q5 = quote("disabled")
step(G, "QUOTE_PCRS_ECC384 after disable still signed by FMC Alias (PCR signing key not erased)",
     q5["status"] == 1 and quote_sig_ok(q5, "ecc", "fmc_alias_ecc384"), "status=%s" % q5["status"])
step(G, "PCR values and reset counters survive DISABLE_ATTESTATION", q5.get("pcrs") == q4["pcrs"] and q5.get("ctrs") == q4["ctrs"])
st, fe, t2d = get_tci("DPE_GET_TAGGED_TCI_A5E2_disabled", TAG2)
step(G, "DPE_GET_TAGGED_TCI still returns the tagged TCI ('A5E2' == M)", t2d is not None and t2d["cur"] == MEAS, "status=%d fwerr=%08x" % (st, fe))
st, r, fe = mbox("DISABLE_ATTESTATION_again", CMD["DSBL"])
step(G, "second DISABLE_ATTESTATION is accepted (idempotent)", OK(st), "status=%d fwerr=%08x" % (st, fe))
summary["disable_twice"] = dict(status=st, fwerr="%08x" % fe)

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
json.dump(summary, open(os.path.join(DIR, "attest3_summary.json"), "w"), indent=1, default=lambda o: o.hex() if isinstance(o, bytes) else str(o))
for e in LOG: print("[attest3]   %03d %-40s status=%d fwerr=%s cycles=%s" % (e["n"], e["name"], e["status"], e["fw_err_non_fatal"], e.get("cycles", "-")))
print("[attest3] per group: " + ", ".join("%s %d/%d" % (k_, v[0], v[0] + v[1]) for k_, v in groups.items()))
fails = [s["step"] for s in RESULTS if s["result"] != "PASS"]
for f in fails: print("[attest3] FAILED: " + f)
print("[attest3] done, %d commands, %d steps, %.1f s; %s" % (n_req, len(RESULTS), summary["wall_s"],
      "ATTEST3 PASS" if summary["all_pass"] else "ATTEST3 FAIL (%d)" % len(fails)))
sys.exit(0 if summary["all_pass"] else 1)

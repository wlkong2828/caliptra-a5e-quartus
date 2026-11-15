#!/usr/bin/env python3
"""Caliptra 2.x runtime crypto exercise (Nios-host side), backend-agnostic: ML-DSA-87, ECDSA P-384, LMS.
= mldsa_driver.py's ML-DSA-87 sequence, followed by ECDSA-384 (CM_IMPORT/CMEP/CMES/CMEV + ECV2) and LMS (LMV2).
ECDSA / LMS commands (fw-2.1.4 = dd1e79d):
  CM_IMPORT          "CMIM"  key_usage(3=ECDSA) | input_size(48) | seed -> CMK[128]
  CM_ECDSA_PUBLIC_KEY"CMEP"  CMK -> x[48] | y[48]      (HMAC-DRBG keygen from the 48 B seed, big-endian)
  CM_ECDSA_SIGN      "CMES"  CMK | msg_size | msg -> r[48] | s[48]   (fw hashes msg with SHA-384)
  CM_ECDSA_VERIFY    "CMEV"  CMK | r | s | msg_size | msg -> hdr / FAIL 0xA0050000
  ECDSA384_SIGNATURE_VERIFY "ECV2" x | y | r | s | sha384[48] -> hdr / FAIL 0x000E0004 (digest supplied directly)
  LMS_SIGNATURE_VERIFY "LMV2" tree_type | ots_type | I[16] | T1[24] | q | ots_sig[1252] | sig_tree_type |
      path[360] | hash[48] -> hdr / FAIL 0x000E0042. Only LMS_SHA256_M24_H15 (12) + LMOTS_SHA256_N24_W4 (7);
      the LMS "message" is the 48-byte field itself (host passes SHA-384(msg)).  u32 fields = LE numbers.
No EdDSA / Ed25519 command exists in fw-2.1.4 (no Ed25519 engine in Caliptra 2.x).
------------------------------------------------------------------------------------------------------------
Original ML-DSA description:

Same file protocol and mailbox framing as attest_driver.py (tb_nios2x_top_fw +test=attest, or the
sw-emulator attest_emu example):  req_NNN.hex -> resp_NNN.hex + resp_NNN.done, cmd 0 ends.
Commands (caliptra-sw fw-2.1.4 = dd1e79d, api/src/mailbox.rs + runtime/src/cryptographic_mailbox.rs):
  CM_RANDOM_GENERATE "CMRG"  size                                   -> data_len | data
  CM_IMPORT          "CMIM"  key_usage(4=MLDSA) | input_size(32) | seed -> CMK[128] (AES-GCM encrypted, opaque)
  CM_MLDSA_PUBLIC_KEY"CMMP"  CMK                                    -> pub_key[2592]
  CM_MLDSA_SIGN      "CMMS"  CMK | msg_size | msg                   -> signature[4628] (4627 + 1 zero pad)
  CM_MLDSA_VERIFY    "CMMV"  CMK | signature[4628] | msg_size | msg -> hdr only / FAIL 0xA0050000
  MLDSA87_SIGNATURE_VERIFY "MLV2" pub_key[2592] | signature[4628] | msg_size | msg -> hdr / FAIL 0x000E006C
Every ML-DSA op re-derives the key pair from the 32-byte seed inside the CMK (Adams Bridge KEYGEN(+SIGN)),
signing is deterministic (sign_rnd = 0) and CMMS also self-verifies before returning.
Usage: crypto_driver.py DIR [TB_LOG]   (TB_LOG: RTL run log, used to extract per-command cycles)
Host cross-check: OpenSSL >= 3.5 (ML-DSA-87) verifies every signature with the Caliptra public key, and
re-derives the fixed-seed key pair + deterministic signature to compare byte-for-byte.
TEST material only.
"""
import hashlib, json, os, re, struct, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lms_n24 as LMS

DIR = os.path.abspath(sys.argv[1]); os.makedirs(DIR, exist_ok=True)
TB_LOG = sys.argv[2] if len(sys.argv) > 2 else None
for _f in os.listdir(DIR):
    if re.match(r"(req|resp)_\d{3}", _f) or _f == ".req.tmp": os.remove(os.path.join(DIR, _f))
LOG = []

def cmd_id(s): return struct.unpack(">I", s.encode())[0]
CMD = {k: cmd_id(v) for k, v in dict(RNG="CMRG", IMPORT="CMIM", PUB="CMMP", SIGN="CMMS", VERIFY="CMMV",
                                       EXT_VERIFY="MLV2", ECPUB="CMEP", ECSIGN="CMES",
                                       ECVERIFY="CMEV", ECV2="ECV2", LMV2="LMV2").items()}
ERR = {0xA0050000: "RUNTIME_MAILBOX_SIGNATURE_MISMATCH", 0x000E006C: "RUNTIME_MLDSA_VERIFY_FAILED",
       0x000E005D: "RUNTIME_CMB_INVALID_KEY_USAGE_AND_SIZE", 0x000E0004: "RUNTIME_ECDSA_VERIFY_FAILED",
       0x000E0042: "RUNTIME_LMS_VERIFY_FAILED", 0x000E0043: "RUNTIME_LMS_VERIFY_INVALID_LMS_ALGORITHM",
       0x000E0044: "RUNTIME_LMS_VERIFY_INVALID_LMOTS_ALGORITHM", 0x000E0009: "RUNTIME_MAILBOX_INVALID_PARAMS"}
ECDSA_USAGE = 3
MLDSA_USAGE, PK_LEN, SIG_LEN = 4, 2592, 4628

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
    print("[crypto] req %03d %-26s cmd=%08x dlen=%d" % (n_req, name, cmd, len(data)), flush=True)
    while not os.path.exists(done):
        if time.time() - t0 > timeout_s: raise SystemExit("timeout waiting for " + done)
        time.sleep(0.5)
    time.sleep(0.2)
    lines = open(os.path.join(DIR, "resp_%03d.hex" % n_req)).read().split("\n")
    st, dlen = int(lines[0], 16), int(lines[1], 16)
    fwerr = int([l for l in lines if l.startswith("fwerr")][0].split()[1], 16)
    resp = b"".join(struct.pack("<I", int(l, 16)) for l in lines[2:2 + (dlen + 3) // 4])[:dlen]
    ok_ck = None
    if st == 1 and dlen >= 8:
        ok_ck = struct.unpack_from("<I", resp)[0] == checksum(0, resp[4:])
    ent = dict(n=n_req, name=name, cmd="%08x" % cmd, req_len=len(data), status=st, resp_len=dlen,
               fw_err_non_fatal="%08x" % fwerr, fw_err_name=ERR.get(fwerr), resp_checksum_ok=ok_ck,
               wall_s=round(time.time() - t0, 1))
    LOG.append(ent)
    print("[crypto]   -> status=%d len=%d fwerr=%08x%s chk=%s (%.1fs)" % (st, dlen, fwerr,
          " (%s)" % ERR[fwerr] if fwerr in ERR else "", ok_ck, ent["wall_s"]), flush=True)
    open(os.path.join(DIR, "resp_%03d_%s.bin" % (n_req, name)), "wb").write(resp)
    n_req += 1
    return st, resp, fwerr

OK = lambda st: st in (1, 2)      # DATA_READY / CMD_COMPLETE
RESULTS = []
def step(name, passed, detail=""):
    RESULTS.append(dict(step=name, result="PASS" if passed else "FAIL", detail=detail))
    print("[crypto] STEP %-48s %s %s" % (name, "PASS" if passed else "FAIL", detail), flush=True)

# ---------------- test vectors (TEST ONLY) ----------------
FIXED_SEED = hashlib.sha256(b"A5E Caliptra 2.x ML-DSA-87 TEST seed (not secret)").digest()   # 32 B
MSG = b"Nios V -> Caliptra 2.x: ML-DSA-87 sign/verify test, A5E-065 !"   # 61 B, not a multiple of 4
assert len(MSG) % 4 != 0
BAD = bytes([MSG[0] ^ 0x01]) + MSG[1:]                                                          # one flipped bit

def import_seed(tag, seed):
    st, r, _ = mbox("CM_IMPORT_" + tag, CMD["IMPORT"], struct.pack("<II", MLDSA_USAGE, len(seed)) + seed)
    ok = st == 1 and len(r) == 8 + 128
    step("CM_IMPORT(MLDSA, 32 B seed) %s -> CMK" % tag, ok, "cmk=%d B" % (len(r) - 8))
    return r[8:136] if ok else None

def pub(tag, cmk):
    st, r, _ = mbox("CM_MLDSA_PUBLIC_KEY_" + tag, CMD["PUB"], cmk)
    ok = st == 1 and len(r) == 8 + PK_LEN
    step("CM_MLDSA_PUBLIC_KEY %s (keygen)" % tag, ok, "pk=%d B" % (len(r) - 8))
    return r[8:8 + PK_LEN] if ok else None

def sign(tag, cmk, msg):
    st, r, _ = mbox("CM_MLDSA_SIGN_" + tag, CMD["SIGN"], cmk + struct.pack("<I", len(msg)) + msg)
    ok = st == 1 and len(r) == 8 + SIG_LEN and r[-1] == 0
    step("CM_MLDSA_SIGN %s (keygen+sign+self-verify)" % tag, ok, "sig=%d B" % (len(r) - 8))
    return r[8:8 + SIG_LEN] if ok else None

def verify(tag, cmk, sig, msg, expect_ok):
    st, r, fe = mbox("CM_MLDSA_VERIFY_" + tag, CMD["VERIFY"], cmk + sig + struct.pack("<I", len(msg)) + msg)
    ok = OK(st) if expect_ok else (st == 3 and fe == 0xA0050000)
    step("CM_MLDSA_VERIFY %s (expect %s)" % (tag, "pass" if expect_ok else "reject"), ok,
         "status=%d fwerr=%08x" % (st, fe))

def ext_verify(tag, pk, sig, msg, expect_ok):
    st, r, fe = mbox("MLDSA87_SIG_VERIFY_" + tag, CMD["EXT_VERIFY"], pk + sig + struct.pack("<I", len(msg)) + msg)
    ok = OK(st) if expect_ok else (st == 3 and fe == 0x000E006C)
    step("MLDSA87_SIGNATURE_VERIFY %s (expect %s)" % (tag, "pass" if expect_ok else "reject"), ok,
         "status=%d fwerr=%08x" % (st, fe))


# ---------------- host-side ECDSA / LMS material (prepared before req_000) ----------------
def osl(*a, **kw): return subprocess.run(["openssl"] + list(a), capture_output=True, **kw)
HTMP = tempfile.mkdtemp(prefix="crypto_", dir=DIR)
def hp(n): return os.path.join(HTMP, n)
ECMSG = b"Nios V -> Caliptra 2.x: ECDSA P-384 sign/verify test, A5E-065 !!"   # 65 B
ECBAD = bytes([ECMSG[0] ^ 0x01]) + ECMSG[1:]
EC_SEED = hashlib.sha384(b"A5E Caliptra 2.x ECDSA-384 TEST seed (not secret)").digest()     # 48 B
ECH, ECH_BAD = hashlib.sha384(ECMSG).digest(), hashlib.sha384(ECBAD).digest()
def der_len(n): return bytes([n]) if n < 128 else bytes([0x81, n])
def der_int(b):
    b = b.lstrip(b"\0") or b"\0"
    if b[0] & 0x80: b = b"\0" + b
    return b"\x02" + der_len(len(b)) + b
def ecdsa_der(r, s_):
    body = der_int(r) + der_int(s_); return b"\x30" + der_len(len(body)) + body
def der_rs(d):   # parse ECDSA-Sig-Value
    i = 2 if d[1] < 128 else 3
    out = []
    for _ in range(2):
        assert d[i] == 2; l = d[i + 1]; v = d[i + 2:i + 2 + l]; i += 2 + l
        out.append(v.lstrip(b"\0").rjust(48, b"\0"))
    return out
P384_SPKI_PREFIX = bytes.fromhex("3076301006072a8648ce3d020106052b81040022036200")
def p384_spki(x, y): return P384_SPKI_PREFIX + b"\x04" + x + y
osl("ecparam", "-name", "secp384r1", "-genkey", "-noout", "-out", hp("hk.pem"))
_d = osl("pkey", "-in", hp("hk.pem"), "-pubout", "-outform", "DER").stdout
HOST_EC_X, HOST_EC_Y = _d[-96:-48], _d[-48:]
assert _d[:-97] == P384_SPKI_PREFIX and _d[-97] == 4
open(hp("ecmsg"), "wb").write(ECMSG)
HOST_EC_R, HOST_EC_S = der_rs(osl("dgst", "-sha384", "-sign", hp("hk.pem"), hp("ecmsg")).stdout)
open(os.path.join(DIR, "ecdsa384_host_pub.der"), "wb").write(_d)
# LMS: host-generated LMS_SHA256_M24_H15 / LMOTS_SHA256_N24_W4 key (tree cached in DIR), + caliptra-sw test vector
LMSMSG = b"Nios V -> Caliptra 2.x: LMS SHA256/192 H15 W4 verify test, A5E-065"
LMS_H, LMS_H_BAD = hashlib.sha384(LMSMSG).digest(), hashlib.sha384(bytes([LMSMSG[0] ^ 1]) + LMSMSG[1:]).digest()
LMS_I, LMS_SEED, LMS_T = LMS.load_or_keygen(os.path.join(DIR, "lms_n24h15_testkey.tree"))
LMS_PUB = LMS.pubkey(LMS_I, LMS_T)
LMS_Q = 1234
LMS_SIG = LMS.sign(LMS_I, LMS_SEED, LMS_T, LMS_Q, LMS_H)
assert LMS.verify(LMS_PUB, LMS_SIG, LMS_H) and not LMS.verify(LMS_PUB, LMS_SIG, LMS_H_BAD)
open(os.path.join(DIR, "lms_host_pub.bin"), "wb").write(LMS_PUB); open(os.path.join(DIR, "lms_host_sig.bin"), "wb").write(LMS_SIG)
def _rs_arr(name):
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "lms_kat_fw214.txt")).read()
    m = re.search(r"%s ([0-9a-f]+)" % name, src); return bytes.fromhex(m.group(1))
KAT_MSG, KAT_PUB, KAT_SIG = _rs_arr("MSG_1"), _rs_arr("MSG_1_PUB_KEY_1"), _rs_arr("MSG_1_KEY_1_SIG_1")
KAT_H = hashlib.sha384(KAT_MSG).digest()
assert LMS.verify(KAT_PUB, KAT_SIG, KAT_H)

summary = dict(fixed_seed=FIXED_SEED.hex(), msg=MSG.hex(), msg_len=len(MSG), bad_msg=BAD.hex())
# ---- 1. key from Caliptra's own DRBG: CM_RANDOM_GENERATE -> CM_IMPORT ----
st, r, _ = mbox("CM_RANDOM_GENERATE_32", CMD["RNG"], struct.pack("<I", 32))
rseed = r[12:12 + struct.unpack_from("<I", r, 8)[0]] if st == 1 else b""
step("CM_RANDOM_GENERATE 32 B", st == 1 and len(rseed) == 32, rseed.hex())
summary["random_seed"] = rseed.hex()
cmk_r = import_seed("rand", rseed) if len(rseed) == 32 else None
# ---- 2. key from a fixed (known) seed, for a byte-exact OpenSSL comparison ----
cmk_f = import_seed("fixed", FIXED_SEED)
# ---- negative import: wrong size for MLDSA ----
st, r, fe = mbox("CM_IMPORT_bad_size", CMD["IMPORT"], struct.pack("<II", MLDSA_USAGE, 48) + b"\x11" * 48)
step("CM_IMPORT(MLDSA, 48 B) rejected", st == 3 and fe == 0x000E005D, "status=%d fwerr=%08x" % (st, fe))

pk_r = pub("rand", cmk_r) if cmk_r else None
sig_r = sign("rand", cmk_r, MSG) if cmk_r else None
if sig_r:
    verify("rand good msg", cmk_r, sig_r, MSG, True)
    verify("rand flipped-bit msg", cmk_r, sig_r, BAD, False)
    if pk_r:
        ext_verify("rand good msg", pk_r, sig_r, MSG, True)
        ext_verify("rand flipped-bit msg", pk_r, sig_r, BAD, False)
pk_f = pub("fixed", cmk_f) if cmk_f else None
sig_f = sign("fixed", cmk_f, MSG) if cmk_f else None
if sig_f: verify("fixed good msg", cmk_f, sig_f, MSG, True)

# ================= ECDSA P-384 =================
def ec_import(tag, seed):
    st, r, fe = mbox("CM_IMPORT_EC_" + tag, CMD["IMPORT"], struct.pack("<II", ECDSA_USAGE, len(seed)) + seed)
    ok = st == 1 and len(r) == 8 + 128
    step("CM_IMPORT(ECDSA, 48 B seed) %s -> CMK" % tag, ok, "status=%d fwerr=%08x" % (st, fe))
    return r[8:136] if ok else None
st, r, _ = mbox("CM_RANDOM_GENERATE_48", CMD["RNG"], struct.pack("<I", 48))
ec_rseed = r[12:12 + struct.unpack_from("<I", r, 8)[0]] if st == 1 else b""
step("CM_RANDOM_GENERATE 48 B", st == 1 and len(ec_rseed) == 48, ec_rseed.hex())
summary["ecdsa_random_seed"] = ec_rseed.hex(); summary["ecdsa_fixed_seed"] = EC_SEED.hex(); summary["ecdsa_msg"] = ECMSG.hex()
st, r, fe = mbox("CM_IMPORT_EC_bad_size", CMD["IMPORT"], struct.pack("<II", ECDSA_USAGE, 32) + b"\x22" * 32)
step("CM_IMPORT(ECDSA, 32 B) rejected", st == 3 and fe == 0x000E005D, "status=%d fwerr=%08x" % (st, fe))
EC = {}
for tag, seed in (("rand", ec_rseed), ("fixed", EC_SEED)):
    if len(seed) != 48: continue
    cmk = ec_import(tag, seed)
    if not cmk: continue
    st, r, fe = mbox("CM_ECDSA_PUBLIC_KEY_" + tag, CMD["ECPUB"], cmk)
    ok = st == 1 and len(r) == 8 + 96
    step("CM_ECDSA_PUBLIC_KEY %s (keygen)" % tag, ok, "status=%d len=%d" % (st, len(r)))
    if not ok: continue
    x, y = r[8:56], r[56:104]
    st, r, fe = mbox("CM_ECDSA_SIGN_" + tag, CMD["ECSIGN"], cmk + struct.pack("<I", len(ECMSG)) + ECMSG)
    ok = st == 1 and len(r) == 8 + 96
    step("CM_ECDSA_SIGN %s (SHA-384 + sign)" % tag, ok, "status=%d len=%d" % (st, len(r)))
    if not ok: continue
    sr, ss = r[8:56], r[56:104]
    EC[tag] = dict(x=x, y=y, r=sr, s=ss)
    for vt, msg, exp in (("good msg", ECMSG, True), ("flipped-bit msg", ECBAD, False)):
        st, r, fe = mbox("CM_ECDSA_VERIFY_%s_%s" % (tag, vt), CMD["ECVERIFY"], cmk + sr + ss + struct.pack("<I", len(msg)) + msg)
        ok = OK(st) if exp else (st == 3 and fe == 0xA0050000)
        step("CM_ECDSA_VERIFY %s %s (expect %s)" % (tag, vt, "pass" if exp else "reject"), ok, "status=%d fwerr=%08x" % (st, fe))
def ecv2(tag, x, y, r_, s_, h, exp):
    st, r, fe = mbox("ECDSA384_SIG_VERIFY_" + tag, CMD["ECV2"], x + y + r_ + s_ + h)
    ok = OK(st) if exp else (st == 3 and fe == 0x000E0004)
    step("ECDSA384_SIGNATURE_VERIFY %s (expect %s)" % (tag, "pass" if exp else "reject"), ok, "status=%d fwerr=%08x" % (st, fe))
ecv2("host OpenSSL key good", HOST_EC_X, HOST_EC_Y, HOST_EC_R, HOST_EC_S, ECH, True)
ecv2("host OpenSSL key flipped-bit msg", HOST_EC_X, HOST_EC_Y, HOST_EC_R, HOST_EC_S, ECH_BAD, False)
if "rand" in EC:
    e = EC["rand"]; ecv2("Caliptra CMES sig (rand key)", e["x"], e["y"], e["r"], e["s"], ECH, True)

# ================= LMS (SHA256/192, H15, W4) =================
def lmv2(tag, pub, sig, h, exp, exp_err=0x000E0042):
    lt, ot = struct.unpack(">II", pub[:8]); I, T1 = pub[8:24], pub[24:48]
    q = struct.unpack(">I", sig[:4])[0]; ots = sig[4:4 + 1252]; slt = struct.unpack(">I", sig[1256:1260])[0]; path = sig[1260:1620]
    payload = struct.pack("<II", lt, ot) + I + T1 + struct.pack("<I", q) + ots + struct.pack("<I", slt) + path + h
    assert len(payload) == 1716
    st, r, fe = mbox("LMS_SIG_VERIFY_" + tag, CMD["LMV2"], payload)
    ok = OK(st) if exp else (st == 3 and fe == exp_err)
    step("LMS_SIGNATURE_VERIFY %s (expect %s)" % (tag, "pass" if exp else "reject"), ok, "status=%d fwerr=%08x" % (st, fe))
lmv2("host key good", LMS_PUB, LMS_SIG, LMS_H, True)
lmv2("host key flipped-bit msg", LMS_PUB, LMS_SIG, LMS_H_BAD, False)
lmv2("caliptra-sw KAT MSG_1 key1 sig1", KAT_PUB, KAT_SIG, KAT_H, True)
summary.update(lms_pub=LMS_PUB.hex(), lms_q=LMS_Q, lms_msg=LMSMSG.hex(), lms_params="LMS_SHA256_M24_H15(12)/LMOTS_SHA256_N24_W4(7)")

# end of command stream
open(os.path.join(DIR, ".req.tmp"), "w").write("00000000\n00000000\n")
os.rename(os.path.join(DIR, ".req.tmp"), os.path.join(DIR, "req_%03d.hex" % n_req))

# ---------------- host cross-check with OpenSSL ----------------
def osl(*a, **kw): return subprocess.run(["openssl"] + list(a), capture_output=True, **kw)
v = osl("version"); summary["openssl"] = v.stdout.decode().strip()
tmp = tempfile.mkdtemp(prefix="mldsa_", dir=DIR)
def p(n): return os.path.join(tmp, n)
SPKI_PREFIX = None
def keygen_from_seed(seed):
    r = osl("genpkey", "-algorithm", "ML-DSA-87", "-pkeyopt", "hexseed:" + seed.hex(), "-out", p("k.pem"))
    if r.returncode: return None
    der = osl("pkey", "-in", p("k.pem"), "-pubout", "-outform", "DER").stdout
    return der
try:
    der = keygen_from_seed(b"\0" * 32); SPKI_PREFIX = der[:len(der) - PK_LEN]
except Exception as e:
    print("[crypto] OpenSSL ML-DSA-87 unavailable:", e)
def spki(pk): return SPKI_PREFIX + pk
def osl_verify(tag, pk, sig, msg, expect_ok):
    open(p("pk.der"), "wb").write(spki(pk)); open(p("sig"), "wb").write(sig[:SIG_LEN - 1]); open(p("m"), "wb").write(msg)
    r = osl("pkeyutl", "-verify", "-pubin", "-keyform", "DER", "-inkey", p("pk.der"), "-rawin", "-in", p("m"),
            "-sigfile", p("sig"))
    ok = (r.returncode == 0) == expect_ok
    step("OpenSSL verify %s (expect %s)" % (tag, "pass" if expect_ok else "reject"), ok, r.stdout.decode().strip())
def seed_variants(s):
    w = [s[i:i + 4] for i in range(0, 32, 4)]
    return {"as-is": s, "bswap32 per word": b"".join(x[::-1] for x in w), "word-reversed": b"".join(w[::-1]),
            "byte-reversed": s[::-1]}
def keygen_match(tag, seed, pk):
    for vn, sv in seed_variants(seed).items():
        der = keygen_from_seed(sv)
        if der and der[-PK_LEN:] == pk:
            step("OpenSSL keygen(seed) == Caliptra pubkey %s" % tag, True, "seed order: " + vn); return sv
    step("OpenSSL keygen(seed) == Caliptra pubkey %s" % tag, False, "no seed byte order matched"); return None

if SPKI_PREFIX is not None:
    for tag, pk, sig in (("rand", pk_r, sig_r), ("fixed", pk_f, sig_f)):
        if pk and sig:
            open(os.path.join(DIR, "mldsa87_%s_pub.der" % tag), "wb").write(spki(pk))
            open(os.path.join(DIR, "mldsa87_%s_sig.bin" % tag), "wb").write(sig[:SIG_LEN - 1])
            osl_verify(tag + " good msg", pk, sig, MSG, True)
            osl_verify(tag + " flipped-bit msg", pk, sig, BAD, False)
    open(os.path.join(DIR, "mldsa_msg.bin"), "wb").write(MSG)
    if pk_r and rseed: keygen_match("rand", rseed, pk_r)
    if pk_f:
        sv = keygen_match("fixed", FIXED_SEED, pk_f)
        if sv and sig_f:
            keygen_from_seed(sv); open(p("m"), "wb").write(MSG)
            r = osl("pkeyutl", "-sign", "-inkey", p("k.pem"), "-rawin", "-in", p("m"), "-pkeyopt", "deterministic:1",
                    "-out", p("ref.sig"))
            ref = open(p("ref.sig"), "rb").read() if r.returncode == 0 else b""
            step("OpenSSL deterministic sign == Caliptra CM_MLDSA_SIGN (fixed)", ref == sig_f[:SIG_LEN - 1],
                 "%d B" % len(ref))
else:
    step("OpenSSL ML-DSA-87 available", False, "skipped host cross-check")
for f in os.listdir(tmp): os.remove(os.path.join(tmp, f))
os.rmdir(tmp)

# ---------------- ECDSA host cross-check with OpenSSL ----------------
for tag, e in EC.items():
    open(os.path.join(DIR, "ecdsa384_%s_pub.der" % tag), "wb").write(p384_spki(e["x"], e["y"]))
    open(os.path.join(DIR, "ecdsa384_%s_sig.der" % tag), "wb").write(ecdsa_der(e["r"], e["s"]))
    for vt, msg, exp in (("good msg", ECMSG, True), ("flipped-bit msg", ECBAD, False)):
        open(hp("m"), "wb").write(msg)
        rr = osl("dgst", "-sha384", "-keyform", "DER", "-verify", os.path.join(DIR, "ecdsa384_%s_pub.der" % tag), "-signature",
                 os.path.join(DIR, "ecdsa384_%s_sig.der" % tag), hp("m"))
        step("OpenSSL ECDSA-384 verify Caliptra %s sig, %s (expect %s)" % (tag, vt, "pass" if exp else "reject"),
             (rr.returncode == 0) == exp, rr.stdout.decode().strip())
open(os.path.join(DIR, "ecdsa_msg.bin"), "wb").write(ECMSG)
for f in os.listdir(HTMP): os.remove(os.path.join(HTMP, f))
os.rmdir(HTMP)

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
summary["all_pass"] = bool(RESULTS) and all(s["result"] == "PASS" for s in RESULTS)
json.dump(summary, open(os.path.join(DIR, "crypto_summary.json"), "w"), indent=1)
print("[crypto] done, %d commands; %s" % (n_req, "CRYPTO PASS" if summary["all_pass"] else "CRYPTO FAIL"))
for e in LOG: print("[crypto]   %03d %-28s status=%d cycles=%s" % (e["n"], e["name"], e["status"], e.get("cycles", "-")))

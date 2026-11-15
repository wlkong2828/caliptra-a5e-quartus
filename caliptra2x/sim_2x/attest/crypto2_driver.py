#!/usr/bin/env python3
"""Caliptra 2.x crypto mailbox exercise 2 (Nios-host side): SHA, HMAC, AES, AES-GCM, KDFs, ECDH, ML-KEM.
Same file protocol / mailbox framing as crypto_driver.py (tb_nios2x_top_fw +test=attest, or the sw-emulator
attest_emu example):  req_NNN.hex -> resp_NNN.hex + resp_NNN.done, cmd 0 ends the stream.
Commands (caliptra-sw fw-2.1.4 = dd1e79d, api/src/mailbox.rs + runtime/src/cryptographic_mailbox.rs). u32 = LE.
  CM_STATUS "CMST" -> used | total ;  CM_RANDOM_STIR "CMRS" size | data ;  CM_RANDOM_GENERATE "CMRG"
  CM_IMPORT "CMIM" usage | size | key -> CMK[128]   usage/size: HMAC=1 48|64, AES=2 32, ECDSA=3 48, MLDSA=4 32, MLKEM=5 64
  CM_SHA_INIT/UPDATE/FINAL "CMSI/CMSU/CMSF"  alg(1=SHA384,2=SHA512) | size | data -> ctx[200] ; final -> len | digest
  CM_SHAKE256_INIT/UPDATE/FINAL "CMXI/CMXU/CMXF" -> ctx[44] ; final -> 64 B
  CM_HMAC "CMHM" cmk | alg | size | data -> len | mac       (HMAC key CMK must be 48 or 64 B)
  CM_AES_ENCRYPT_INIT "CMAI" cmk | mode(1=CBC,2=CTR) | size | pt -> ctx[156] | iv[16] (Caliptra picks the IV) | size | ct
  CM_AES_ENCRYPT_UPDATE "CMAU" / CM_AES_DECRYPT_INIT "CMAJ" (cmk|mode|iv|size|ct) / CM_AES_DECRYPT_UPDATE "CMAV"
  CM_AES_GCM_ENCRYPT_INIT "CMGI" flags(0) | cmk | aad_size | aad -> ctx[128] | iv[12] (random IV)
  CM_AES_GCM_ENCRYPT_UPDATE/FINAL "CMGU/CMGF" -> ... final: tag[16] | size | ct
  CM_AES_GCM_DECRYPT_INIT/UPDATE/FINAL "CMDI/CMDU/CMDF"  final: ctx | tag_len | tag | size | ct -> tag_verified | size | pt
  CM_HMAC_KDF_COUNTER "CMKC" kin | alg | usage | key_size | label_size | label -> CMK = HMAC(kin, 00000001 || label)[:size]
  CM_HKDF_EXTRACT "CMKT" alg | salt CMK | ikm CMK -> PRK CMK ; CM_HKDF_EXPAND "CMKP" prk | alg | usage | size | info -> CMK
  CM_ECDH_GENERATE "CMEG" -> ctx[76] | x||y ; CM_ECDH_FINISH "CMEF" ctx | usage | peer x||y -> CMK(shared x; AES: first 32 B)
  CM_MLKEM_KEY_GEN "CMLK" cmk -> ek[1568] ; CM_MLKEM_ENCAPSULATE "CMLE" usage | ek -> ct[1568] | CMK(ss)
  CM_MLKEM_DECAPSULATE "CMLD" usage | cmk | ct -> CMK(ss)
  CM_DELETE "CMDL" cmk ; CM_CLEAR "CMCL"
Derived secrets (KDF / ECDH / ML-KEM outputs) never leave Caliptra; they come back as encrypted CMKs. The driver
checks them indirectly: it uses the CMK in CM_HMAC or AES-CBC and compares with the host doing the same KDF /
ECDH / ML-KEM with OpenSSL + Python and then the same HMAC / AES.
Usage: crypto2_driver.py DIR [TB_LOG]   (TB_LOG: RTL run log, used to extract per-command cycles)
Host side: `openssl` >= 3.5 + Python 3 stdlib only (see cm_host.py).  TEST material only.
"""
import hashlib, json, os, re, struct, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cm_host as H

DIR = os.path.abspath(sys.argv[1]); os.makedirs(DIR, exist_ok=True)
TB_LOG = sys.argv[2] if len(sys.argv) > 2 else None
for _f in os.listdir(DIR):
    if re.match(r"(req|resp)_\d{3}", _f) or _f == ".req.tmp": os.remove(os.path.join(DIR, _f))
LOG = []
T_START = time.time()

def cmd_id(s): return struct.unpack(">I", s.encode())[0]
CMD = {k: cmd_id(k) for k in ("CMST", "CMRS", "CMRG", "CMIM", "CMDL", "CMCL", "CMSI", "CMSU", "CMSF", "CMSH",
                              "CMXI", "CMXU", "CMXF", "CMHM", "CMAI", "CMAU", "CMAJ", "CMAV", "CMGI", "CMGU",
                              "CMGF", "CMDI", "CMDU", "CMDF", "CMKC", "CMKT", "CMKP", "CMEG", "CMEF", "CMLK",
                              "CMLE", "CMLD")}
ERR = {0x000E0002: "RUNTIME_UNIMPLEMENTED_COMMAND", 0x000E0009: "RUNTIME_MAILBOX_INVALID_PARAMS",
       0x000E005D: "RUNTIME_CMB_INVALID_KEY_USAGE_AND_SIZE", 0xA0055022: "CMB_HMAC_INVALID_KEY_USAGE",
       0xA0055024: "CMB_HMAC_INVALID_KEY_USAGE_AND_SIZE", 0x000E008E: "RUNTIME_CM_SHAKE256_CONTEXT_MISMATCH",
       0x000E0001: "RUNTIME_INTERNAL", 0x00100003: "DRIVER_TRNG_UPDATE_NOT_SUPPORTED",
       0x00050011: "DRIVER_ECC384_HW_ERROR"}
U_HMAC, U_AES, U_ECDSA, U_MLDSA, U_MLKEM = 1, 2, 3, 4, 5
SHA384, SHA512 = 1, 2
CBC, CTR = 1, 2
ALG = {SHA384: "sha384", SHA512: "sha512"}

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
    print("[crypto2] req %03d %-30s cmd=%08x dlen=%d" % (n_req, name, cmd, len(data)), flush=True)
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
    print("[crypto2]   -> status=%d len=%d fwerr=%08x%s chk=%s (%.2fs)" % (st, dlen, fwerr,
          " (%s)" % ERR[fwerr] if fwerr in ERR else "", ok_ck, ent["wall_s"]), flush=True)
    open(os.path.join(DIR, "resp_%03d_%s.bin" % (n_req, name)), "wb").write(resp)
    n_req += 1
    return st, resp, fwerr

OK = lambda st: st in (1, 2)      # DATA_READY / CMD_COMPLETE
RESULTS = []
def step(group, name, passed, detail=""):
    RESULTS.append(dict(group=group, step=name, result="PASS" if passed else "FAIL", detail=detail))
    print("[crypto2] STEP %-7s %-60s %s %s" % (group, name, "PASS" if passed else "FAIL", detail), flush=True)
def expect_fail(group, name, st, fe, code):
    step(group, name + " (expect reject %08x)" % code, st == 3 and fe == code, "status=%d fwerr=%08x" % (st, fe))
def u32(*v): return struct.pack("<%dI" % len(v), *v)
def save(name, data): open(os.path.join(DIR, name), "wb").write(data)
def T(label, n):                  # deterministic TEST vectors
    out = b""
    while len(out) < n: out += hashlib.sha512(("A5E crypto2 TEST " + label).encode() + bytes([len(out) // 64])).digest()
    return out[:n]
HT = tempfile.mkdtemp(prefix="crypto2_", dir=DIR)
def hp(n): return os.path.join(HT, n)
summary = dict(fw="caliptra-sw fw-2.1.4 (dd1e79d)", openssl=H.osl("version").stdout.decode().strip())

def cm_import(tag, usage, key, grp):
    st, r, fe = mbox("CM_IMPORT_" + tag, CMD["CMIM"], u32(usage, len(key)) + key)
    ok = st == 1 and len(r) == 136
    step(grp, "CM_IMPORT %s (usage %d, %d B) -> CMK" % (tag, usage, len(key)), ok, "status=%d fwerr=%08x" % (st, fe))
    return r[8:136] if ok else None
def cm_hmac(tag, cmk, alg, data):
    st, r, fe = mbox("CM_HMAC_" + tag, CMD["CMHM"], cmk + u32(alg, len(data)) + data)
    if st != 1: return None, st, fe
    n = struct.unpack_from("<I", r, 8)[0]; return r[12:12 + n], st, fe
def aes_cbc_probe(grp, tag, cmk, key_ref, pt, fname=None):
    """AES-256-CBC encrypt pt with a CMK; compare with OpenSSL using the host's copy of the key."""
    st, r, fe = mbox("CM_AES_ENCRYPT_INIT_" + tag, CMD["CMAI"], cmk + u32(CBC, len(pt)) + pt)
    if st != 1:
        step(grp, "AES-CBC with %s" % tag, False, "status=%d fwerr=%08x" % (st, fe)); return False
    iv = r[164:180]; n = struct.unpack_from("<I", r, 180)[0]; ct = r[184:184 + n]
    ref = H.aes_cbc(key_ref, iv, pt)
    step(grp, "AES-CBC with %s == OpenSSL with host key" % tag, ct == ref, "ct=%s.." % ct[:8].hex())
    if fname: save(fname + "_iv.bin", iv); save(fname + "_ct.bin", ct)
    return ct == ref

# ======================= 0. status / DRBG extras =======================
G = "misc"
st, r, fe = mbox("CM_STATUS_start", CMD["CMST"])
used0 = struct.unpack_from("<II", r, 8) if st == 1 and len(r) >= 16 else None
step(G, "CM_STATUS", used0 is not None, "used=%s total=%s" % used0 if used0 else "status=%d fwerr=%08x" % (st, fe))
# This design runs Caliptra with the EXTERNAL TRNG (the Nios services TRNG requests), and fw-2.1.4's
# Trng::stir() only supports the internal CSRNG -> DRIVER_TRNG_UPDATE_NOT_SUPPORTED is the expected answer here.
st, r, fe = mbox("CM_RANDOM_STIR_48", CMD["CMRS"], u32(48) + T("stir", 48))
expect_fail(G, "CM_RANDOM_STIR with external TRNG", st, fe, 0x00100003)
summary["random_stir"] = dict(status=st, fwerr="%08x" % fe)
st, r, fe = mbox("CM_RANDOM_GENERATE_64", CMD["CMRG"], u32(64))
rnd = r[12:12 + struct.unpack_from("<I", r, 8)[0]] if st == 1 else b""
step(G, "CM_RANDOM_GENERATE 64 B after stir", len(rnd) == 64 and len(set(rnd)) > 16, rnd[:16].hex() + "..")

# ======================= 1. SHA-384 / SHA-512 multi-part =======================
G = "sha"
SHA_MSG = T("sha message", 5 + 200 + 1 + 3001 + 77)
parts = [SHA_MSG[:5], SHA_MSG[5:205], SHA_MSG[205:206], SHA_MSG[206:3207], SHA_MSG[3207:]]
summary["sha_msg_len"] = len(SHA_MSG); save("sha_msg.bin", SHA_MSG)
for alg in (SHA384, SHA512):
    a = ALG[alg]
    st, r, fe = mbox("CM_SHA_INIT_" + a, CMD["CMSI"], u32(alg, len(parts[0])) + parts[0])
    ctx = r[8:208] if st == 1 else None
    for i, pp in enumerate(parts[1:-1]):
        if ctx is None: break
        st, r, fe = mbox("CM_SHA_UPDATE_%s_%d" % (a, i), CMD["CMSU"], ctx + u32(len(pp)) + pp)
        ctx = r[8:208] if st == 1 else None
    dig = None
    if ctx is not None:
        st, r, fe = mbox("CM_SHA_FINAL_" + a, CMD["CMSF"], ctx + u32(len(parts[-1])) + parts[-1])
        if st == 1: dig = r[12:12 + struct.unpack_from("<I", r, 8)[0]]
    ref = hashlib.new(a, SHA_MSG).digest()
    step(G, "%s init(5)+update(200,1,3001)+final(77) == hashlib" % a.upper(), dig == ref,
         (dig or b"").hex()[:32] + ".." if dig else "status=%d fwerr=%08x" % (st, fe))
    if dig: save("%s_caliptra.bin" % a, dig)
st, r, fe = mbox("CM_SHA_INIT_empty", CMD["CMSI"], u32(SHA384, 0))
dig = None
if st == 1:
    st, r, fe = mbox("CM_SHA_FINAL_empty", CMD["CMSF"], r[8:208] + u32(0))
    dig = r[12:60] if st == 1 else None
step(G, "SHA384 of empty message == hashlib", dig == hashlib.sha384(b"").digest(), (dig or b"").hex()[:32])
st, r, fe = mbox("CM_SHA_INIT_bad_alg", CMD["CMSI"], u32(3, 4) + b"abcd")
expect_fail(G, "CM_SHA_INIT hash_algorithm=3", st, fe, 0x000E0009)
st, r, fe = mbox("CM_SHA_oneshot", CMD["CMSH"], u32(SHA384, 4) + b"abcd")
step(G, "CM_SHA one-shot (CMSH) is not dispatched by fw-2.1.4 (expect reject)", st == 3,
     "status=%d fwerr=%08x %s" % (st, fe, ERR.get(fe, "")))
summary["cm_sha_oneshot"] = dict(status=st, fwerr="%08x" % fe)
# SHAKE256
SK = T("shake256 message", 10 + 150 + 33)
st, r, fe = mbox("CM_SHAKE256_INIT", CMD["CMXI"], u32(10) + SK[:10])
sdig = None
if st == 1:
    st, r, fe = mbox("CM_SHAKE256_UPDATE", CMD["CMXU"], r[8:52] + u32(150) + SK[10:160])
    if st == 1:
        st, r, fe = mbox("CM_SHAKE256_FINAL", CMD["CMXF"], r[8:52] + u32(33) + SK[160:])
        if st == 1: sdig = r[8:72]
summary["shake256"] = dict(status=st, fwerr="%08x" % fe)
step(G, "SHAKE256 init(10)+update(150)+final(33), 64 B out == hashlib.shake_256", sdig == hashlib.shake_256(SK).digest(64),
     (sdig.hex()[:32] + "..") if sdig else "status=%d fwerr=%08x %s" % (st, fe, ERR.get(fe, "")))
if sdig: save("shake256_msg.bin", SK); save("shake256_caliptra.bin", sdig)

# ======================= 2. HMAC =======================
G = "hmac"
K48, K64 = T("hmac key 48", 48), T("hmac key 64", 64)
HMSG = T("hmac message", 333)
save("hmac_key48.bin", K48); save("hmac_key64.bin", K64); save("hmac_msg.bin", HMSG)
ck48 = cm_import("HMAC48", U_HMAC, K48, G)
ck64 = cm_import("HMAC64", U_HMAC, K64, G)
st, r, fe = mbox("CM_IMPORT_HMAC_bad_size", CMD["CMIM"], u32(U_HMAC, 32) + K48[:32])
expect_fail(G, "CM_IMPORT HMAC 32 B key", st, fe, 0x000E005D)
for tag, ck, key, alg in (("key48 SHA384", ck48, K48, SHA384), ("key64 SHA512", ck64, K64, SHA512)):
    if not ck: continue
    mac, st, fe = cm_hmac(tag, ck, alg, HMSG)
    ref = H.hmac_ref(ALG[alg], key, HMSG)
    step(G, "CM_HMAC %s == Python hmac" % tag, mac == ref, (mac or b"").hex()[:32] + ".." if mac else "status=%d fwerr=%08x" % (st, fe))
    if mac: save("hmac_%s_caliptra.bin" % ALG[alg], mac)
if ck64:
    # fw-2.1.4 common/src/hmac_cm.rs: SHA384 always uses key_material[..48], so a 64 B key is cut to its first
    # 48 bytes. Standard HMAC-SHA384 would use all 64 bytes. Record what the firmware does.
    mac, st, fe = cm_hmac("key64_SHA384", ck64, SHA384, HMSG)
    std, trunc = H.hmac_ref("sha384", K64, HMSG), H.hmac_ref("sha384", K64[:48], HMSG)
    step(G, "CM_HMAC 64 B key with SHA384 == hmac(first 48 B of key) (fw quirk, != standard)",
         mac == trunc and mac != std, "standard-HMAC match=%s" % (mac == std))
    summary["hmac_key64_sha384"] = dict(matches_standard=mac == std, matches_first48=mac == trunc)
if ck64:
    bad = bytes([HMSG[0] ^ 1]) + HMSG[1:]
    mac, st, fe = cm_hmac("key64_SHA512_flipped", ck64, SHA512, bad)
    step(G, "CM_HMAC flipped-bit msg != reference MAC (and == hmac(flipped))",
         mac is not None and mac != H.hmac_ref("sha512", K64, HMSG) and mac == H.hmac_ref("sha512", K64, bad), "")
    mac, st, fe = cm_hmac("key48_vs_key64", ck48, SHA384, HMSG) if ck48 else (None, 0, 0)
    step(G, "CM_HMAC with a different key != reference MAC", mac is not None and mac != H.hmac_ref("sha384", K64, HMSG), "")
if ck48:
    mac, st, fe = cm_hmac("key48_SHA512_bad", ck48, SHA512, HMSG)
    expect_fail(G, "CM_HMAC 48 B key with SHA512", st, fe, 0xA0055024)

# ======================= 3. AES-256 CBC / CTR =======================
G = "aes"
KA = T("aes-256 key", 32); APT = T("aes plaintext", 128); save("aes_key.bin", KA); save("aes_pt.bin", APT); save("probe_pt.bin", APT[:32])
cka = cm_import("AES", U_AES, KA, G)
summary["aes"] = {}
def aes_mode(mname, mode, split_e, split_d, n):
    pt = APT[:n]
    st, r, fe = mbox("CM_AES_ENCRYPT_INIT_" + mname, CMD["CMAI"], cka + u32(mode, split_e) + pt[:split_e])
    if st != 1:
        step(G, "AES-%s encrypt init" % mname, False, "status=%d fwerr=%08x" % (st, fe)); return
    ctx, iv = r[8:164], r[164:180]; n1 = struct.unpack_from("<I", r, 180)[0]; ct = r[184:184 + n1]
    st, r, fe = mbox("CM_AES_ENCRYPT_UPDATE_" + mname, CMD["CMAU"], ctx + u32(n - split_e) + pt[split_e:])
    if st == 1: ct += r[168:168 + struct.unpack_from("<I", r, 164)[0]]
    ref = H.aes_cbc(KA, iv, pt) if mode == CBC else H.aes_ctr(KA, iv, pt)
    step(G, "AES-256-%s encrypt init(%d)+update(%d) == openssl enc" % (mname, split_e, n - split_e), ct == ref,
         "iv=%s (Caliptra-generated)" % iv.hex())
    save("aes_%s_iv.bin" % mname.lower(), iv); save("aes_%s_ct.bin" % mname.lower(), ct)
    summary["aes"][mname] = dict(iv=iv.hex(), ct=ct.hex(), pt_len=n)
    st, r, fe = mbox("CM_AES_DECRYPT_INIT_" + mname, CMD["CMAJ"], cka + u32(mode) + iv + u32(split_d) + ct[:split_d])
    out = b""
    if st == 1:
        ctx = r[8:164]; out = r[168:168 + struct.unpack_from("<I", r, 164)[0]]
        st, r, fe = mbox("CM_AES_DECRYPT_UPDATE_" + mname, CMD["CMAV"], ctx + u32(n - split_d) + ct[split_d:])
        if st == 1: out += r[168:168 + struct.unpack_from("<I", r, 164)[0]]
    step(G, "AES-256-%s decrypt init(%d)+update(%d) round-trip" % (mname, split_d, n - split_d), out == pt,
         "status=%d" % st)
if cka:
    aes_mode("CBC", CBC, 64, 48, 128)
    aes_mode("CTR", CTR, 37, 50, 100)
    st, r, fe = mbox("CM_AES_CBC_unaligned", CMD["CMAI"], cka + u32(CBC, 20) + APT[:20])
    expect_fail(G, "AES-CBC encrypt of 20 B (not a block multiple)", st, fe, 0x000E0009)
if ck48:
    st, r, fe = mbox("CM_AES_with_HMAC_key", CMD["CMAI"], ck48 + u32(CBC, 16) + APT[:16])
    expect_fail(G, "AES encrypt with an HMAC CMK", st, fe, 0x000E005D)
st, r, fe = mbox("CM_IMPORT_AES_bad_size", CMD["CMIM"], u32(U_AES, 16) + KA[:16])
expect_fail(G, "CM_IMPORT AES 16 B key (AES-128 not offered)", st, fe, 0x000E005D)

# ======================= 4. AES-256-GCM =======================
G = "gcm"
GAAD, GPT = T("gcm aad", 20), T("gcm plaintext", 77)
save("gcm_aad.bin", GAAD); save("gcm_pt.bin", GPT)
gcm = {}
if cka:
    st, r, fe = mbox("CM_AES_GCM_ENCRYPT_INIT", CMD["CMGI"], u32(0) + cka + u32(len(GAAD)) + GAAD)
    if st == 1:
        ctx, giv = r[8:136], r[136:148]
        st, r, fe = mbox("CM_AES_GCM_ENCRYPT_UPDATE", CMD["CMGU"], ctx + u32(40) + GPT[:40])
        gct = b""
        if st == 1:
            ctx = r[8:136]; gct = r[140:140 + struct.unpack_from("<I", r, 136)[0]]
            st, r, fe = mbox("CM_AES_GCM_ENCRYPT_FINAL", CMD["CMGF"], ctx + u32(37) + GPT[40:])
            if st == 1:
                gtag = r[8:24]; gct += r[28:28 + struct.unpack_from("<I", r, 24)[0]]
                rct, rtag = H.gcm_encrypt(KA, giv, GAAD, GPT)
                step(G, "AES-256-GCM encrypt init(aad 20)+update(40)+final(37): ct == reference", gct == rct,
                     "iv=%s (Caliptra-generated)" % giv.hex())
                step(G, "AES-256-GCM tag == reference (OpenSSL AES + GHASH)", gtag == rtag, gtag.hex())
                gcm = dict(iv=giv, ct=gct, tag=gtag)
                save("gcm_iv.bin", giv); save("gcm_ct.bin", gct); save("gcm_tag.bin", gtag)
    if not gcm: step(G, "AES-256-GCM encrypt", False, "status=%d fwerr=%08x" % (st, fe))
def gcm_dec(tag, iv, aad, ct, tg, split=30):
    st, r, fe = mbox("CM_AES_GCM_DECRYPT_INIT_" + tag, CMD["CMDI"], u32(0) + cka + iv + u32(len(aad)) + aad)
    if st != 1: return None, None, st, fe
    st, r, fe = mbox("CM_AES_GCM_DECRYPT_UPDATE_" + tag, CMD["CMDU"], r[8:136] + u32(split) + ct[:split])
    if st != 1: return None, None, st, fe
    pt = r[140:140 + struct.unpack_from("<I", r, 136)[0]]
    st, r, fe = mbox("CM_AES_GCM_DECRYPT_FINAL_" + tag, CMD["CMDF"], r[8:136] + u32(len(tg)) + tg.ljust(16, b"\0") +
                     u32(len(ct) - split) + ct[split:])
    if st != 1: return None, None, st, fe
    tv = struct.unpack_from("<I", r, 8)[0]; pt += r[16:16 + struct.unpack_from("<I", r, 12)[0]]
    return pt, tv, st, fe
if gcm:
    pt, tv, st, fe = gcm_dec("caliptra_ct", gcm["iv"], GAAD, gcm["ct"], gcm["tag"])
    step(G, "AES-256-GCM decrypt Caliptra ct: tag_verified=1, pt matches", tv == 1 and pt == GPT, "tag_verified=%s" % tv)
    hiv = T("host gcm iv", 12); hct, htag = H.gcm_encrypt(KA, hiv, GAAD, GPT)
    pt, tv, st, fe = gcm_dec("host_ct", hiv, GAAD, hct, htag)
    step(G, "AES-256-GCM decrypt host-encrypted ct (host IV): tag_verified=1, pt matches", tv == 1 and pt == GPT,
         "tag_verified=%s" % tv)
    bt = bytes([gcm["tag"][0] ^ 1]) + gcm["tag"][1:]
    pt, tv, st, fe = gcm_dec("tampered_tag", gcm["iv"], GAAD, gcm["ct"], bt)
    step(G, "AES-256-GCM decrypt with tampered tag rejected", (st == 1 and tv == 0) or st == 3,
         "status=%d tag_verified=%s fwerr=%08x" % (st, tv, fe))
    summary["gcm_tampered_tag"] = dict(status=st, tag_verified=tv, fwerr="%08x" % fe)
    bad_aad = bytes([GAAD[0] ^ 1]) + GAAD[1:]
    pt, tv, st, fe = gcm_dec("tampered_aad", gcm["iv"], bad_aad, gcm["ct"], gcm["tag"])
    step(G, "AES-256-GCM decrypt with tampered AAD rejected", (st == 1 and tv == 0) or st == 3,
         "status=%d tag_verified=%s fwerr=%08x" % (st, tv, fe))
    summary["gcm"] = dict(iv=gcm["iv"].hex(), ct=gcm["ct"].hex(), tag=gcm["tag"].hex(), host_iv=hiv.hex())

# ======================= 5. KDFs (indirect: use the derived CMK) =======================
G = "kdf"
KK48, KK64 = T("kdf key 48", 48), T("kdf key 64", 64)
LBL1, LBL2, LBL3 = b"A5E crypto2 KDF label: hmac", b"A5E crypto2 KDF label: aes", b"A5E crypto2 KDF label: hmac512"
save("kdf_key48.bin", KK48); save("kdf_key64.bin", KK64)
ckk48 = cm_import("KDF48", U_HMAC, KK48, G); ckk64 = cm_import("KDF64", U_HMAC, KK64, G)
def kdf_counter(tag, kin, alg, usage, size, label):
    st, r, fe = mbox("CM_HMAC_KDF_COUNTER_" + tag, CMD["CMKC"], kin + u32(alg, usage, size, len(label)) + label)
    ok = st == 1 and len(r) == 136
    step(G, "CM_HMAC_KDF_COUNTER %s -> CMK" % tag, ok, "status=%d fwerr=%08x" % (st, fe))
    return r[8:136] if ok else None
if ckk48:
    c = kdf_counter("SHA384_hmac48", ckk48, SHA384, U_HMAC, 48, LBL1)
    if c:
        mac, st, fe = cm_hmac("kdfc384_out", c, SHA384, HMSG)
        step(G, "HMAC with KDF-counter(SHA384) key == host SP800-108 + hmac", mac == H.hmac_ref("sha384", H.kdf_counter("sha384", KK48, LBL1, 48), HMSG), "")
    c = kdf_counter("SHA384_aes32", ckk48, SHA384, U_AES, 32, LBL2)
    if c: aes_cbc_probe(G, "KDF-counter(SHA384)->AES key", c, H.kdf_counter("sha384", KK48, LBL2, 32), APT[:32], "kdfc_aes")
    st, r, fe = mbox("CM_HMAC_KDF_COUNTER_bad", CMD["CMKC"], ckk48 + u32(SHA384, U_HMAC, 64, 4) + b"abcd")
    expect_fail(G, "KDF-counter SHA384 -> 64 B HMAC key", st, fe, 0x000E0009)
if ckk64:
    c = kdf_counter("SHA512_hmac64", ckk64, SHA512, U_HMAC, 64, LBL3)
    if c:
        mac, st, fe = cm_hmac("kdfc512_out", c, SHA512, HMSG)
        step(G, "HMAC with KDF-counter(SHA512) key == host SP800-108 + hmac", mac == H.hmac_ref("sha512", H.kdf_counter("sha512", KK64, LBL3, 64), HMSG), "")
# HKDF
SALT48, IKM48, SALT64, IKM64 = T("hkdf salt 48", 48), T("hkdf ikm 48", 48), T("hkdf salt 64", 64), T("hkdf ikm 64", 64)
INFO1, INFO2 = b"A5E crypto2 HKDF info: hmac", b"A5E crypto2 HKDF info: aes"
for nme, v in (("hkdf_salt48", SALT48), ("hkdf_ikm48", IKM48), ("hkdf_salt64", SALT64), ("hkdf_ikm64", IKM64)): save(nme + ".bin", v)
def hkdf_extract(tag, alg, salt, ikm):
    st, r, fe = mbox("CM_HKDF_EXTRACT_" + tag, CMD["CMKT"], u32(alg) + salt + ikm)
    ok = st == 1 and len(r) == 136
    step(G, "CM_HKDF_EXTRACT %s -> PRK CMK" % tag, ok, "status=%d fwerr=%08x" % (st, fe)); return r[8:136] if ok else None
def hkdf_expand(tag, prk, alg, usage, size, info):
    st, r, fe = mbox("CM_HKDF_EXPAND_" + tag, CMD["CMKP"], prk + u32(alg, usage, size, len(info)) + info)
    ok = st == 1 and len(r) == 136
    step(G, "CM_HKDF_EXPAND %s -> CMK" % tag, ok, "status=%d fwerr=%08x" % (st, fe)); return r[8:136] if ok else None
cs48, ci48 = cm_import("HKDF_salt48", U_HMAC, SALT48, G), cm_import("HKDF_ikm48", U_HMAC, IKM48, G)
if cs48 and ci48:
    prk = hkdf_extract("SHA384", SHA384, cs48, ci48); hprk = H.hkdf_extract("sha384", SALT48, IKM48)
    if prk:
        mac, st, fe = cm_hmac("hkdf_prk384", prk, SHA384, HMSG)
        step(G, "HMAC with HKDF-Extract(SHA384) PRK == host RFC 5869 + hmac", mac == H.hmac_ref("sha384", hprk, HMSG), "")
        o = hkdf_expand("SHA384_hmac48", prk, SHA384, U_HMAC, 48, INFO1)
        if o:
            mac, st, fe = cm_hmac("hkdf_okm384", o, SHA384, HMSG)
            step(G, "HMAC with HKDF-Expand(SHA384) OKM == host RFC 5869 + hmac", mac == H.hmac_ref("sha384", H.hkdf_expand1("sha384", hprk, INFO1, 48), HMSG), "")
        o = hkdf_expand("SHA384_aes32", prk, SHA384, U_AES, 32, INFO2)
        if o: aes_cbc_probe(G, "HKDF-Expand(SHA384)->AES key", o, H.hkdf_expand1("sha384", hprk, INFO2, 32), APT[:32], "hkdf_aes")
cs64, ci64 = cm_import("HKDF_salt64", U_HMAC, SALT64, G), cm_import("HKDF_ikm64", U_HMAC, IKM64, G)
if cs64 and ci64:
    prk = hkdf_extract("SHA512", SHA512, cs64, ci64); hprk = H.hkdf_extract("sha512", SALT64, IKM64)
    if prk:
        o = hkdf_expand("SHA512_hmac64", prk, SHA512, U_HMAC, 64, INFO1)
        if o:
            mac, st, fe = cm_hmac("hkdf_okm512", o, SHA512, HMSG)
            step(G, "HMAC with HKDF-Expand(SHA512) OKM == host RFC 5869 + hmac", mac == H.hmac_ref("sha512", H.hkdf_expand1("sha512", hprk, INFO1, 64), HMSG), "")
if cka and ci48:
    st, r, fe = mbox("CM_HKDF_EXTRACT_aes_salt", CMD["CMKT"], u32(SHA384) + cka + ci48)
    expect_fail(G, "HKDF-Extract with an AES CMK as salt", st, fe, 0x000E0009)

# ======================= 6. ECDH P-384 =======================
G = "ecdh"
host_xy = H.p384_genkey(os.path.join(DIR, "ecdh_host_priv.pem"))
save("ecdh_host_pub.der", H.p384_spki(host_xy))
st, r, fe = mbox("CM_ECDH_GENERATE", CMD["CMEG"])
ok = st == 1 and len(r) == 8 + 76 + 96
step(G, "CM_ECDH_GENERATE -> context + P-384 public x||y", ok, "status=%d fwerr=%08x" % (st, fe))
if ok:
    ectx, cal_xy = r[8:84], r[84:180]
    save("ecdh_caliptra_pub.der", H.p384_spki(cal_xy))
    chk = H.osl("pkey", "-pubin", "-inform", "DER", "-in", os.path.join(DIR, "ecdh_caliptra_pub.der"), "-noout", "-check")
    step(G, "Caliptra ECDH public key is a valid P-384 point (openssl pkey -check)", chk.returncode == 0,
         (chk.stdout + chk.stderr).decode().strip()[:60])
    ss = H.ecdh_p384(os.path.join(DIR, "ecdh_host_priv.pem"), cal_xy)
    for tag, usage in (("HMAC", U_HMAC), ("AES", U_AES)):
        st, r, fe = mbox("CM_ECDH_FINISH_" + tag, CMD["CMEF"], ectx + u32(usage) + host_xy)
        ok = st == 1 and len(r) == 136
        step(G, "CM_ECDH_FINISH (host OpenSSL pub, usage %s) -> CMK" % tag, ok, "status=%d fwerr=%08x" % (st, fe))
        if not ok: continue
        if usage == U_HMAC:
            mac, st, fe = cm_hmac("ecdh_secret", r[8:136], SHA384, HMSG)
            if mac: save("ecdh_hmac_caliptra.bin", mac)
            step(G, "HMAC-SHA384 keyed with ECDH secret == host (openssl pkeyutl -derive) + hmac",
                 mac == H.hmac_ref("sha384", ss, HMSG), "")
        else:
            aes_cbc_probe(G, "ECDH secret[:32] as AES key", r[8:136], ss[:32], APT[:32], "ecdh_aes")
    bad_xy = (1).to_bytes(48, "big") + (1).to_bytes(48, "big")
    st, r, fe = mbox("CM_ECDH_FINISH_bad_point", CMD["CMEF"], ectx + u32(U_HMAC) + bad_xy)
    step(G, "CM_ECDH_FINISH with an invalid peer point (1,1) rejected", st == 3, "status=%d fwerr=%08x" % (st, fe))
    summary["ecdh_bad_point"] = dict(status=st, fwerr="%08x" % fe)

# ======================= 7. ML-KEM-1024 =======================
G = "mlkem"
MK_SEED = T("ml-kem-1024 seed d||z", 64); save("mlkem_seed.bin", MK_SEED)
ckm = cm_import("MLKEM", U_MLKEM, MK_SEED, G)
st, r, fe = mbox("CM_IMPORT_MLKEM_bad_size", CMD["CMIM"], u32(U_MLKEM, 32) + MK_SEED[:32])
expect_fail(G, "CM_IMPORT ML-KEM 32 B seed", st, fe, 0x000E005D)
if ckm:
    st, r, fe = mbox("CM_MLKEM_KEY_GEN", CMD["CMLK"], ckm)
    ek = r[8:8 + 1568] if st == 1 and len(r) == 8 + 1568 else None
    step(G, "CM_MLKEM_KEY_GEN -> 1568 B encapsulation key", ek is not None, "status=%d fwerr=%08x" % (st, fe))
    if ek:
        save("mlkem_caliptra_ek.der", H.mlkem_spki(ek))
        ref = H.mlkem_keygen_seed(MK_SEED, hp("mk.pem"))
        step(G, "Caliptra ek == OpenSSL ML-KEM-1024 keygen from the same seed (byte-exact)", ek == ref, "")
        ct, ss = H.mlkem_encap(ek, HT)
        save("mlkem_host_ct.bin", ct)
        st, r, fe = mbox("CM_MLKEM_DECAPSULATE_host_ct", CMD["CMLD"], u32(U_AES) + ckm + ct)
        ok = st == 1 and len(r) == 136
        step(G, "CM_MLKEM_DECAPSULATE OpenSSL ciphertext -> AES CMK", ok, "status=%d fwerr=%08x" % (st, fe))
        if ok: aes_cbc_probe(G, "ML-KEM decap secret (OpenSSL encap) as AES key", r[8:136], ss, APT[:32], "mlkem_decap_aes")
        bct = bytes([ct[0] ^ 1]) + ct[1:]
        st, r, fe = mbox("CM_MLKEM_DECAPSULATE_tampered", CMD["CMLD"], u32(U_AES) + ckm + bct)
        if st == 1:
            st2, r2, fe2 = mbox("CM_AES_ENCRYPT_INIT_mlkem_tampered", CMD["CMAI"], r[8:136] + u32(CBC, 32) + APT[:32])
            differs = st2 == 1 and r2[184:216] != H.aes_cbc(ss, r2[164:180], APT[:32])
            step(G, "Tampered ML-KEM ct: implicit rejection gives a different secret", differs, "")
        else:
            step(G, "Tampered ML-KEM ct rejected", st == 3, "status=%d fwerr=%08x" % (st, fe))
    # Caliptra encapsulates to a host key; OpenSSL decapsulates
    hek = H.mlkem_keygen(os.path.join(DIR, "mlkem_host_priv.pem")); save("mlkem_host_ek.der", H.mlkem_spki(hek))
    st, r, fe = mbox("CM_MLKEM_ENCAPSULATE_host_ek", CMD["CMLE"], u32(U_AES) + hek)
    ok = st == 1 and len(r) == 8 + 1568 + 128
    step(G, "CM_MLKEM_ENCAPSULATE to host OpenSSL ek -> ct + AES CMK", ok, "status=%d fwerr=%08x" % (st, fe))
    if ok:
        cct, ccmk = r[8:1576], r[1576:1704]; save("mlkem_caliptra_ct.bin", cct)
        hss = H.mlkem_decap(os.path.join(DIR, "mlkem_host_priv.pem"), cct, HT)
        aes_cbc_probe(G, "ML-KEM encap secret (OpenSSL decap) as AES key", ccmk, hss, APT[:32], "mlkem_encap_aes")

# ======================= 8. CM_DELETE / CM_CLEAR =======================
G = "misc"
st, r, fe = mbox("CM_STATUS_before_delete", CMD["CMST"])
used1 = struct.unpack_from("<I", r, 8)[0] if st == 1 else None
if cka:
    st, r, fe = mbox("CM_DELETE_AES", CMD["CMDL"], cka)
    step(G, "CM_DELETE AES CMK", OK(st), "status=%d fwerr=%08x" % (st, fe))
    st, r, fe = mbox("CM_STATUS_after_delete", CMD["CMST"])
    used2 = struct.unpack_from("<I", r, 8)[0] if st == 1 else None
    step(G, "CM_STATUS used key-usage slots drops by 1 after delete", used1 is not None and used2 == used1 - 1,
         "used %s -> %s" % (used1, used2))
    st, r, fe = mbox("CM_AES_after_delete", CMD["CMGI"], u32(0) + cka + u32(0))
    step(G, "AES-GCM encrypt with the deleted AES CMK rejected", st == 3, "status=%d fwerr=%08x" % (st, fe))
    summary["aes_after_delete"] = dict(status=st, fwerr="%08x" % fe)
st, r, fe = mbox("CM_CLEAR", CMD["CMCL"])
step(G, "CM_CLEAR", OK(st), "status=%d fwerr=%08x" % (st, fe))
st, r, fe = mbox("CM_STATUS_after_clear", CMD["CMST"])
used3 = struct.unpack_from("<I", r, 8)[0] if st == 1 else None
step(G, "CM_STATUS used == 0 after CM_CLEAR", used3 == 0, "used=%s" % used3)

# end of command stream
open(os.path.join(DIR, ".req.tmp"), "w").write("00000000\n00000000\n")
os.rename(os.path.join(DIR, ".req.tmp"), os.path.join(DIR, "req_%03d.hex" % n_req))
for f in os.listdir(HT): os.remove(os.path.join(HT, f))
os.rmdir(HT)

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
summary["groups"] = {k: dict(passed=v[0], failed=v[1]) for k, v in groups.items()}
json.dump(summary, open(os.path.join(DIR, "crypto2_summary.json"), "w"), indent=1)
for e in LOG: print("[crypto2]   %03d %-34s status=%d cycles=%s" % (e["n"], e["name"], e["status"], e.get("cycles", "-")))
print("[crypto2] per group: " + ", ".join("%s %d/%d" % (k, v[0], v[0] + v[1]) for k, v in groups.items()))
fails = [s["step"] for s in RESULTS if s["result"] != "PASS"]
for f in fails: print("[crypto2] FAILED: " + f)
print("[crypto2] done, %d commands, %d steps, %.1f s; %s" % (n_req, len(RESULTS), summary["wall_s"],
      "CRYPTO2 PASS" if summary["all_pass"] else "CRYPTO2 FAIL (%d)" % len(fails)))

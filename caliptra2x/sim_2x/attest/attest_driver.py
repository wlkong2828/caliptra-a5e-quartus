#!/usr/bin/env python3
"""Caliptra 2.x runtime attestation driver (Nios-host side), backend-agnostic.

Talks to EITHER the RTL testbench (tb_nios2x_top_fw +test=attest) OR the sw-emulator
(attest_emu example) through the same file protocol in DIR:
   req_NNN.hex  : cmd, dlen(bytes), little-endian dwords   (we write, atomically via rename)
   resp_NNN.hex : status (1 DATA_READY / 2 CMD_COMPLETE / 3 CMD_FAILURE), dlen, dwords, 'fwerr XXXXXXXX'
   resp_NNN.done: backend marker that resp_NNN.hex is complete
Each mailbox request carries the caliptra-sw checksum (api/src/checksum.rs): 0 - sum(cmd LE bytes + payload).
Usage: attest_driver.py DIR   (writes artefacts into DIR: raw requests/responses, .der/.pem/.txt, attest_summary.json)
TEST mfg CA + cached IDevID TBS/certs live in attest/testca/ (override with ATTEST_CA_DIR). The cache is keyed by the
IDevID public key, so with the committed fuses/ROM/bundle no CA private key is needed. If the IDevID key changes
(other UDS/FE fuses), point ATTEST_CA_DIR at an empty directory and a fresh local TEST CA (*.key, never committed)
is generated with OpenSSL >= 3.5 (ML-DSA-87 support).
"""
import hashlib, json, os, re, struct, subprocess, sys, time

DIR = os.path.abspath(sys.argv[1]); os.makedirs(DIR, exist_ok=True)
HERE = os.path.dirname(os.path.abspath(__file__))
CA_DIR = os.path.abspath(os.environ.get("ATTEST_CA_DIR", os.path.join(HERE, "testca")))   # shared by both backends
os.makedirs(CA_DIR, exist_ok=True)
# Remove stale protocol files from an earlier run so the backend never replays an old request.
for _f in os.listdir(DIR):
    if re.match(r"(req|resp)_\d{3}", _f) or _f == ".req.tmp": os.remove(os.path.join(DIR, _f))
LOG = []

def cmd_id(s): return struct.unpack(">I", s.encode())[0]
CMD = {k: cmd_id(v) for k, v in dict(
    FW_INFO="INFO", IDEV_ECC_INFO="IDEI", IDEV_MLDSA_INFO="IDMI",
    IDEV_ECC_CERT="IDEC", IDEV_MLDSA_CERT="IDMC",
    LDEV_ECC="LDEV", FMC_ECC="CERF", RT_ECC="CERR",
    LDEV_MLDSA="LDMC", FMC_MLDSA="CMCF", RT_MLDSA="CMCR",
    STASH="MEAS", DPE_ECC="DPEC", DPE_MLDSA="DPEM",
    QUOTE_ECC="PCRQ", QUOTE_MLDSA="PCRM", PCR_LOG="PLOG").items()}

def checksum(cmd, data):
    return (-(sum(struct.pack("<I", cmd)) + sum(data))) & 0xFFFFFFFF

n_req = 0
def mbox(name, cmd, payload=b"", timeout_s=6 * 3600):
    """Send one mailbox command (header checksum prepended), return (status, resp bytes)."""
    global n_req
    data = struct.pack("<I", checksum(cmd, payload)) + payload
    words = [struct.unpack_from("<I", data + b"\0" * 3, i)[0] for i in range(0, len(data), 4)]
    tmp = os.path.join(DIR, ".req.tmp")
    with open(tmp, "w") as f:
        f.write("%08x\n%08x\n" % (cmd, len(data)) + "".join("%08x\n" % w for w in words))
    os.rename(tmp, os.path.join(DIR, "req_%03d.hex" % n_req))
    t0 = time.time(); done = os.path.join(DIR, "resp_%03d.done" % n_req)
    print("[driver] req %03d %-28s cmd=%08x dlen=%d" % (n_req, name, cmd, len(data)), flush=True)
    while not os.path.exists(done):
        if time.time() - t0 > timeout_s: raise SystemExit("timeout waiting for " + done)
        time.sleep(0.5)
    time.sleep(0.2)
    lines = open(os.path.join(DIR, "resp_%03d.hex" % n_req)).read().split("\n")
    st, dlen = int(lines[0], 16), int(lines[1], 16)
    fwerr = [l for l in lines if l.startswith("fwerr")][0].split()[1]
    resp = b"".join(struct.pack("<I", int(l, 16)) for l in lines[2:2 + (dlen + 3) // 4])[:dlen]
    ok_ck = None
    if st == 1 and dlen >= 8:
        ok_ck = struct.unpack_from("<I", resp)[0] == checksum(0, resp[4:])
    ent = dict(n=n_req, name=name, cmd="%08x" % cmd, req_len=len(data), status=st, resp_len=dlen,
               fw_err_non_fatal=fwerr, resp_checksum_ok=ok_ck, wall_s=round(time.time() - t0, 1))
    LOG.append(ent); print("[driver]   -> status=%d len=%d fwerr=%s chk=%s (%.1fs)" % (st, dlen, fwerr, ok_ck, ent["wall_s"]), flush=True)
    open(os.path.join(DIR, "resp_%03d_%s.bin" % (n_req, name)), "wb").write(resp)
    n_req += 1
    return st, resp

def save_cert(name, der):
    p = os.path.join(DIR, name)
    open(p + ".der", "wb").write(der)
    subprocess.run(["openssl", "x509", "-inform", "DER", "-in", p + ".der", "-out", p + ".pem"], check=True)
    subprocess.run(["openssl", "x509", "-inform", "DER", "-in", p + ".der", "-noout", "-text", "-out", p + ".txt"], check=False)
    print("[driver]   saved %s.der (%d B)" % (name, len(der)))

def var_data(resp):            # VarSizeDataResp: hdr(chksum,fips) + data_size + data
    sz = struct.unpack_from("<I", resp, 8)[0]; return resp[12:12 + sz]

def get_cert(name, cmd):
    st, r = mbox(name, cmd)
    if st == 1: save_cert(name, var_data(r)); return var_data(r)
    return None

# ---------------- DPE helpers (caliptra-dpe f2b7121) ----------------
DPE_MAGIC = cmd_id("DPEC"); P384, MLDSA87 = 4, 5
def dpe(name, which, cmd, body, profile):
    pkt = struct.pack("<III", DPE_MAGIC, cmd, profile) + body
    # INVOKE_DPE_ECC384: data_size|data ; INVOKE_DPE_MLDSA87: flags|axi_response(addr_lo,addr_hi,max)|data_size|data
    pre = b"" if which == "ecc" else struct.pack("<IIII", 0, 0, 0, 0)
    st, r = mbox(name, CMD["DPE_ECC" if which == "ecc" else "DPE_MLDSA"], pre + struct.pack("<I", len(pkt)) + pkt)
    if st != 1: return None
    sz = struct.unpack_from("<I", r, 8)[0]; d = r[12:12 + sz]
    magic, status, prof = struct.unpack_from("<III", d)
    print("[driver]   DPE resp magic=%08x status=%08x profile=%d" % (magic, status, prof))
    return d if status == 0 else None

def dpe_certify_key(which, tag, label):
    prof = P384 if which == "ecc" else MLDSA87
    body = b"\0" * 16 + struct.pack("<II", 0, 0) + label          # default handle, flags 0, FORMAT_X509
    d = dpe("DPE_%s_CERTIFY_KEY_%s" % (which.upper(), tag), which, 0x09, body, prof)
    if d is None: return None
    off = 12 + 16
    if which == "ecc": pub = d[off:off + 96]; off += 96
    else: pub = d[off:off + 2592]; off += 2592
    csz = struct.unpack_from("<I", d, off)[0]; cert = d[off + 4:off + 4 + csz]
    save_cert("dpe_%s_leaf_%s" % (which, tag), cert)
    return cert

def dpe_cert_chain(which):
    prof = P384 if which == "ecc" else MLDSA87; chain = b""; off = 0
    while True:
        d = dpe("DPE_%s_GET_CERT_CHAIN_%d" % (which.upper(), off), which, 0x10, struct.pack("<II", off, 2048), prof)
        if d is None: break
        sz = struct.unpack_from("<I", d, 12)[0]; chain += d[16:16 + sz]; off += sz
        if sz < 2048: break
    open(os.path.join(DIR, "dpe_%s_cert_chain.bin" % which), "wb").write(chain)
    # split concatenated DER certificates
    i = k = 0; certs = []
    while i < len(chain):
        assert chain[i] == 0x30
        l = chain[i + 1]
        if l & 0x80: nb = l & 0x7f; L = int.from_bytes(chain[i + 2:i + 2 + nb], "big"); h = 2 + nb
        else: L, h = l, 2
        certs.append(chain[i:i + h + L]); i += h + L
    for k, c in enumerate(certs): save_cert("dpe_%s_chain_%d" % (which, k), c)
    return certs

# ---------------- IDevID certificate (SoC/manufacturer CA signs the IDevID TBS) ----------------
def der_len(n):
    if n < 0x80: return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big"); return bytes([0x80 | len(b)]) + b
def tlv(t, v): return bytes([t]) + der_len(len(v)) + v
def ecc_spki(x, y):
    alg = tlv(0x30, bytes.fromhex("06072a8648ce3d0201") + bytes.fromhex("06052b81040022"))
    return tlv(0x30, alg + tlv(0x03, b"\0\x04" + x + y))
def mldsa_spki(pk):
    return tlv(0x30, tlv(0x30, bytes.fromhex("0609608648016503040313")) + tlv(0x03, b"\0" + pk))
def parse_tlv(b, i):
    t = b[i]; l = b[i + 1]
    if l & 0x80: nb = l & 0x7f; L = int.from_bytes(b[i + 2:i + 2 + nb], "big"); h = 2 + nb
    else: L, h = l, 2
    return t, i + h, L, i + h + L       # tag, value start, value len, next
def ossl(*a): subprocess.run(["openssl", *a], check=True, capture_output=True)

def make_ca(alg):
    key, crt = os.path.join(CA_DIR, "test_mfg_ca_%s.key" % alg), os.path.join(CA_DIR, "test_mfg_ca_%s.pem" % alg)
    if os.path.exists(crt) and not os.path.exists(key):
        raise SystemExit("IDevID key not in the TBS cache %s and the TEST CA private key %s is not available "
                         "(never committed). Set ATTEST_CA_DIR to an empty directory to create a new local TEST CA." % (CA_DIR, key))
    if not os.path.exists(crt):
        if alg == "ecc": ossl("genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-384", "-out", key)
        else: ossl("genpkey", "-algorithm", "ML-DSA-87", "-out", key)
        # ML-DSA: CA name kept short - the whole IDevID TBS must fit GetIdevMldsa87CertReq (2820 B)
        subj = "/O=TEST ONLY Nios-A5E Mfg/CN=TEST Mfg CA ECC" if alg == "ecc" else "/CN=CA"
        ossl("req", "-x509", "-new", "-key", key, "-out", crt, "-days", "36500", "-subj", subj,
             "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign",
             *(["-sha384"] if alg == "ecc" else []))
    return key, crt

def build_idev_tbs(alg, spki_der, ldev_der):
    """Make the IDevID TBS + signature with the test mfg CA. Cached by public key so both backends
    submit byte-identical requests (ECDSA by openssl is randomized)."""
    tag = hashlib.sha256(spki_der).hexdigest()[:16]
    cache = os.path.join(CA_DIR, "idev_%s_%s" % (alg, tag))
    if not os.path.exists(cache + ".cert.der"):
        key, crt = make_ca(alg)
        open(cache + ".pub.der", "wb").write(spki_der)
        ossl("pkey", "-pubin", "-inform", "DER", "-in", cache + ".pub.der", "-out", cache + ".pub.pem")
        # Subject = exactly the issuer DN Caliptra put in the LDevID cert; SKI = LDevID's AKI keyid
        issuer = subprocess.run(["openssl", "x509", "-inform", "DER", "-in", ldev_der, "-noout", "-issuer",
                                 "-nameopt", "RFC2253"], capture_output=True, text=True, check=True).stdout.strip()[len("issuer="):]
        txt = subprocess.run(["openssl", "x509", "-inform", "DER", "-in", ldev_der, "-noout", "-ext", "authorityKeyIdentifier"],
                             capture_output=True, text=True).stdout
        aki = [l.strip() for l in txt.splitlines() if ":" in l and "Authority" not in l][-1].replace("keyid:", "")
        ext = cache + ".ext.cnf"
        if alg == "ecc":
            open(ext, "w").write("[v3]\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign\n"
                                 "subjectKeyIdentifier=%s\nauthorityKeyIdentifier=keyid\n" % aki)
        else:   # size-limited (TBS <= 2820 B): only non-critical basicConstraints CA:TRUE (no KU/SKI/AKI)
            open(ext, "w").write("[v3]\nbasicConstraints=CA:TRUE\nsubjectKeyIdentifier=none\nauthorityKeyIdentifier=none\n")
        subj = "/" + "/".join(reversed(issuer.split(",")))
        ossl("x509", "-new", "-force_pubkey", cache + ".pub.pem", "-subj", subj, "-CA", crt, "-CAkey", key,
             "-extfile", ext, "-extensions", "v3", "-days", "36500" if alg == "ecc" else "3650",
             "-set_serial", "0x" + (tag if alg == "ecc" else "01"),
             "-outform", "DER", "-out", cache + ".cert.der", *(["-sha384"] if alg == "ecc" else []))
    c = open(cache + ".cert.der", "rb").read()
    _, v, L, _ = parse_tlv(c, 0)
    _, tv, tl, nxt = parse_tlv(c, v)
    tbs = c[v:nxt]
    _, av, al, nxt2 = parse_tlv(c, nxt)           # signatureAlgorithm
    _, sv, sl, _ = parse_tlv(c, nxt2)             # BIT STRING
    sig = c[sv + 1:sv + sl]
    return tbs, sig, cache + ".cert.der"

def ecdsa_rs(sig):
    _, v, L, _ = parse_tlv(sig, 0)
    _, rv, rl, n1 = parse_tlv(sig, v); _, sv, sl, _ = parse_tlv(sig, n1)
    r = int.from_bytes(sig[rv:rv + rl], "big"); s = int.from_bytes(sig[sv:sv + sl], "big")
    return r.to_bytes(48, "big"), s.to_bytes(48, "big")

# ---------------- the exercise ----------------
MEAS_IMAGE = b"Nios V SoC application image v1.0 (A5E attestation exercise)"
MEASUREMENT = hashlib.sha384(MEAS_IMAGE).digest()
METADATA = b"NIOS"                                # 4-byte TCI tag
CONTEXT = hashlib.sha384(b"nios-app-context").digest()
SVN = 1
LABEL = hashlib.sha384(b"attestation-exercise-label").digest()
NONCE1 = hashlib.sha256(b"verifier-nonce-1").digest(); NONCE2 = hashlib.sha256(b"verifier-nonce-2").digest()

def quote(tag, which, nonce):
    st, r = mbox("QUOTE_PCRS_%s_%s" % (which.upper(), tag), CMD["QUOTE_" + which.upper()], nonce)
    if st != 1: return None
    off = 8; pcrs = [r[off + 48 * i: off + 48 * (i + 1)].hex() for i in range(32)]; off += 48 * 32
    rn = r[off:off + 32].hex(); off += 32
    ctrs = list(struct.unpack_from("<32I", r, off)); off += 128
    dl = 48 if which == "ecc" else 64
    digest = r[off:off + dl]; off += dl
    sig = r[off:]
    return dict(pcrs=pcrs, nonce=rn, reset_ctrs=ctrs, digest=digest.hex(), sig=sig.hex())

summary = dict(measurement_image=MEAS_IMAGE.decode(), measurement=MEASUREMENT.hex(), metadata=METADATA.decode(),
               context=CONTEXT.hex(), svn=SVN, label=LABEL.hex(), nonce1=NONCE1.hex(), nonce2=NONCE2.hex())
st, r = mbox("FW_INFO", CMD["FW_INFO"]); summary["fw_info"] = r.hex()
st, r = mbox("GET_IDEV_ECC384_INFO", CMD["IDEV_ECC_INFO"]); idev_ecc = r[8:8 + 96]
st, r = mbox("GET_IDEV_MLDSA87_INFO", CMD["IDEV_MLDSA_INFO"]); idev_mldsa = r[8:8 + 2592]
summary["idev_ecc_pub"] = idev_ecc.hex(); summary["idev_mldsa_pub_sha384"] = hashlib.sha384(idev_mldsa).hexdigest()
ldev_e = get_cert("ldevid_ecc384", CMD["LDEV_ECC"])
fmc_e = get_cert("fmc_alias_ecc384", CMD["FMC_ECC"])
rt_e = get_cert("rt_alias_ecc384", CMD["RT_ECC"])
ldev_m = get_cert("ldevid_mldsa87", CMD["LDEV_MLDSA"])
fmc_m = get_cert("fmc_alias_mldsa87", CMD["FMC_MLDSA"])
rt_m = get_cert("rt_alias_mldsa87", CMD["RT_MLDSA"])
summary["quote_ecc_before"] = quote("before", "ecc", NONCE1)
dpe("DPE_ECC_GET_PROFILE", "ecc", 0x01, b"", P384)
dpe_certify_key("ecc", "before", LABEL)
# ---- STASH_MEASUREMENT: the SoC (Nios) reports its own measurement to Caliptra ----
st, r = mbox("STASH_MEASUREMENT", CMD["STASH"], METADATA + MEASUREMENT + CONTEXT + struct.pack("<I", SVN))
summary["stash_dpe_result"] = struct.unpack_from("<I", r, 8)[0] if st == 1 else None
summary["quote_ecc_after"] = quote("after", "ecc", NONCE2)
dpe_certify_key("ecc", "after", LABEL)
summary["dpe_ecc_chain"] = len(dpe_cert_chain("ecc"))
dpe("DPE_MLDSA_GET_PROFILE", "mldsa", 0x01, b"", MLDSA87)
dpe_certify_key("mldsa", "after", LABEL)
summary["dpe_mldsa_chain"] = len(dpe_cert_chain("mldsa"))
summary["quote_mldsa_after"] = quote("after", "mldsa", NONCE2)
# ---- IDevID certs: Caliptra only knows the key; the SoC supplies TBS + mfg-CA signature ----
tbs, sig, ref = build_idev_tbs("ecc", ecc_spki(idev_ecc[:48], idev_ecc[48:]), os.path.join(DIR, "ldevid_ecc384.der"))
r_, s_ = ecdsa_rs(sig)
st, r = mbox("GET_IDEV_ECC384_CERT", CMD["IDEV_ECC_CERT"], struct.pack("<I", len(tbs)) + r_ + s_ + tbs)
if st == 1: save_cert("idevid_ecc384", var_data(r)); summary["idev_ecc_cert_eq_openssl_ref"] = var_data(r) == open(ref, "rb").read()
tbs, sig, ref = build_idev_tbs("mldsa", mldsa_spki(idev_mldsa), os.path.join(DIR, "ldevid_mldsa87.der"))
summary["idev_mldsa_tbs_len"] = len(tbs)
st, r = mbox("GET_IDEV_MLDSA87_CERT", CMD["IDEV_MLDSA_CERT"], struct.pack("<I", len(tbs)) + sig + b"\0" + tbs)
if st == 1: save_cert("idevid_mldsa87", var_data(r)); summary["idev_mldsa_cert_eq_openssl_ref"] = var_data(r) == open(ref, "rb").read()
summary["log"] = LOG
json.dump(summary, open(os.path.join(DIR, "attest_summary.json"), "w"), indent=1)
open(os.path.join(DIR, ".req.tmp"), "w").write("00000000\n00000000\n")
os.rename(os.path.join(DIR, ".req.tmp"), os.path.join(DIR, "req_%03d.hex" % n_req))
print("[driver] done, %d commands" % n_req)

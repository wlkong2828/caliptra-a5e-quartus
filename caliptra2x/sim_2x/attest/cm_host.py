#!/usr/bin/env python3
"""Host-side reference crypto for crypto2_driver.py (Caliptra 2.x crypto mailbox exercise 2).
Only the `openssl` command (>= 3.5 for ML-KEM) and the Python standard library are used, so it runs on
any machine that can run the driver (no pip packages).  TEST material only.
  aes_ecb / aes_cbc / aes_ctr     : `openssl enc -aes-256-{ecb,cbc,ctr} -nopad`
  gcm_encrypt / gcm_decrypt       : AES-256-GCM (NIST SP 800-38D) = openssl AES-CTR/ECB + GHASH in Python
  kdf_counter                     : NIST SP 800-108 HMAC counter mode, one block: HMAC(K, 00000001 || label)
  hkdf_extract / hkdf_expand1     : RFC 5869 (expand: first block T(1) = HMAC(PRK, info || 0x01))
  ecdh_p384 / mlkem_* helpers     : `openssl pkeyutl -derive / -encap / -decap`, `openssl genpkey`
"""
import hashlib, hmac, os, subprocess, tempfile

def osl(*a, **kw):
    return subprocess.run(["openssl"] + list(a), capture_output=True, **kw)

def _enc(cipher, key, data, iv=None, decrypt=False):
    args = ["enc", "-" + cipher, "-K", key.hex(), "-nopad", "-nosalt"]
    if iv is not None: args += ["-iv", iv.hex()]
    if decrypt: args.append("-d")
    r = osl(*args, input=data)
    if r.returncode: raise RuntimeError("openssl enc failed: " + r.stderr.decode())
    return r.stdout

def aes_ecb(key, data): return _enc("aes-256-ecb", key, data)
def aes_cbc(key, iv, data, decrypt=False): return _enc("aes-256-cbc", key, data, iv, decrypt)
def aes_ctr(key, iv, data): return _enc("aes-256-ctr", key, data, iv)

# ---- AES-256-GCM (96-bit IV) ----
def _gmul(x, y):
    R, z, v = 0xE1 << 120, 0, x
    for i in range(127, -1, -1):
        if (y >> i) & 1: z ^= v
        v = (v >> 1) ^ R if v & 1 else v >> 1
    return z

def ghash(h, aad, ct):
    H, y = int.from_bytes(h, "big"), 0
    def blocks(b):
        b = b + b"\0" * (-len(b) % 16)
        return [b[i:i + 16] for i in range(0, len(b), 16)]
    for blk in blocks(aad) + blocks(ct) + [(8 * len(aad)).to_bytes(8, "big") + (8 * len(ct)).to_bytes(8, "big")]:
        y = _gmul(y ^ int.from_bytes(blk, "big"), H)
    return y.to_bytes(16, "big")

def gcm_encrypt(key, iv12, aad, pt):
    assert len(iv12) == 12
    h = aes_ecb(key, b"\0" * 16)
    j0 = iv12 + b"\0\0\0\1"
    ct = aes_ctr(key, iv12 + b"\0\0\0\2", pt) if pt else b""
    s = ghash(h, aad, ct)
    tag = bytes(a ^ b for a, b in zip(aes_ecb(key, j0), s))
    return ct, tag

def gcm_decrypt(key, iv12, aad, ct, tag):
    pt = aes_ctr(key, iv12 + b"\0\0\0\2", ct) if ct else b""
    _, t = gcm_encrypt(key, iv12, aad, pt)
    return pt, hmac.compare_digest(t[:len(tag)], tag)

# ---- KDFs ----
def _hm(alg): return {"sha384": hashlib.sha384, "sha512": hashlib.sha512}[alg]
def hmac_ref(alg, key, data): return hmac.new(key, data, _hm(alg)).digest()
def kdf_counter(alg, key, label, n):  # SP 800-108 counter mode, i = 1 (32-bit BE), no L / context field
    return hmac_ref(alg, key, (1).to_bytes(4, "big") + label)[:n]
def hkdf_extract(alg, salt, ikm): return hmac_ref(alg, salt, ikm)
def hkdf_expand1(alg, prk, info, n): return hmac_ref(alg, prk, info + b"\x01")[:n]

# ---- P-384 ECDH ----
P384_SPKI_PREFIX = bytes.fromhex("3076301006072a8648ce3d020106052b81040022036200")
def p384_spki(xy): return P384_SPKI_PREFIX + b"\x04" + xy
def p384_genkey(pem):
    osl("ecparam", "-name", "secp384r1", "-genkey", "-noout", "-out", pem)
    der = osl("pkey", "-in", pem, "-pubout", "-outform", "DER").stdout
    assert der[:-97] == P384_SPKI_PREFIX and der[-97] == 4
    return der[-96:]                                  # x || y, big-endian
def ecdh_p384(priv_pem, peer_xy):
    with tempfile.NamedTemporaryFile(suffix=".der", delete=False) as f:
        f.write(p384_spki(peer_xy)); peer = f.name
    try:
        r = osl("pkeyutl", "-derive", "-inkey", priv_pem, "-peerkey", peer, "-keyform", "PEM", "-peerform", "DER")
        if r.returncode: raise RuntimeError(r.stderr.decode())
        return r.stdout                               # shared x-coordinate, 48 B big-endian
    finally:
        os.remove(peer)

# ---- ML-KEM-1024 ----
MLKEM1024_SPKI_PREFIX = bytes.fromhex("30820632300b06096086480165030404030382062100")
MLKEM_EK = 1568
def mlkem_spki(ek): return MLKEM1024_SPKI_PREFIX + ek
def mlkem_keygen_seed(seed64, pem):                   # FIPS 203 seed d || z
    r = osl("genpkey", "-algorithm", "ML-KEM-1024", "-pkeyopt", "hexseed:" + seed64.hex(), "-out", pem)
    if r.returncode: raise RuntimeError(r.stderr.decode())
    der = osl("pkey", "-in", pem, "-pubout", "-outform", "DER").stdout
    assert der[:-MLKEM_EK] == MLKEM1024_SPKI_PREFIX, der[:24].hex()
    return der[-MLKEM_EK:]
def mlkem_keygen(pem):
    osl("genpkey", "-algorithm", "ML-KEM-1024", "-out", pem)
    der = osl("pkey", "-in", pem, "-pubout", "-outform", "DER").stdout
    return der[-MLKEM_EK:]
def mlkem_encap(ek, d):
    pk, ct, ss = os.path.join(d, "mlkem_ek.der"), os.path.join(d, "mlkem_ct.tmp"), os.path.join(d, "mlkem_ss.tmp")
    open(pk, "wb").write(mlkem_spki(ek))
    r = osl("pkeyutl", "-encap", "-pubin", "-inkey", pk, "-keyform", "DER", "-out", ct, "-secret", ss)
    if r.returncode: raise RuntimeError(r.stderr.decode())
    c, s = open(ct, "rb").read(), open(ss, "rb").read()
    for f in (pk, ct, ss): os.remove(f)
    return c, s
def mlkem_decap(priv_pem, ct_bytes, d):
    ct, ss = os.path.join(d, "mlkem_ct.tmp"), os.path.join(d, "mlkem_ss.tmp")
    open(ct, "wb").write(ct_bytes)
    r = osl("pkeyutl", "-decap", "-inkey", priv_pem, "-in", ct, "-secret", ss)
    if r.returncode: raise RuntimeError(r.stderr.decode())
    s = open(ss, "rb").read()
    for f in (ct, ss): os.remove(f)
    return s

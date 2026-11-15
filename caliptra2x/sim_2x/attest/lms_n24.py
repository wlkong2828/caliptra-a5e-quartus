#!/usr/bin/env python3
"""Minimal RFC 8554 / NIST SP 800-208 LMS for the ONE parameter set Caliptra 2.x fw-2.1.4 LMS_SIGNATURE_VERIFY
accepts (runtime/src/verify.rs): LMS_SHA256_M24_H15 (type 12) + LMOTS_SHA256_N24_W4 (type 7), SHA-256/192.
keygen() builds the full 2^15 tree (~25M SHA-256 calls, parallelised); sign(q) uses the cached tree.
TEST material only (private seed is derived from a public string)."""
import hashlib, json, os, struct, sys
from multiprocessing import Pool

N, W, P, LS, H = 24, 4, 51, 4, 15
LMS_TYPE, OTS_TYPE = 12, 7
D_PBLC, D_MESG, D_LEAF, D_INTR = b"\x80\x80", b"\x81\x81", b"\x82\x82", b"\x83\x83"
u32 = lambda x: struct.pack(">I", x)
u16 = lambda x: struct.pack(">H", x)
def Hh(b): return hashlib.sha256(b).digest()[:N]

def coef(S, i):            # w=4: nibble i, MSB first
    return (S[i // 2] >> (4 * (1 - i % 2))) & 0xF
def cksm(Q):
    s = sum(15 - coef(Q, i) for i in range(N * 8 // W))
    return u16(s << LS)
def chain(I, q, i, x, a, b):
    pre = I + u32(q) + u16(i)
    for j in range(a, b):
        x = hashlib.sha256(pre + bytes([j]) + x).digest()[:N]
    return x
def ots_priv(I, seed, q, i):
    return Hh(I + u32(q) + u16(i) + b"\xff" + seed)

def ots_pub(args):
    I, seed, q = args
    K = b"".join(chain(I, q, i, ots_priv(I, seed, q, i), 0, 15) for i in range(P))
    return Hh(I + u32(q) + D_PBLC + K)

def keygen(I, seed, procs=None):
    with Pool(procs) as pool:
        ots = pool.map(ots_pub, [(I, seed, q) for q in range(1 << H)], chunksize=256)
    T = [None] * (2 << H)
    for q in range(1 << H):
        r = (1 << H) + q
        T[r] = Hh(I + u32(r) + D_LEAF + ots[q])
    for r in range((1 << H) - 1, 0, -1):
        T[r] = Hh(I + u32(r) + D_INTR + T[2 * r] + T[2 * r + 1])
    return T

def pubkey(I, T): return u32(LMS_TYPE) + u32(OTS_TYPE) + I + T[1]

def sign(I, seed, T, q, msg, C=None):
    if C is None: C = Hh(b"C" + I + u32(q) + seed)
    Q = Hh(I + u32(q) + D_MESG + C + msg)
    V = Q + cksm(Q)
    y = b"".join(chain(I, q, i, ots_priv(I, seed, q, i), 0, coef(V, i)) for i in range(P))
    r = (1 << H) + q
    path = b"".join(T[(r >> k) ^ 1] for k in range(H))
    return u32(q) + u32(OTS_TYPE) + C + y + u32(LMS_TYPE) + path

def verify(pub, sig, msg):
    lt, ot, I, Tr = struct.unpack(">II", pub[:8]) + (pub[8:24], pub[24:48])
    if (lt, ot) != (LMS_TYPE, OTS_TYPE) or len(sig) != 4 + 4 + N + P * N + 4 + H * N: return False
    q, sot = struct.unpack(">II", sig[:8]); C = sig[8:8 + N]; y = sig[8 + N:8 + N + P * N]
    off = 8 + N + P * N; slt = struct.unpack(">I", sig[off:off + 4])[0]; path = sig[off + 4:]
    if sot != OTS_TYPE or slt != LMS_TYPE or q >= (1 << H): return False
    Q = Hh(I + u32(q) + D_MESG + C + msg); V = Q + cksm(Q)
    z = b"".join(chain(I, q, i, y[i * N:(i + 1) * N], coef(V, i), 15) for i in range(P))
    Kc = Hh(I + u32(q) + D_PBLC + z)
    node = (1 << H) + q; tmp = Hh(I + u32(node) + D_LEAF + Kc)
    for k in range(H):
        pk = path[k * N:(k + 1) * N]
        tmp = Hh(I + u32(node // 2) + D_INTR + (pk + tmp if node & 1 else tmp + pk))
        node //= 2
    return tmp == Tr

def test_key():
    seed = hashlib.sha256(b"A5E Caliptra 2.x LMS N24/H15 TEST seed (not secret)").digest()[:N]
    I = hashlib.sha256(b"A5E Caliptra 2.x LMS I").digest()[:16]
    return I, seed

def load_or_keygen(cache):
    """Tree cache = T[1..2^(H+1)-1] concatenated (24 B each); rebuilt (~1-3 min on 8 cores) if missing/stale."""
    I, seed = test_key()
    if os.path.exists(cache):
        b = open(cache, "rb").read()
        if len(b) == ((2 << H) - 1) * N:
            T = [None] + [b[k * N:(k + 1) * N] for k in range((2 << H) - 1)]
            return I, seed, T
    T = keygen(I, seed)
    open(cache + ".tmp", "wb").write(b"".join(T[1:])); os.rename(cache + ".tmp", cache)
    return I, seed, T

if __name__ == "__main__":   # lms_n24.py CACHE.bin : build the test key tree, self-test sign/verify
    import time
    t0 = time.time(); I, seed, T = load_or_keygen(sys.argv[1]); print("keygen/load %.1fs" % (time.time() - t0))
    pub = pubkey(I, T); h = hashlib.sha384(b"x").digest(); sg = sign(I, seed, T, 5, h)
    print("pub", pub.hex(), "self-test", verify(pub, sg, h), not verify(pub, sg, bytes([h[0] ^ 1]) + h[1:]))

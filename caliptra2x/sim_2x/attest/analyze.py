#!/usr/bin/env python3
"""Decode + verify the attestation artefacts written by attest_driver.py in DIR (emu or rtl).
   analyze.py DIR [OTHER_DIR]   -> DIR/analysis.json (+ byte-compare vs OTHER_DIR if given)
   Prints the JSON report, then 'ANALYZE PASS' (exit 0) or 'ANALYZE FAIL: ...' (exit 1).
   Gating: every chain link + strict full chain OK, DPE chain == mailbox certs, IDevID key == *_INFO, PCR31 ==
   SHA-384(0^48||M), M in the post-stash DPE leaves only, quote signatures verify with FMC Alias, and (with OTHER_DIR)
   every DER identical. The quote digest recomputation is reported as WARN only (known RTL-vs-emulator open item)."""
import hashlib, json, os, struct, subprocess, sys, tempfile
DIR = os.path.abspath(sys.argv[1]); OTHER = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else None
CA = os.path.abspath(os.environ.get("ATTEST_CA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "testca")))
S = json.load(open(os.path.join(DIR, "attest_summary.json")))
OID = {"2.23.133.5.4.1": "tcg-dice-TcbInfo", "2.23.133.5.4.5": "tcg-dice-MultiTcbInfo", "2.23.133.5.4.4": "tcg-dice-Ueid",
       "2.23.133.5.4.100.6": "tcg-dice-kp-identityInit", "2.23.133.5.4.100.7": "tcg-dice-kp-identityLoc",
       "2.23.133.5.4.100.8": "tcg-dice-kp-attestInit", "2.23.133.5.4.100.9": "tcg-dice-kp-attestLoc",
       "2.23.133.5.4.100.12": "tcg-dice-kp-eca", "2.16.840.1.101.3.4.2.2": "sha384", "2.16.840.1.101.3.4.2.3": "sha512"}

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
        elif n == 6: d["fwids"] = [dict(alg=OID.get(oid(children(f)[0][1]), oid(children(f)[0][1])), digest=children(f)[1][1].hex())
                                   for _, f in children(c)]
        elif n == 7: d["flags"] = c.hex()
        elif n == 8: d["vendorInfo"] = c.hex()
        elif n == 9: d["type"] = c.hex() + (" ('%s')" % c.decode() if all(32 <= x < 127 for x in c) else "")
        elif n == 10: d["flagsMask"] = c.hex()
    return d
def cert_exts(der):
    tbs = children(tlv(der, 0)[1])[0][1]
    out = []
    for t, c in children(tbs):
        if t == 0xa3:
            for _, e in children(children(c)[0][1]):
                parts = children(e); o = oid(parts[0][1]); crit = len(parts) == 3 and parts[1][1] == b"\xff"
                val = parts[-1][1]; ent = dict(oid=o, name=OID.get(o, ""), critical=crit)
                if o == "2.23.133.5.4.1": ent["tcb_info"] = tcbinfo(tlv(val, 0)[1])
                elif o == "2.23.133.5.4.5": ent["multi_tcb_info"] = [tcbinfo(c2) for _, c2 in children(tlv(val, 0)[1])]
                elif o == "2.23.133.5.4.4": ent["ueid"] = children(tlv(val, 0)[1])[0][1].hex()
                out.append(ent)
    return out
def ossl(*a, inp=None):
    r = subprocess.run(["openssl", *a], capture_output=True, text=True, input=inp); return (r.stdout + r.stderr).strip()
def info(name):
    p = os.path.join(DIR, name + ".der")
    if not os.path.exists(p): return None
    der = open(p, "rb").read(); pem = os.path.join(DIR, name + ".pem")
    txt = ossl("x509", "-in", pem, "-noout", "-text")
    key = [l.strip() for l in txt.splitlines() if "Public Key Algorithm" in l][0].split(":", 1)[1].strip()
    sig = [l.strip() for l in txt.splitlines() if "Signature Algorithm" in l][0].split(":", 1)[1].strip()
    g = lambda f: ossl("x509", "-in", pem, "-noout", f, "-nameopt", "RFC2253").split("=", 1)[1]
    ku = [l.strip() for l in txt.split("Key Usage:")[1].splitlines()[1:2]] if "X509v3 Key Usage" in txt else []
    bc = txt.split("Basic Constraints:")[1].splitlines()[1].strip() if "Basic Constraints" in txt else ""
    return dict(file=name + ".der", size=len(der), sha256=hashlib.sha256(der).hexdigest(), subject=g("-subject"),
                issuer=g("-issuer"), serial=g("-serial"), not_before=g("-startdate"), not_after=g("-enddate"),
                key_alg=key, sig_alg=sig, basic_constraints=bc, key_usage=ku, extensions=cert_exts(der))
ECC = ["idevid_ecc384", "ldevid_ecc384", "fmc_alias_ecc384", "rt_alias_ecc384", "dpe_ecc_leaf_after"]
MLD = ["idevid_mldsa87", "ldevid_mldsa87", "fmc_alias_mldsa87", "rt_alias_mldsa87", "dpe_mldsa_leaf_after"]
A = dict(certs={}, verify={}, quote={}, measurement={}, compare={})
for n in ECC + MLD + ["dpe_ecc_leaf_before"] + ["dpe_%s_chain_%d" % (w, i) for w in ("ecc", "mldsa") for i in range(3)]:
    i = info(n)
    if i: A["certs"][n] = i
# ---- chain verification (each link, then whole chain to the test mfg CA root) ----
def verify(chain, root):
    out = {}
    pems = [os.path.join(DIR, c + ".pem") for c in chain]
    for k in range(len(chain)):
        issuer = root if k == 0 else pems[k - 1]
        r = ossl("verify", "-partial_chain", "-ignore_critical", "-CAfile", issuer, pems[k])
        out["%s <- %s" % (chain[k], "TEST mfg CA" if k == 0 else chain[k - 1])] = r.splitlines()[-1].split(": ", 1)[-1]
    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as u:
        for p in pems[:-1]: u.write(open(p).read())
    out["FULL %s (root=TEST mfg CA, -ignore_critical)" % " > ".join(chain)] = ossl("verify", "-ignore_critical", "-CAfile", root, "-untrusted", u.name, pems[-1]).splitlines()[-1].split(": ", 1)[-1]
    out["FULL strict (no -ignore_critical)"] = ossl("verify", "-CAfile", root, "-untrusted", u.name, pems[-1]).replace("\n", " | ")[-160:]
    return out
A["verify"]["ecc384"] = verify(ECC, os.path.join(CA, "test_mfg_ca_ecc.pem"))
A["verify"]["mldsa87"] = verify(MLD, os.path.join(CA, "test_mfg_ca_mldsa.pem"))
# DPE GetCertificateChain == the individual mailbox certs?
for w, names in (("ecc", ECC), ("mldsa", MLD)):
    A["verify"]["dpe_%s_chain_matches_mailbox_certs" % w] = [
        open(os.path.join(DIR, "dpe_%s_chain_%d.der" % (w, i)), "rb").read() == open(os.path.join(DIR, names[i + 1] + ".der"), "rb").read()
        for i in range(3)]
# IDevID cert pubkey == GET_IDEV_*_INFO
pk = ossl("x509", "-in", os.path.join(DIR, "idevid_ecc384.pem"), "-noout", "-pubkey")
spki = subprocess.run(["openssl", "pkey", "-pubin", "-outform", "DER"], input=pk.encode(), capture_output=True).stdout
A["verify"]["idevid_ecc_cert_key_eq_GET_IDEV_ECC384_INFO"] = spki[-96:].hex() == S["idev_ecc_pub"]
pk = ossl("x509", "-in", os.path.join(DIR, "idevid_mldsa87.pem"), "-noout", "-pubkey")
spki = subprocess.run(["openssl", "pkey", "-pubin", "-outform", "DER"], input=pk.encode(), capture_output=True).stdout
A["verify"]["idevid_mldsa_cert_key_eq_GET_IDEV_MLDSA87_INFO"] = hashlib.sha384(spki[-2592:]).hexdigest() == S["idev_mldsa_pub_sha384"]
# ---- measurement path ----
M = bytes.fromhex(S["measurement"]); exp31 = hashlib.sha384(b"\0" * 48 + M).hexdigest()
A["measurement"] = dict(value=S["measurement"], tag=S["metadata"], svn=S["svn"], stash_dpe_result=S["stash_dpe_result"],
    pcr31_before=S["quote_ecc_before"]["pcrs"][31], pcr31_after=S["quote_ecc_after"]["pcrs"][31],
    pcr31_expected_sha384_zero48_concat_meas=exp31, pcr31_matches=S["quote_ecc_after"]["pcrs"][31] == exp31,
    pcr31_mldsa_quote=S["quote_mldsa_after"]["pcrs"][31])
def find_meas(name):
    hits = []
    for e in A["certs"].get(name, {}).get("extensions", []):
        for k, t in enumerate(e.get("multi_tcb_info", []) + ([e["tcb_info"]] if "tcb_info" in e else [])):
            for f in t.get("fwids", []):
                if f["digest"] == S["measurement"]: hits.append(dict(ext=e["name"], tcb_index=k, type=t.get("type"), svn=t.get("svn"), fwid_alg=f["alg"]))
    return hits
for n in ("dpe_ecc_leaf_before", "dpe_ecc_leaf_after", "dpe_mldsa_leaf_after", "rt_alias_ecc384"):
    A["measurement"]["found_in_" + n] = find_meas(n)
# ---- PCR quotes ----
def pubpem(name):
    return ossl("x509", "-in", os.path.join(DIR, name + ".pem"), "-noout", "-pubkey")
def der_int(b): b = b.lstrip(b"\0") or b"\0"; b = (b"\0" + b) if b[0] & 0x80 else b; return bytes([2, len(b)]) + b
for q, w in (("quote_ecc_before", "ecc"), ("quote_ecc_after", "ecc"), ("quote_mldsa_after", "mldsa")):
    Q = S[q]; pcrs = b"".join(bytes.fromhex(p) for p in Q["pcrs"]); nonce = bytes.fromhex(Q["nonce"])
    # Caliptra gen_pcr_hash = SHA-512(PCR0..31 || nonce), nonce loaded as big-endian dwords (bswap32 of the
    # request bytes). ECC quote: first 48 B; MLDSA quote: dword-reversed register image = byte-reversed digest.
    nsw = b"".join(nonce[i:i + 4][::-1] for i in range(0, 32, 4))
    full = hashlib.sha512(pcrs + nsw).digest()
    # RTL pv_gen_hash feeds NONCE[7]..NONCE[0] (pv_gen_hash.sv, GEN_HASH_NONCE state): request nonce with its
    # 4-byte chunks in reverse order. The emulator feeds NONCE[0]..NONCE[7] (the bswap32 form above).
    ndr = b"".join(nonce[i:i + 4] for i in range(28, -1, -4))
    full_rtl = hashlib.sha512(pcrs + ndr).digest()
    m = (lambda f: f[:48].hex() == Q["digest"]) if w == "ecc" else (lambda f: f[::-1].hex() == Q["digest"])
    res = dict(nonce=Q["nonce"], digest=Q["digest"], digest_matches_emu_model=m(full), digest_matches_rtl_model=m(full_rtl),
               digest_recomputed_from_pcrs_and_nonce=m(full) or m(full_rtl))
    sig = bytes.fromhex(Q["sig"]); dg = bytes.fromhex(Q["digest"])
    td = tempfile.mkdtemp()
    open(td + "/d", "wb").write(dg)
    if w == "ecc":
        body = der_int(sig[:48]) + der_int(sig[48:96]); open(td + "/s", "wb").write(bytes([0x30, len(body)]) + body)
        cands = ECC[:4]
    else:
        open(td + "/s", "wb").write(sig[:4627]); cands = MLD[:4]
    for c in cands:
        open(td + "/k.pem", "w").write(pubpem(c))
        r = ossl("pkeyutl", "-verify", "-pubin", "-inkey", td + "/k.pem", "-in", td + "/d", "-sigfile", td + "/s")
        res["sig_by_" + c] = "Verified OK" in r or "Signature Verified Successfully" in r
    A["quote"][q] = res
# ---- Step A vs Step B ----
if OTHER:
    for f in sorted(os.listdir(DIR)):
        if f.endswith(".der") or (f.startswith("resp_") and f.endswith(".bin")):
            o = os.path.join(OTHER, f)
            A["compare"][f] = (open(os.path.join(DIR, f), "rb").read() == open(o, "rb").read()) if os.path.exists(o) else "missing"
A = json.loads(json.dumps(A).replace(DIR + "/", ""))       # keep analysis.json free of local paths
json.dump(A, open(os.path.join(DIR, "analysis.json"), "w"), indent=1)
print(json.dumps(dict(verify=A["verify"], measurement=A["measurement"], quote=A["quote"],
                      compare_mismatch=[k for k, v in A["compare"].items() if v is not True]), indent=1))

# ---- PASS/FAIL summary ----
fail, warn = [], []
for alg, v in A["verify"].items():
    if isinstance(v, dict):
        for k, r in v.items():
            if k.startswith("FULL strict"):
                if not r.rstrip().endswith("OK"): fail.append("%s %s" % (alg, k))
            elif r != "OK": fail.append("%s %s: %s" % (alg, k, r))
    elif isinstance(v, list):
        if not all(v): fail.append(alg)
    elif v is not True: fail.append(alg)
m = A["measurement"]
if not m["pcr31_matches"]: fail.append("PCR31 != SHA-384(0^48||M)")
if m["found_in_dpe_ecc_leaf_before"] or not m["found_in_dpe_ecc_leaf_after"] or not m["found_in_dpe_mldsa_leaf_after"]:
    fail.append("measurement not (only) in post-stash DPE leaves")
for q, r in A["quote"].items():
    if not r.get("sig_by_fmc_alias_ecc384", r.get("sig_by_fmc_alias_mldsa87")): fail.append(q + " signature not by FMC Alias")
    if not r["digest_recomputed_from_pcrs_and_nonce"]: warn.append(q + " digest != SHA-512(PCRs||bswap32(nonce)) recomputation")
der_mis = [k for k, v in A["compare"].items() if k.endswith(".der") and v is not True]
bin_mis = [k for k, v in A["compare"].items() if k.endswith(".bin") and v is not True]
if der_mis: fail.append("DER mismatch vs %s: %s" % (OTHER, der_mis))
if bin_mis: warn.append("raw response mismatch vs %s: %s" % (OTHER, bin_mis))
for w in warn: print("ANALYZE WARN:", w)
if fail:
    print("ANALYZE FAIL:", "; ".join(fail)); sys.exit(1)
print("ANALYZE PASS (%d certs, %d DER compared)" % (len(A["certs"]), sum(k.endswith(".der") for k in A["compare"])))

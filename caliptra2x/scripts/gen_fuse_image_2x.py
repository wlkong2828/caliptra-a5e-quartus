#!/usr/bin/env python3
"""Generate fw_2x/fuse_image_2x.hex: the SoC "OTP" image that rtl_2x/soc_fuse_ctrl2x pushes into
Caliptra 2.x (caliptra-rtl v2.1.2) soc_ifc over AXI. One entry per line, $readmemh 64-bit word
{AXI byte address[31:0], data[31:0]} (the 2.x fuse map has holes, so addresses are explicit).
The controller appends CPTRA_FUSE_WR_DONE=1 itself.

PRODUCTION-LIFECYCLE *MIMIC* (FPGA study) - same policy as the 1.x scripts/gen_fuse_image.py.
UDS / field entropy are fixed STUDY values, NOT real secrets. Values chosen so ROM rom-2.1.3-1
image verification passes in DEVICE_PRODUCTION + debug locked with the test-signed bundle in fw_2x/:
  * FUSE_VENDOR_PK_HASH  = SHA-384(preamble.vendor_pub_key_info)  (ECC + PQC key descriptors)
  * CPTRA_OWNER_PK_HASH  = SHA-384(preamble.owner_pub_keys)        (ECC + MLDSA-87 owner key)
    then CPTRA_OWNER_PK_HASH_LOCK = 1. In 2.x the owner hash is an architectural register
    (pwrgood domain, write-once lock), no longer a fuse.
    Both as 12 big-endian words (caliptra-sw test/src/lib.rs image_pk_desc_hash/bytes_to_be_words_48).
  * FUSE_PQC_KEY_TYPE    = manifest.pqc_key_type (1 = MLDSA, 3 = LMS; ROM compares when not Unprovisioned)
  * revocations 0, SVN fuses 0 (bundle header SVN must be >= fuse SVN), anti-rollback disable 0
  * MANUF_DBG_UNLOCK_TOKEN / SOC_MANIFEST_* / HEK_SEED = 0 (passive mode, unused)
"""
import os, struct, hashlib, sys
HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "fw_2x", "caliptra-fw-bundle.bin")
OUT = os.path.join(HERE, "..", "fw_2x", "fuse_image_2x.hex")
b = open(BUNDLE, "rb").read()
marker, msize, pqc_type = struct.unpack_from("<IIB", b, 0)
assert marker == 0x324E4D43, "bad 2.x MANIFEST_MARKER %08x (expect 'CMN2')" % marker
assert pqc_type in (1, 3), pqc_type
# ImageManifest (caliptra-sw image/types 2.x): marker,size,pqc_key_type+rsvd (12 B) | preamble:
#   vendor_pub_key_info = ecc desc (4 + 4*48) + pqc desc (4 + 32*48)       = 1736
#   vendor_ecc_pub_key_idx 4 | vendor_ecc_active_pub_key 96 | vendor_pqc_pub_key_idx 4
#   vendor_pqc_active_pub_key 2592 | vendor_sigs 96 + 4628 | owner_pub_keys 96 + 2592 | owner_sigs | rsvd 8
VPKI_OFF, VPKI_LEN = 12, (4 + 4*48) + (4 + 32*48)
OWNER_OFF = VPKI_OFF + VPKI_LEN + 4 + 96 + 4 + 2592 + (96 + 4628)
OWNER_LEN = 96 + 2592
PREAMBLE_LEN = VPKI_LEN + 4 + 96 + 4 + 2592 + 2*(96 + 4628) + OWNER_LEN + 8
HDR_OFF = 12 + PREAMBLE_LEN
assert msize == HDR_OFF + 160 + 2*104, "manifest size %d does not match the 2.x layout" % msize
hdr_svn = struct.unpack_from("<I", b, HDR_OFF + 76)[0]
assert hdr_svn == 0, "bundle FW SVN=%d; set FUSE_RUNTIME_SVN <= image SVN" % hdr_svn
pqc_desc_type = b[VPKI_OFF + 196 + 2]
assert pqc_desc_type == pqc_type, (pqc_desc_type, pqc_type)
def be_words(d): return list(struct.unpack(">12I", d))
VENDOR_HASH = be_words(hashlib.sha384(b[VPKI_OFF:VPKI_OFF+VPKI_LEN]).digest())
OWNER_HASH  = be_words(hashlib.sha384(b[OWNER_OFF:OWNER_OFF+OWNER_LEN]).digest())
UDS = [0x1F2E3D4C ^ (0x9E3779B9 * (i + 1) & 0xFFFFFFFF) for i in range(16)]   # STUDY UDS seed (512 b)
FE  = [0xA7C3E519 ^ (0x85EBCA6B * (i + 1) & 0xFFFFFFFF) for i in range(8)]    # STUDY field entropy
S = 0x30000   # soc_ifc base on the SoC AXI
ent = []
def put(off, words): ent.extend((S + off + 4*i, w) for i, w in enumerate(words))
put(0x200, UDS)          # FUSE_UDS_SEED[0..15]
put(0x240, FE)           # FUSE_FIELD_ENTROPY[0..7]
put(0x260, VENDOR_HASH)  # FUSE_VENDOR_PK_HASH[0..11]
put(0x290, [0])          # FUSE_ECC_REVOCATION
put(0x2b4, [0])          # FUSE_FMC_KEY_MANIFEST_SVN
put(0x2b8, [0]*4)        # FUSE_RUNTIME_SVN[0..3]
put(0x2c8, [0])          # FUSE_ANTI_ROLLBACK_DISABLE
put(0x2cc, [0]*24)       # FUSE_IDEVID_CERT_ATTR[0..23]
put(0x32c, [0]*4)        # FUSE_IDEVID_MANUF_HSM_ID[0..3]
put(0x340, [0])          # FUSE_LMS_REVOCATION
put(0x344, [0])          # FUSE_MLDSA_REVOCATION
put(0x348, [1])          # FUSE_SOC_STEPPING_ID (test)
put(0x34c, [0]*16)       # FUSE_MANUF_DBG_UNLOCK_TOKEN[0..15]
put(0x38c, [pqc_type])   # FUSE_PQC_KEY_TYPE
put(0x390, [0]*4)        # FUSE_SOC_MANIFEST_SVN[0..3]
put(0x3a0, [0])          # FUSE_SOC_MANIFEST_MAX_SVN
put(0x3c0, [0]*8)        # FUSE_HEK_SEED[0..7]
n_fuse = len(ent)
put(0x140, OWNER_HASH)   # CPTRA_OWNER_PK_HASH[0..11]
put(0x170, [1])          # CPTRA_OWNER_PK_HASH_LOCK
with open(OUT, "w") as f:
    for a, d in ent: f.write("%08x%08x\n" % (a, d))
print("wrote %s: %d entries (%d fuse words + %d owner-hash/lock); +FUSE_WR_DONE = %d AXI writes; pqc_key_type=%d"
      % (OUT, len(ent), n_fuse, len(ent) - n_fuse, len(ent) + 1, pqc_type))
print("vendor_pk_hash", " ".join("%08x" % w for w in VENDOR_HASH))
print("owner_pk_hash ", " ".join("%08x" % w for w in OWNER_HASH))

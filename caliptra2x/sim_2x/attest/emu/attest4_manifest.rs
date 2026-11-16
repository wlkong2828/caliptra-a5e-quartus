// Licensed under the Apache-2.0 license
//! attest4 (SIMULATION_2X section 12): build a Caliptra SoC authorization manifest (AuthorizationManifest, "ATM2")
//! with the caliptra-sw fw-2.1.4 auth-manifest generator crate (caliptra-auth-man-gen + caliptra-image-crypto).
//! Keys = caliptra-sw's public TEST ("fake") keys, the same ones that signed our firmware bundle:
//!   vendor FW key   = VENDOR_*_KEY_0 (bundle active vendor key, ecc_key_idx 0 / pqc_key_idx 0) -> endorses the manifest vendor keys
//!   vendor man. key = VENDOR_*_KEY_1                                                             -> signs the IMC (if flag bit 0)
//!   owner FW key    = OWNER_*_KEY (bundle owner key, hash in CPTRA_OWNER_PK_HASH)                -> endorses the manifest owner keys
//!   owner man. key  = OWNER_*_KEY                                                                -> signs the IMC
//! Build: copy into caliptra-sw/auth-manifest/app/examples/ and
//!   cargo build --release -p caliptra-auth-manifest-app --example attest4_manifest
//! Usage: attest4_manifest OUT.bin PQC(1=ML-DSA,3=LMS) SVN FLAGS KEYMODE ENTRY...
//!   KEYMODE: good | wrong_vendor_fw (vendor keys endorsed by KEY_1, not the bundle's KEY_0)
//!            | wrong_owner_fw (owner keys endorsed by vendor KEY_1 instead of the bundle owner key)
//!   ENTRY  : fw_id:component_id:image_flags:digest_hex(48 B)     (all ints accept 0x..)
//! TEST ONLY: the private halves of these keys are public.
use caliptra_auth_man_gen::default_test_manifest::*;
use caliptra_auth_man_gen::{AuthManifestGenerator, AuthManifestGeneratorConfig};
use caliptra_auth_man_types::{AuthManifestFlags, AuthManifestImageMetadata};
use caliptra_image_crypto::OsslCrypto;
use caliptra_image_types::FwVerificationPqcKeyType;
use zerocopy::IntoBytes;

fn num(s: &str) -> u32 {
    if let Some(h) = s.strip_prefix("0x") { u32::from_str_radix(h, 16).unwrap() } else { s.parse().unwrap() }
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    if a.len() < 6 {
        eprintln!("usage: attest4_manifest OUT.bin PQC SVN FLAGS KEYMODE ENTRY...");
        std::process::exit(2);
    }
    let pqc = match num(&a[2]) { 1 => FwVerificationPqcKeyType::MLDSA, 3 => FwVerificationPqcKeyType::LMS, x => panic!("pqc {x}") };
    let svn = num(&a[3]);
    let flags = AuthManifestFlags::from_bits_retain(num(&a[4]));
    let mut list = Vec::new();
    for e in &a[6..] {
        let p: Vec<&str> = e.split(':').collect();
        let d: Vec<u8> = (0..p[3].len()).step_by(2).map(|i| u8::from_str_radix(&p[3][i..i + 2], 16).unwrap()).collect();
        list.push(AuthManifestImageMetadata {
            fw_id: num(p[0]), component_id: num(p[1]), flags: num(p[2]), digest: d.try_into().unwrap(), ..Default::default()
        });
    }
    let (vendor_fw, owner_fw) = match a[5].as_str() {
        "good" => (default_test_vendor_fw_key_info(), default_test_owner_fw_key_info()),
        "wrong_vendor_fw" => (default_test_vendor_man_key_info(), default_test_owner_fw_key_info()),
        "wrong_owner_fw" => (default_test_vendor_fw_key_info(), default_test_vendor_man_key_info()),
        m => panic!("keymode {m}"),
    };
    let cfg = AuthManifestGeneratorConfig {
        vendor_fw_key_info: Some(vendor_fw),
        vendor_man_key_info: Some(default_test_vendor_man_key_info()),
        owner_fw_key_info: Some(owner_fw),
        owner_man_key_info: Some(default_test_owner_man_key_info()),
        image_metadata_list: list,
        version: 2,
        flags,
        pqc_key_type: pqc,
        svn,
    };
    let m = AuthManifestGenerator::new(OsslCrypto::default()).generate(&cfg).unwrap();
    // Whole AuthorizationManifest (24,292 B preamble + 4 + 80 x 80 B IMC = 30,696 B). The IMC signatures cover all 80
    // slots, unused ones included (default fw_id/component_id 0xFFFFFFFF), so the IMC must not be truncated.
    let n = m.as_bytes().len();
    std::fs::write(&a[1], m.as_bytes()).unwrap();
    println!("wrote {} ({} B, {} entries, svn {}, flags {:#x}, keymode {})", a[1], n, m.image_metadata_col.entry_count, svn, flags.bits(), a[5]);
}

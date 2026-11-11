// Licensed under the Apache-2.0 license
//! Step A of the 2.x attestation exercise: boot the SAME rom-2.1.3-1 ROM + fw-2.1.4 bundle on the
//! caliptra-sw sw-emulator (caliptra-hw-model, ModelEmulated) with the SAME fuses / straps as
//! rtl_2x/nios_caliptra2x_top.sv + fw_2x/fuse_image_2x.hex, then serve runtime mailbox commands from
//! the same file protocol as the RTL testbench (+test=attest):
//!   DIR/req_NNN.hex  : cmd, dlen, little-endian dwords      (written by attest_driver.py)
//!   DIR/resp_NNN.hex : status(1=DATA_READY,2=COMPLETE,3=FAILURE), dlen, dwords, "fwerr XXXXXXXX"
//!   DIR/resp_NNN.done
//! Build: copy into caliptra-sw/hw-model/examples/ and `cargo run --release -p caliptra-hw-model
//!        --example attest_emu -- <rom.bin> <bundle.bin> <fuse_image_2x.hex> <dir>`
use caliptra_api::SocManager;
use caliptra_api_types::{DeviceLifecycle, Fuses, SecurityState};
use caliptra_hw_model::{BootParams, HwModel, InitParams, ModelError};
use std::io::Write;
use std::path::Path;

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let rom = std::fs::read(&a[1]).unwrap();
    let fw = std::fs::read(&a[2]).unwrap();
    let dir = Path::new(&a[4]);
    // Parse the SoC OTP image: {axi addr, data} per line
    let mut fuse_w = std::collections::BTreeMap::new();
    for l in std::fs::read_to_string(&a[3]).unwrap().lines() {
        let v = u64::from_str_radix(l.trim(), 16).unwrap();
        fuse_w.insert(((v >> 32) as u32) - 0x30000, v as u32);
    }
    let rd = |off: u32, n: usize| -> Vec<u32> { (0..n).map(|i| fuse_w[&(off + 4 * i as u32)]).collect() };
    let mut fuses = Fuses::default();
    fuses.uds_seed.copy_from_slice(&rd(0x200, 16));
    fuses.field_entropy.copy_from_slice(&rd(0x240, 8));
    fuses.vendor_pk_hash.copy_from_slice(&rd(0x260, 12));
    fuses.owner_pk_hash.copy_from_slice(&rd(0x140, 12));
    fuses.fuse_pqc_key_type = rd(0x38c, 1)[0];
    fuses.soc_stepping_id = rd(0x348, 1)[0] as u16;
    fuses.manuf_dbg_unlock_token = [0; 16];
    fuses.soc_manifest_max_svn = rd(0x3a0, 1)[0] as u8;
    fuses.life_cycle = DeviceLifecycle::Production;
    fuses.debug_locked = true;
    let mut ss = SecurityState::default();
    ss.set_device_lifecycle(DeviceLifecycle::Production).set_debug_locked(true);
    // RTL: cptra_obf_key = 256'h31358e8a_..._b2c3b8d5 ; word i = bits[32i+31:32i]
    let obf: [u32; 8] = [0xb2c3b8d5, 0x3dc4fd37, 0xcf1f2ce9, 0xd1bf4e16, 0xe5f5ffd6, 0x1c1b3b72, 0xf34d6a45, 0x31358e8a];
    let log = std::fs::File::create(dir.join("emu_uart.log")).unwrap();
    let mut hw = caliptra_hw_model::new_unbooted(InitParams {
        rom: &rom,
        fuses,
        security_state: ss,
        cptra_obf_key: obf,
        csr_hmac_key: [0x5A3C_96E1; 16],
        log_writer: Box::new(log),
        ..Default::default()
    })
    .unwrap();
    // CPTRA_OWNER_PK_HASH + LOCK, as soc_fuse_ctrl2x does
    let oh: [u32; 12] = rd(0x140, 12).try_into().unwrap();
    hw.soc_ifc().cptra_owner_pk_hash().write(&oh);
    hw.soc_ifc().cptra_owner_pk_hash_lock().write(|w| w.lock(true));
    hw.boot(BootParams { fw_image: Some(&fw), valid_axi_user: vec![1], ..Default::default() }).unwrap();
    hw.step_until_ready_for_runtime();
    println!("EMU ready_for_runtime");
    let mut n = 0;
    loop {
        let req = dir.join(format!("req_{n:03}.hex"));
        let Ok(txt) = std::fs::read_to_string(&req) else {
            std::thread::sleep(std::time::Duration::from_millis(100));
            continue;
        };
        let w: Vec<u32> = txt.lines().map(|l| u32::from_str_radix(l.trim(), 16).unwrap()).collect();
        let (cmd, dlen) = (w[0], w[1] as usize);
        if cmd == 0 { break; }
        let mut data: Vec<u8> = w[2..].iter().flat_map(|x| x.to_le_bytes()).collect();
        data.truncate(dlen);
        let r = hw.mailbox_execute(cmd, &data);
        let fwerr = hw.soc_ifc().cptra_fw_error_non_fatal().read();
        let mut f = std::fs::File::create(dir.join(format!("resp_{n:03}.hex"))).unwrap();
        match r {
            Ok(Some(resp)) => {
                writeln!(f, "{:08x}\n{:08x}", 1, resp.len()).unwrap();
                for c in resp.chunks(4) { let mut b = [0u8; 4]; b[..c.len()].copy_from_slice(c); writeln!(f, "{:08x}", u32::from_le_bytes(b)).unwrap(); }
            }
            Ok(None) => writeln!(f, "{:08x}\n{:08x}", 2, 0).unwrap(),
            Err(e) => { eprintln!("cmd {cmd:08x} failed: {e:?}"); let _ = matches!(e, ModelError::MailboxCmdFailed(_)); writeln!(f, "{:08x}\n{:08x}", 3, 0).unwrap() }
        }
        writeln!(f, "fwerr {:08x}", fwerr).unwrap();
        drop(f);
        std::fs::write(dir.join(format!("resp_{n:03}.done")), "emu\n").unwrap();
        println!("EMU req {n} cmd {cmd:08x} done");
        n += 1;
    }
    println!("EMU done, {n} commands");
}

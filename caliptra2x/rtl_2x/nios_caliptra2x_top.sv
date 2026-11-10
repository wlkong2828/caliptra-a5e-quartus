// nios_caliptra2x_top.sv - Nios V/m host + Caliptra 2.x (caliptra-rtl v2.1.2, passive/core-only) on
// Agilex 5 E. 2.x port of quartus_a5e_nios/rtl/nios_caliptra_top.sv (1.x): same reset gating, 2FF
// reset synchronizers, PIO map, local SoC IP (fw store + fuse controller) and straps; APB -> AXI4.
// Nios data master -> PD mm_bridge (exported, 20-bit / 1 MiB window) -> avmm_to_axi -> Caliptra AXI.
// Straps DEVICE_PRODUCTION + debug locked; STUDY (non-secret) cptra_obf_key / CSR HMAC key.
`include "config_defines.svh"
`include "caliptra_macros.svh"
module nios_caliptra2x_top #(
  parameter string ROM_INIT_FILE  = "../fw_2x/caliptra-rom.hex",
  parameter string FW_INIT_FILE   = "../fw_2x/caliptra-fw-bundle.hex",
  parameter string FUSE_IMAGE     = "../fw_2x/fuse_image_2x.hex",
  parameter int    FW_BYTES       = 253440,
  parameter int    NUM_FUSES      = 117,
  parameter logic [31:0] NIOS_AXI_USER = 32'h1,   // unique per agent, never 0xFFFF_FFFF (reserved)
  parameter logic [31:0] FUSE_AXI_USER = 32'h2
)(
  input  logic       clk,        // single clock for Nios + Caliptra (e.g. 50 MHz board osc)
  input  logic       reset_n,    // board reset / push-button, active low
  output logic [7:0] led
);
  localparam int AXI_AW = `CALIPTRA_SLAVE_ADDR_WIDTH(`CALIPTRA_SLAVE_SEL_SOC_IFC);
  localparam int AXI_IW = `CALIPTRA_AXI_ID_WIDTH;
  localparam int AXI_UW = `CALIPTRA_AXI_USER_WIDTH;

  // ---- Device init / reset qualification (unchanged from 1.x) ----
  logic ninit_done, sys_reset_n, glue_rst_n;
  rst_release u_rst_release (.ninit_done(ninit_done));
  assign sys_reset_n = reset_n & ~ninit_done;
  rst_sync_async_assert #(.STAGES(2)) u_sync_glue (.clk, .async_rst_n(sys_reset_n), .rst_n(glue_rst_n));

  // ---- Platform Designer system (Nios V/m + PIOs + exported 1 MiB Avalon window) ----
  logic [19:0] cl_address; logic cl_read, cl_write, cl_waitrequest, cl_readdatavalid;
  logic [31:0] cl_writedata, cl_readdata; logic [3:0] cl_byteenable; logic [1:0] cl_response;
  logic [31:0] ctrl_out, status_in, magic_out;
  nios_caliptra2x_sys u_sys (
    .clk_clk(clk), .reset_reset_n(sys_reset_n),
    .caliptra_axi_address(cl_address), .caliptra_axi_read(cl_read), .caliptra_axi_write(cl_write),
    .caliptra_axi_writedata(cl_writedata), .caliptra_axi_byteenable(cl_byteenable),
    .caliptra_axi_readdata(cl_readdata), .caliptra_axi_readdatavalid(cl_readdatavalid),
    .caliptra_axi_waitrequest(cl_waitrequest), .caliptra_axi_burstcount(), .caliptra_axi_debugaccess(),
    .ctrl_pio_export(ctrl_out), .status_pio_export(status_in), .magic_pio_export(magic_out));

  logic ready_for_fuses, ready_for_mb_processing, ready_for_runtime;
  // ---- SoC window decode (20-bit, 1 MiB) ----
  //   0x00000-0x3FFFF  soc_fw_store   FW bundle ROM (read-only, 256 KiB; 2.x bundle 253,440 B)
  //   0x7F000-0x7FFFF  soc_fuse_ctrl2x MMIO
  //   0x80000-0xBFFFF  Caliptra 2.x AXI (AXI addr = cl_address[17:0]: mbox_csr 0xA0000, soc_ifc 0xB0000)
  logic sel_cptra, sel_fuse, sel_fw;
  assign sel_cptra = cl_address[19];
  assign sel_fuse  = !cl_address[19] && (cl_address[18:12] == 7'h7F);
  assign sel_fw    = !cl_address[19] && !cl_address[18];
  logic [31:0] br_readdata, fuse_rdata, fw_rdata;
  logic br_readdatavalid, br_waitrequest, loc_rv, loc_rv_fuse;
  always_ff @(posedge clk or negedge glue_rst_n)
    if (!glue_rst_n) begin loc_rv <= 1'b0; loc_rv_fuse <= 1'b0; end
    else begin loc_rv <= cl_read && !sel_cptra; loc_rv_fuse <= sel_fuse; end
  assign cl_waitrequest   = sel_cptra ? br_waitrequest : 1'b0;
  assign cl_readdatavalid = br_readdatavalid | loc_rv;
  assign cl_readdata      = loc_rv ? (loc_rv_fuse ? fuse_rdata : fw_rdata) : br_readdata;

  soc_fw_store #(.DEPTH(65536), .FW_INIT_FILE(FW_INIT_FILE)) u_fw_store (
    .clk, .rd(cl_read && sel_fw), .waddr(cl_address[17:2]), .rdata(fw_rdata));

  // ---- Avalon -> AXI4 (Nios path) + fuse controller AXI write path, muxed ----
  // Register (not a continuous assign) so the AXI-user lock test can force a wrong ID.
  logic [31:0] nios_axi_user;
  always_ff @(posedge clk or negedge glue_rst_n)
    if (!glue_rst_n) nios_axi_user <= NIOS_AXI_USER; else nios_axi_user <= NIOS_AXI_USER;

  logic [AXI_AW-1:0] awaddr, araddr, n_awaddr, f_awaddr;
  logic [1:0] awburst, arburst, bresp, rresp; logic [2:0] awsize, arsize; logic [7:0] awlen, arlen;
  logic [AXI_UW-1:0] awuser, wuser, aruser, n_awuser, n_wuser, f_user;
  logic [AXI_IW-1:0] awid, arid;
  logic awlock, arlock, awvalid, awready, wvalid, wready, wlast, bvalid, bready, arvalid, arready, rvalid, rready;
  logic n_awvalid, n_wvalid, n_bready, f_awvalid, f_wvalid, f_bready, fuse_busy, bridge_idle;
  logic [31:0] wdata, rdata, n_wdata, f_wdata; logic [3:0] wstrb;
  avmm_to_axi #(.AW(AXI_AW), .IW(AXI_IW), .UW(AXI_UW)) u_bridge (
    .clk, .rst_n(glue_rst_n),
    .avs_address(cl_address[AXI_AW-1:0]), .avs_read(cl_read && sel_cptra), .avs_write(cl_write && sel_cptra),
    .avs_writedata(cl_writedata), .avs_byteenable(cl_byteenable),
    .avs_readdata(br_readdata), .avs_readdatavalid(br_readdatavalid),
    .avs_waitrequest(br_waitrequest), .avs_response(cl_response), .user_i(nios_axi_user),
    .awaddr(n_awaddr), .awburst, .awsize, .awlen, .awuser(n_awuser), .awid, .awlock,
    .awvalid(n_awvalid), .awready, .wdata(n_wdata), .wstrb, .wuser(n_wuser), .wvalid(n_wvalid),
    .wready, .wlast, .bresp, .bvalid, .bready(n_bready),
    .araddr, .arburst, .arsize, .arlen, .aruser, .arid, .arlock, .arvalid, .arready,
    .rdata, .rresp, .rvalid, .rready, .idle(bridge_idle));

  soc_fuse_ctrl2x #(.FUSE_IMAGE_FILE(FUSE_IMAGE), .NUM_FUSES(NUM_FUSES), .AW(AXI_AW), .UW(AXI_UW),
                    .FUSE_AXI_USER(FUSE_AXI_USER), .FW_BYTES(FW_BYTES)) u_fuse_ctrl (
    .clk, .rst_n(glue_rst_n), .ready_for_fuses,
    .mmio_read(cl_read && sel_fuse), .mmio_write(cl_write && sel_fuse),
    .mmio_addr(cl_address[11:0]), .mmio_wdata(cl_writedata), .mmio_rdata(fuse_rdata),
    .busy(fuse_busy), .awaddr(f_awaddr), .awvalid(f_awvalid), .awready, .wdata(f_wdata),
    .wvalid(f_wvalid), .wready, .axi_user(f_user), .bresp, .bvalid, .bready(f_bready));

  // Fuse controller owns the AXI write channels while pushing (Nios only polls fuse_ctrl STATUS,
  // a local slave, meanwhile, so the bridge is idle). Read channels always belong to the bridge.
  assign awaddr  = fuse_busy ? f_awaddr  : n_awaddr;
  assign awvalid = fuse_busy ? f_awvalid : n_awvalid;
  assign awuser  = fuse_busy ? f_user    : n_awuser;
  assign wdata   = fuse_busy ? f_wdata   : n_wdata;
  assign wvalid  = fuse_busy ? f_wvalid  : n_wvalid;
  assign wuser   = fuse_busy ? f_user    : n_wuser;
  assign bready  = fuse_busy ? f_bready  : n_bready;

  // ---- Host controls (ctrl PIO; reset value 0 => Caliptra held in reset), unchanged from 1.x ----
  logic cptra_pwrgood, cptra_rst_b, raw_pwrgood, raw_rst_b;
  assign raw_pwrgood = ctrl_out[0] & sys_reset_n;
  assign raw_rst_b   = ctrl_out[1] & sys_reset_n;
  pwrgood_sync_async_assert #(.STAGES(2)) u_sync_pwrgood (.clk, .async_pwrgood(raw_pwrgood), .pwrgood(cptra_pwrgood));
  rst_sync_async_assert     #(.STAGES(2)) u_sync_rst_b   (.clk, .async_rst_n(raw_rst_b),    .rst_n(cptra_rst_b));

  logic mailbox_data_avail, mailbox_flow_done, cptra_error_fatal, cptra_error_non_fatal, etrng_req;
  logic [63:0] generic_output_wires, generic_input_wires;
  assign generic_input_wires = 64'b0;   // Table 12: bit0 zeroization status (no source) -> 0
  // status PIO, same bit positions as 1.x (bit1 = ready_for_mb_processing, was ready_for_fw_push)
  assign status_in = {generic_output_wires[23:0],
                      etrng_req, cptra_error_non_fatal, cptra_error_fatal, mailbox_flow_done,
                      mailbox_data_avail, ready_for_runtime, ready_for_mb_processing, ready_for_fuses};

  // FPGA production-MIMIC study keys: fixed arbitrary values, NOT real product secrets.
  localparam logic [255:0] STUDY_PROD_MIMIC_OBF_KEY =
    256'h31358e8a_f34d6a45_1c1b3b72_e5f5ffd6_d1bf4e16_cf1f2ce9_3dc4fd37_b2c3b8d5;
  localparam logic [`CLP_CSR_HMAC_KEY_DWORDS-1:0][31:0] STUDY_CSR_HMAC_KEY = {`CLP_CSR_HMAC_KEY_DWORDS{32'h5A3C_96E1}};

  caliptra_passive_top #(.ROM_INIT_FILE(ROM_INIT_FILE)) u_caliptra (
    .clk, .cptra_pwrgood, .cptra_rst_b,
    .cptra_obf_key(STUDY_PROD_MIMIC_OBF_KEY), .cptra_csr_hmac_key(STUDY_CSR_HMAC_KEY),
    .security_state_device_lifecycle(2'b11),   // DEVICE_PRODUCTION
    .security_state_debug_locked(1'b1),        // debug locked
    .jtag_tck(1'b0), .jtag_tms(1'b0), .jtag_tdi(1'b0), .jtag_trst_n(1'b0), .jtag_tdo(), .jtag_tdoEn(),
    .s_axi_awaddr(awaddr), .s_axi_awburst(awburst), .s_axi_awsize(awsize), .s_axi_awlen(awlen),
    .s_axi_awuser(awuser), .s_axi_awid(awid), .s_axi_awlock(awlock), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
    .s_axi_wdata(wdata), .s_axi_wstrb(wstrb), .s_axi_wuser(wuser), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
    .s_axi_wlast(wlast), .s_axi_bresp(bresp), .s_axi_bid(), .s_axi_buser(), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
    .s_axi_araddr(araddr), .s_axi_arburst(arburst), .s_axi_arsize(arsize), .s_axi_arlen(arlen),
    .s_axi_aruser(aruser), .s_axi_arid(arid), .s_axi_arlock(arlock), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
    .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rid(), .s_axi_ruser(), .s_axi_rlast(), .s_axi_rvalid(rvalid),
    .s_axi_rready(rready),
    .ready_for_fuses, .ready_for_mb_processing, .ready_for_runtime,
    .mailbox_data_avail, .mailbox_flow_done, .cptra_error_fatal, .cptra_error_non_fatal,
    .BootFSM_BrkPoint(ctrl_out[2]), .generic_input_wires, .generic_output_wires,
    .etrng_req, .itrng_data(4'h0), .itrng_valid(1'b0), .scan_mode(1'b0));

  assign led = magic_out[7:0];
endmodule

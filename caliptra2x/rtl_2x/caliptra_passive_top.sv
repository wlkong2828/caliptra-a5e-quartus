// caliptra_passive_top.sv
// Caliptra 2.x (caliptra-rtl v2.1.2) Core/Passive-mode wrapper for FPGA (Intel Agilex 7 target).
// - Flattens SoC AXI4 subordinate (axi_if) to plain ports (Platform Designer friendly)
// - Ties off AXI manager / DMA and all subsystem (ss_*) straps per CaliptraIntegrationSpecification.md
// - Instantiates mailbox SRAM (256 KiB + ECC), ROM (imem), VeeR ICCM/DCCM and Adams-Bridge memories
//   as inferred RAMs (caliptra_sram / abr_mem_top) -> should infer M20K in Quartus (unverified).
// TEST KEYS ONLY: obf/hmac keys are input ports; drive from secure source for anything non-prototype.
`include "config_defines.svh"
`include "caliptra_macros.svh"

module caliptra_passive_top
  import soc_ifc_pkg::*;
#(
  parameter int AXI_AW = `CALIPTRA_SLAVE_ADDR_WIDTH(`CALIPTRA_SLAVE_SEL_SOC_IFC),
  parameter int AXI_DW = `CALIPTRA_AXI_DATA_WIDTH,
  parameter int AXI_IW = `CALIPTRA_AXI_ID_WIDTH,
  parameter int AXI_UW = `CALIPTRA_AXI_USER_WIDTH,
  parameter     ROM_INIT_FILE = ""          // $readmemh hex of caliptra-rom (64-bit words)
)(
  input  logic         clk,
  input  logic         cptra_pwrgood,
  input  logic         cptra_rst_b,

  // Keys (prototype/test values)
  input  logic [255:0]                              cptra_obf_key,
  input  logic [`CLP_CSR_HMAC_KEY_DWORDS-1:0][31:0] cptra_csr_hmac_key,
  input  logic [1:0]   security_state_device_lifecycle, // 0=UNPROVISIONED 1=MANUFACTURING 3=PRODUCTION
  input  logic         security_state_debug_locked,

  // JTAG
  input  logic jtag_tck, jtag_tms, jtag_tdi, jtag_trst_n,
  output logic jtag_tdo, jtag_tdoEn,

  // SoC AXI4 subordinate (mailbox / soc_ifc)
  input  logic [AXI_AW-1:0] s_axi_awaddr,  input logic [1:0] s_axi_awburst, input logic [2:0] s_axi_awsize,
  input  logic [7:0]        s_axi_awlen,   input logic [AXI_UW-1:0] s_axi_awuser, input logic [AXI_IW-1:0] s_axi_awid,
  input  logic              s_axi_awlock,  input logic s_axi_awvalid, output logic s_axi_awready,
  input  logic [AXI_DW-1:0] s_axi_wdata,   input logic [AXI_DW/8-1:0] s_axi_wstrb, input logic [AXI_UW-1:0] s_axi_wuser,
  input  logic              s_axi_wvalid,  output logic s_axi_wready, input logic s_axi_wlast,
  output logic [1:0]        s_axi_bresp,   output logic [AXI_IW-1:0] s_axi_bid, output logic [AXI_UW-1:0] s_axi_buser,
  output logic              s_axi_bvalid,  input logic s_axi_bready,
  input  logic [AXI_AW-1:0] s_axi_araddr,  input logic [1:0] s_axi_arburst, input logic [2:0] s_axi_arsize,
  input  logic [7:0]        s_axi_arlen,   input logic [AXI_UW-1:0] s_axi_aruser, input logic [AXI_IW-1:0] s_axi_arid,
  input  logic              s_axi_arlock,  input logic s_axi_arvalid, output logic s_axi_arready,
  output logic [AXI_DW-1:0] s_axi_rdata,   output logic [1:0] s_axi_rresp, output logic [AXI_IW-1:0] s_axi_rid,
  output logic [AXI_UW-1:0] s_axi_ruser,   output logic s_axi_rlast, output logic s_axi_rvalid, input logic s_axi_rready,

  // Status / interrupts
  output logic ready_for_fuses, ready_for_mb_processing, ready_for_runtime,
  output logic mailbox_data_avail, mailbox_flow_done,
  output logic cptra_error_fatal, cptra_error_non_fatal,
  input  logic BootFSM_BrkPoint,
  input  logic [63:0] generic_input_wires,
  output logic [63:0] generic_output_wires,

  // TRNG: external-TRNG request; internal-TRNG physical source (only if CALIPTRA_INTERNAL_TRNG)
  output logic       etrng_req,
  input  logic [3:0] itrng_data,
  input  logic       itrng_valid,

  input  logic scan_mode
);

  // ---------------- AXI interfaces ----------------
  axi_if #(.AW(AXI_AW), .DW(AXI_DW), .IW(AXI_IW), .UW(AXI_UW)) s_axi (.clk(clk), .rst_n(cptra_rst_b));
  axi_if #(.AW(`CALIPTRA_AXI_DMA_ADDR_WIDTH), .DW(CPTRA_AXI_DMA_DATA_WIDTH),
           .IW(CPTRA_AXI_DMA_ID_WIDTH), .UW(CPTRA_AXI_DMA_USER_WIDTH)) m_axi (.clk(clk), .rst_n(cptra_rst_b));

  assign s_axi.awaddr = s_axi_awaddr; assign s_axi.awburst = s_axi_awburst; assign s_axi.awsize = s_axi_awsize;
  assign s_axi.awlen = s_axi_awlen;   assign s_axi.awuser = s_axi_awuser;   assign s_axi.awid = s_axi_awid;
  assign s_axi.awlock = s_axi_awlock; assign s_axi.awvalid = s_axi_awvalid; assign s_axi_awready = s_axi.awready;
  assign s_axi.wdata = s_axi_wdata;   assign s_axi.wstrb = s_axi_wstrb;     assign s_axi.wuser = s_axi_wuser;
  assign s_axi.wvalid = s_axi_wvalid; assign s_axi_wready = s_axi.wready;   assign s_axi.wlast = s_axi_wlast;
  assign s_axi_bresp = s_axi.bresp;   assign s_axi_bid = s_axi.bid;         assign s_axi_buser = s_axi.buser;
  assign s_axi_bvalid = s_axi.bvalid; assign s_axi.bready = s_axi_bready;
  assign s_axi.araddr = s_axi_araddr; assign s_axi.arburst = s_axi_arburst; assign s_axi.arsize = s_axi_arsize;
  assign s_axi.arlen = s_axi_arlen;   assign s_axi.aruser = s_axi_aruser;   assign s_axi.arid = s_axi_arid;
  assign s_axi.arlock = s_axi_arlock; assign s_axi.arvalid = s_axi_arvalid; assign s_axi_arready = s_axi.arready;
  assign s_axi_rdata = s_axi.rdata;   assign s_axi_rresp = s_axi.rresp;     assign s_axi_rid = s_axi.rid;
  assign s_axi_ruser = s_axi.ruser;   assign s_axi_rlast = s_axi.rlast;     assign s_axi_rvalid = s_axi.rvalid;
  assign s_axi.rready = s_axi_rready;

  // Passive mode: AXI manager (DMA) must not connect to SoC. Respond "never ready" -> tie handshakes to 0.
  assign m_axi.awready = 1'b0; assign m_axi.wready = 1'b0;
  assign m_axi.bvalid = 1'b0;  assign m_axi.bresp = '0; assign m_axi.bid = '0; assign m_axi.buser = '0;
  assign m_axi.arready = 1'b0; assign m_axi.rvalid = 1'b0; assign m_axi.rdata = '0; assign m_axi.rresp = '0;
  assign m_axi.rid = '0; assign m_axi.ruser = '0; assign m_axi.rlast = 1'b0;

  // ---------------- Memory export ----------------
  el2_mem_if el2_mem_export ();
  abr_mem_if abr_memory_export ();

  logic mbox_sram_cs, mbox_sram_we;
  logic [CPTRA_MBOX_ADDR_W-1:0]         mbox_sram_addr;
  logic [CPTRA_MBOX_DATA_AND_ECC_W-1:0] mbox_sram_wdata, mbox_sram_rdata;
  logic imem_cs;
  logic [`CALIPTRA_IMEM_ADDR_WIDTH-1:0] imem_addr;
  logic [`CALIPTRA_IMEM_DATA_WIDTH-1:0] imem_rdata;

  security_state_t security_state;
  assign security_state.device_lifecycle = device_lifecycle_e'(security_state_device_lifecycle);
  assign security_state.debug_locked     = security_state_debug_locked;

  caliptra_top u_caliptra (
    .clk, .cptra_pwrgood, .cptra_rst_b,
    .cptra_obf_key, .cptra_csr_hmac_key,
    .cptra_obf_field_entropy_vld(1'b0), .cptra_obf_field_entropy('0),   // passive: tie 0
    .cptra_obf_uds_seed_vld(1'b0),      .cptra_obf_uds_seed('0),        // passive: tie 0
    .jtag_tck, .jtag_tms, .jtag_tdi, .jtag_trst_n, .jtag_tdo, .jtag_tdoEn,
    .s_axi_w_if(s_axi.w_sub), .s_axi_r_if(s_axi.r_sub),
    .m_axi_w_if(m_axi.w_mgr), .m_axi_r_if(m_axi.r_mgr),
    .el2_mem_export(el2_mem_export.veer_sram_src),
    .abr_memory_export(abr_memory_export.req),
    .mbox_sram_cs, .mbox_sram_we, .mbox_sram_addr, .mbox_sram_wdata, .mbox_sram_rdata,
    .imem_cs, .imem_addr, .imem_rdata,
    .ready_for_fuses, .ready_for_mb_processing, .ready_for_runtime,
    .mailbox_data_avail, .mailbox_flow_done,
    .recovery_data_avail(1'b0), .recovery_image_activated(1'b0),        // subsystem-only
    .BootFSM_BrkPoint,
    .cptra_error_fatal, .cptra_error_non_fatal,
    .etrng_req, .itrng_data, .itrng_valid,
    // Subsystem straps: passive mode => tie to 0 (Integration Spec, strap table)
    .strap_ss_caliptra_base_addr('0), .strap_ss_mci_base_addr('0), .strap_ss_recovery_ifc_base_addr('0),
    .strap_ss_external_staging_area_base_addr('0), .strap_ss_otp_fc_base_addr('0),
    .strap_ss_uds_seed_base_addr('0), .strap_ss_key_release_base_addr('0), .strap_ss_key_release_key_size('0),
    .strap_ss_prod_debug_unlock_auth_pk_hash_reg_bank_offset('0),
    .strap_ss_num_of_prod_debug_unlock_auth_pk_hashes('0), .strap_ss_caliptra_dma_axi_user('0),
    .strap_ss_strap_generic_0('0), .strap_ss_strap_generic_1('0), .strap_ss_strap_generic_2('0), .strap_ss_strap_generic_3('0),
    .ss_debug_intent(1'b0), .ss_ocp_lock_en(1'b0),
    .ss_dbg_manuf_enable(), .ss_soc_dbg_unlock_level(), .ss_generic_fw_exec_ctrl(),
    .generic_input_wires, .generic_output_wires,
    .trace_rv_i_insn_ip(), .trace_rv_i_address_ip(), .trace_rv_i_valid_ip(), .trace_rv_i_exception_ip(),
    .trace_rv_i_ecause_ip(), .trace_rv_i_interrupt_ip(), .trace_rv_i_tval_ip(),
    .security_state, .scan_mode
  );

  // Mailbox SRAM: 256 KiB data + ECC (passive mode size)
  caliptra_sram #(.DATA_WIDTH(CPTRA_MBOX_DATA_AND_ECC_W), .DEPTH(CPTRA_MBOX_DEPTH)) u_mbox_ram (
    .clk_i(clk), .cs_i(mbox_sram_cs), .we_i(mbox_sram_we), .addr_i(mbox_sram_addr),
    .wdata_i(mbox_sram_wdata), .rdata_o(mbox_sram_rdata));

  // ROM (imem), 96 KiB, read-only; preload with caliptra-rom image
  caliptra_rom_m20k #(.DEPTH(`CALIPTRA_IMEM_DEPTH), .DW(`CALIPTRA_IMEM_DATA_WIDTH),
                      .AW(`CALIPTRA_IMEM_ADDR_WIDTH), .INIT_FILE(ROM_INIT_FILE)) u_rom (
    .clk(clk), .cs(imem_cs), .addr(imem_addr), .rdata(imem_rdata));

  // VeeR ICCM/DCCM and Adams-Bridge (ML-DSA/ML-KEM) memories
  caliptra_veer_sram_export u_veer_sram (.el2_mem_export(el2_mem_export.veer_sram_sink));
  abr_mem_top u_abr_mem (.clk_i(clk), .abr_memory_export(abr_memory_export.resp));

endmodule

module caliptra_rom_m20k #(parameter int DEPTH=12288, DW=64, AW=14, parameter INIT_FILE="") (
  input logic clk, input logic cs, input logic [AW-1:0] addr, output logic [DW-1:0] rdata);
  logic [DW-1:0] mem [DEPTH];
  initial if (INIT_FILE != "") $readmemh(INIT_FILE, mem);
  always_ff @(posedge clk) if (cs) rdata <= mem[addr];
endmodule

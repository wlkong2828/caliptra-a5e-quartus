// tb_nios2x_top_fw.sv - simulates the REAL rtl_2x/nios_caliptra2x_top.sv (window decode, soc_fw_store,
// soc_fuse_ctrl2x, avmm_to_axi, 2FF reset syncs, caliptra_passive_top + Caliptra 2.x v2.1.2 RTL +
// rom-2.1.3-1 ROM + fw-2.1.4 FMC/RT bundle) with a behavioral stand-in for the Platform Designer
// system (nios_caliptra2x_sys) that issues the same Avalon accesses as the Nios host firmware
// (1.x sw/app/main.c flow, ported to the 2.x register names). TEST KEYS / ENTROPY ONLY.
// Plusargs: +test=axiuser|prod|all (default all = axiuser checks + prod cold boot)
//           +max_cycles=N (default 300_000_000)   +hb=N heartbeat period (default 1_000_000)
`timescale 1ns/1ps
module nios_caliptra2x_sys (
  input  logic clk_clk, reset_reset_n,
  output logic [19:0] caliptra_axi_address, output logic caliptra_axi_read, caliptra_axi_write,
  output logic [31:0] caliptra_axi_writedata, output logic [3:0] caliptra_axi_byteenable,
  input  logic [31:0] caliptra_axi_readdata, input logic caliptra_axi_readdatavalid, caliptra_axi_waitrequest,
  output logic [0:0] caliptra_axi_burstcount, output logic caliptra_axi_debugaccess,
  output logic [31:0] ctrl_pio_export, input logic [31:0] status_pio_export, output logic [31:0] magic_pio_export);
  wire clk = clk_clk;
  initial begin caliptra_axi_read=0; caliptra_axi_write=0; caliptra_axi_byteenable=4'hf;
    ctrl_pio_export=0; magic_pio_export=0; end
  // Nios address map (20-bit window)
  localparam logic [19:0] FUSEC = 20'h7F000, CPTRA = 20'h80000;
  localparam logic [19:0] MBOX_LOCK = CPTRA+20'h20000, MBOX_USER = CPTRA+20'h20004, MBOX_CMD = CPTRA+20'h20008,
    MBOX_DLEN = CPTRA+20'h2000c, MBOX_DATAIN = CPTRA+20'h20010, MBOX_EXECUTE = CPTRA+20'h20018, MBOX_STATUS = CPTRA+20'h2001c;
  localparam logic [19:0] SOC = CPTRA+20'h30000;
  localparam logic [19:0] HW_ERR_FATAL = SOC+20'h000, HW_ERR_NF = SOC+20'h004, FW_ERR_FATAL = SOC+20'h008, FW_ERR_NF = SOC+20'h00c,
    BOOT_STATUS = SOC+20'h038, FLOW_STATUS = SOC+20'h03c, SEC_STATE = SOC+20'h044,
    MBOX_VALID_USER0 = SOC+20'h048, MBOX_USER_LOCK0 = SOC+20'h05c, TRNG_VALID_USER = SOC+20'h070, TRNG_USER_LOCK = SOC+20'h074,
    TRNG_DATA0 = SOC+20'h078, TRNG_STATUS = SOC+20'h0ac, FUSE_WR_DONE = SOC+20'h0b0, TIMER_CONFIG = SOC+20'h0b4,
    HW_REV_ID = SOC+20'h0d4, HW_CONFIG = SOC+20'h0e0, FUSE_VALID_USER = SOC+20'h108, FUSE_USER_LOCK = SOC+20'h10c,
    WDT_CFG0 = SOC+20'h110, WDT_CFG1 = SOC+20'h114, OWNER_PK_HASH0 = SOC+20'h140, OWNER_PK_HASH_LOCK = SOC+20'h170,
    FUSE_UDS0 = SOC+20'h200, FUSE_PQC_KEY_TYPE = SOC+20'h38c;
  localparam int NIOS_USER = 1, FUSE_USER = 2;

  bit busy=0; bit allow_fatal=0; string testname = "all";
  longint cyc=0; always @(posedge clk) cyc++;
  // Avalon host: drive/sample at negedge; accepted on first posedge with waitrequest low.
  task automatic wr(input [19:0] a, input [31:0] d);
    while (busy) @(negedge clk); busy=1;
    @(negedge clk); caliptra_axi_address=a; caliptra_axi_writedata=d; caliptra_axi_write=1;
    #1; while (caliptra_axi_waitrequest) @(negedge clk) ;
    @(negedge clk); caliptra_axi_write=0; busy=0;
  endtask
  task automatic rd(input [19:0] a, output [31:0] d);
    while (busy) @(negedge clk); busy=1;
    @(negedge clk); caliptra_axi_address=a; caliptra_axi_read=1;
    #1; while (caliptra_axi_waitrequest) @(negedge clk) ;
    @(negedge clk); caliptra_axi_read=0;
    while (!caliptra_axi_readdatavalid) @(negedge clk);
    d = caliptra_axi_readdata; busy=0;
  endtask
  function automatic logic last_slverr(); return tb_nios2x_top_fw.dut.u_bridge.err_q; endfunction

  // ETRNG service - identical to 1.x trng_service(): on etrng_req write 12 x CPTRA_TRNG_DATA then
  // CPTRA_TRNG_STATUS.DATA_WR_DONE (=2), from the Nios user (TRNG_VALID_AXI_USER).
  int trng_reqs=0; longint first_trng=-1;
  task automatic trng_svc();
    if (status_pio_export[7]) begin
      for (int i=0;i<12;i++) wr(TRNG_DATA0+4*i, $urandom);
      wr(TRNG_STATUS, 2); trng_reqs++; if (first_trng<0) first_trng=cyc;
      $display("[%0d] TRNG request %0d serviced", cyc, trng_reqs);
      begin : trng_wait
        int tw;
        for (tw=0; tw<100000 && status_pio_export[7]; tw++) @(posedge clk);
        if (status_pio_export[7]) begin
          $display("TB_NIOS2X FAIL etrng_req stuck after TRNG %0d (AXI user / DATA_WR_DONE?)", trng_reqs); $finish;
        end
      end
    end
  endtask
  task automatic dump();
    logic [31:0] d;
    rd(BOOT_STATUS, d);  $display("  CPTRA_BOOT_STATUS        = %h", d);
    rd(FLOW_STATUS, d);  $display("  CPTRA_FLOW_STATUS        = %h", d);
    rd(HW_ERR_FATAL, d); $display("  CPTRA_HW_ERROR_FATAL     = %h", d);
    rd(FW_ERR_FATAL, d); $display("  CPTRA_FW_ERROR_FATAL     = %h", d);
    rd(HW_ERR_NF, d);    $display("  CPTRA_HW_ERROR_NON_FATAL = %h", d);
    rd(FW_ERR_NF, d);    $display("  CPTRA_FW_ERROR_NON_FATAL = %h", d);
  endtask
  task automatic handle_non_fatal();
    logic [31:0] hw, fw;
    if (status_pio_export[6]) begin
      rd(HW_ERR_NF, hw); rd(FW_ERR_NF, fw);
      $display("[%0d] non_fatal HW=%h FW=%h (RW1C clear)", cyc, hw, fw);
      wr(HW_ERR_NF, hw); wr(FW_ERR_NF, fw);
    end
  endtask
  task automatic check_fatal();
    if (status_pio_export[5] && !allow_fatal) begin
      $display("TB_NIOS2X FAIL unexpected cptra_error_fatal at %0d", cyc); dump(); $finish;
    end
  endtask
  task automatic wait_st(input int b);
    while (!status_pio_export[b]) begin check_fatal(); handle_non_fatal(); trng_svc(); @(posedge clk); end
  endtask

  task automatic cold_release();
    ctrl_pio_export = 1; repeat (20) @(posedge clk);   // pwrgood
    ctrl_pio_export = 3; repeat (8) @(posedge clk);    // rst_b
  endtask
  // Same ordering as 1.x program_pauser_timer_wdt(), registers renamed *_AXI_USER*; fuse user = 2.
  task automatic program_axi_user_timer_wdt();
    wr(FUSE_VALID_USER, FUSE_USER); wr(FUSE_USER_LOCK, 1); // fuse ctrl IP user + lock (pwrgood-sticky)
    wr(TRNG_VALID_USER, NIOS_USER); wr(TRNG_USER_LOCK, 1); // Nios services ETRNG
    wr(MBOX_VALID_USER0, NIOS_USER); wr(MBOX_USER_LOCK0, 1); // Nios is mailbox user 0
    wr(TIMER_CONFIG, 32'd20000);                           // 20000 ps @ 50 MHz
    wr(WDT_CFG0, 32'd100_000_000); wr(WDT_CFG1, 0);         // debug-locked ROM arms WDT1
  endtask
  longint m_rff=-1, m_fuse=-1, m_rmb=-1, m_fwld=-1, m_mbox=-1, m_rrt=-1;
  int fuse_count=0;
  task automatic start_fuses();
    logic [31:0] d, n;
    rd(FUSEC+0, d); $display("[%0d] FUSE_CTRL ID=%h", cyc, d);
    if (d!=32'h46555345) begin $display("TB_NIOS2X FAIL fuse id"); $finish; end
    rd(FUSEC+20'h14, n); $display("[%0d] FUSE_CTRL NUM_FUSES=%0d (image entries)", cyc, n);
    wr(FUSEC+4, 32'h1);                                    // START
    do rd(FUSEC+8, d); while (d[0] || !(d[1]|d[2]));
    rd(FUSEC+20'h0c, n); fuse_count = n; m_fuse = cyc;
    $display("[%0d] FUSE_CTRL STATUS=%h COUNT=%0d", cyc, d, n);
    if (d[2]) begin $display("TB_NIOS2X FAIL fuse ctrl ERR (SLVERR on a fuse write?)"); dump(); $finish; end
    if (n != 118) begin $display("TB_NIOS2X FAIL expected COUNT=118 (104 fuse + 13 owner hash/lock + WR_DONE)"); $finish; end
    rd(FUSE_WR_DONE, d); $display("[%0d] FUSE_WR_DONE=%h", cyc, d);
    if (!d[0]) begin $display("TB_NIOS2X FAIL FUSE_WR_DONE not set"); $finish; end
    rd(FUSE_PQC_KEY_TYPE, d); $display("  FUSE_PQC_KEY_TYPE readback=%h", d);
    rd(OWNER_PK_HASH_LOCK, d); $display("  CPTRA_OWNER_PK_HASH_LOCK readback=%h", d);
    if (!d[0]) begin $display("TB_NIOS2X FAIL owner PK hash not locked"); $finish; end
    rd(OWNER_PK_HASH0, d); $display("  CPTRA_OWNER_PK_HASH[0] readback=%h", d);
  endtask
  task automatic load_fw_to_runtime();
    logic [31:0] d, n; int words;
    wait_st(1); m_rmb = cyc; magic_pio_export = 5;
    $display("[%0d] MILESTONE ready_for_mb_processing trng=%0d", cyc, trng_reqs);
    rd(FUSEC+20'h10, n);
    do begin trng_svc(); rd(MBOX_LOCK, d); end while (d[0]);
    rd(MBOX_USER, d); $display("  MBOX_USER=%h", d);
    if (d != NIOS_USER) begin $display("TB_NIOS2X FAIL MBOX_USER"); $finish; end
    wr(MBOX_CMD, 32'h46574C44); wr(MBOX_DLEN, n);
    words = (n+3)/4;
    for (int i=0;i<words;i++) begin rd(4*i, d); wr(MBOX_DATAIN, d); if ((i&255)==0) trng_svc(); end
    wr(MBOX_EXECUTE, 1); magic_pio_export = 6; m_fwld = cyc;
    $display("[%0d] MILESTONE FIRMWARE_LOAD issued, %0d bytes from soc_fw_store", cyc, n);
    do begin repeat (1000) @(posedge clk); check_fatal(); trng_svc(); rd(MBOX_STATUS, d); end while (d[3:0]==0);
    m_mbox = cyc; $display("[%0d] MILESTONE MBOX_STATUS=%0d (2=CMD_COMPLETE)", cyc, d[3:0]); wr(MBOX_EXECUTE, 0);
    if (d[3:0]!=2) begin $display("TB_NIOS2X FAIL mbox status"); dump(); $finish; end
    magic_pio_export = 7;
    wait_st(2); m_rrt = cyc; $display("[%0d] MILESTONE ready_for_runtime", cyc);
  endtask

  // AXI-user lock checks (2.x version of the 1.x pauser test)
  task automatic test_axiuser();
    logic [31:0] d;
    $display("[%0d] === test_axiuser: wrong-user accesses rejected ===", cyc);
    force tb_nios2x_top_fw.dut.nios_axi_user = 32'h3;
    wr(MBOX_LOCK, 32'h0);
    if (!last_slverr()) begin $display("TB_AXIUSER FAIL expected SLVERR on MBOX write with AxUSER=3"); $finish; end
    $display("[%0d] MBOX write AxUSER=3 -> SLVERR OK", cyc);
    wr(FUSE_UDS0, 32'hdeadbeef);
    if (!last_slverr()) begin $display("TB_AXIUSER FAIL expected SLVERR on fuse write with AxUSER=3"); $finish; end
    $display("[%0d] fuse write AxUSER=3 -> SLVERR OK", cyc);
    force tb_nios2x_top_fw.dut.nios_axi_user = NIOS_USER;
    wr(FUSE_UDS0, 32'hdeadbeef);   // Nios (user 1) is NOT the fuse user (2) -> must be rejected too
    if (!last_slverr()) begin $display("TB_AXIUSER FAIL expected SLVERR on fuse write from Nios AxUSER=1"); $finish; end
    $display("[%0d] fuse write AxUSER=1 (Nios) -> SLVERR OK (fuses only from fuse ctrl user 2)", cyc);
    rd(HW_REV_ID, d);
    if (last_slverr()) begin $display("TB_AXIUSER FAIL unexpected SLVERR on HW_REV_ID with AxUSER=1"); $finish; end
    release tb_nios2x_top_fw.dut.nios_axi_user;
    $display("[%0d] AxUSER=1 HW_REV_ID=%h accepted OK", cyc, d);
    $display("TB_AXIUSER PASS");
  endtask

  initial begin
    logic [31:0] d; longint maxc = 300_000_000, hb = 1_000_000;
    void'($value$plusargs("max_cycles=%d", maxc)); void'($value$plusargs("hb=%d", hb));
    void'($value$plusargs("test=%s", testname));
    $display("TB_NIOS2X test=%s max_cycles=%0d", testname, maxc);
    fork begin wait (cyc>=maxc); $display("TB_NIOS2X TIMEOUT magic=%h trng=%0d", magic_pio_export, trng_reqs); $finish; end join_none
    fork forever begin repeat (hb) @(posedge clk);
      $display("[%0d] heartbeat status=%h trng=%0d", cyc, status_pio_export[7:0], trng_reqs); end join_none
    wait (reset_reset_n); repeat (5) @(posedge clk);
    magic_pio_export = 1;
    cold_release();
    wait_st(0); m_rff = cyc; magic_pio_export = 2;
    $display("[%0d] MILESTONE ready_for_fuses", cyc);
    rd(HW_REV_ID, d); $display("[%0d] HW_REV_ID=%h", cyc, d);
    rd(HW_CONFIG, d); $display("[%0d] HW_CONFIG=%h (iTRNG_en=%0d SUBSYSTEM_MODE_en=%0d)", cyc, d, d[0], d[2]);
    rd(SEC_STATE, d); $display("[%0d] CPTRA_SECURITY_STATE=%h (lifecycle=%0d debug_locked=%0d)", cyc, d, d[1:0], d[2]);
    if (tb_nios2x_top_fw.dut.generic_input_wires !== 64'b0) begin $display("TB_NIOS2X FAIL generic_input_wires"); $finish; end
    program_axi_user_timer_wdt(); magic_pio_export = 3;
    if (testname=="axiuser" || testname=="all") begin
      test_axiuser();
      if (testname=="axiuser") $finish;
    end
    start_fuses(); magic_pio_export = 4;
    $display("[%0d] MILESTONE fuses done via soc_fuse_ctrl2x (COUNT=%0d)", cyc, fuse_count);
    load_fw_to_runtime();
    magic_pio_export = 32'hCA11F00D;
    repeat (20000) begin check_fatal(); handle_non_fatal(); trng_svc(); @(posedge clk); end
    dump();
    $display("SUMMARY ready_for_fuses=%0d fuses_done=%0d first_trng=%0d ready_for_mb_processing=%0d fw_load_issued=%0d mbox_complete=%0d rom_to_fmc=%0d fmc_to_rt=%0d ready_for_runtime=%0d trng_fills=%0d fuse_writes=%0d",
      m_rff, m_fuse, first_trng, m_rmb, m_fwld, m_mbox, tb_nios2x_top_fw.m_fmc, tb_nios2x_top_fw.m_rt, m_rrt, trng_reqs, fuse_count);
    $display("TB_NIOS2X PASS cyc=%0d trng=%0d (prod, debug locked)", cyc, trng_reqs);
    $finish;
  end
endmodule

module tb_nios2x_top_fw;
  logic clk=0, rst_n=0; always #5 clk=~clk;
  initial begin repeat (5) @(posedge clk); rst_n=1; end
  logic [7:0] led;
  nios_caliptra2x_top dut (.clk, .reset_n(rst_n), .led);
  longint cyc=0; always @(posedge clk) cyc++;
  always @(posedge dut.etrng_req) $display("[%0d] etrng_req rise", cyc);
  // Caliptra ROM/FMC/RT log on generic_output_wires[7:0] (bit8 toggles per char); printed per line
  // with the cycle number; first FMC / RT lines recorded as milestones.
  longint m_fmc=-1, m_rt=-1;
  function automatic bit has(string s, string sub);
    if (sub.len() > s.len()) return 0;
    for (int i=0; i<=s.len()-sub.len(); i++) if (s.substr(i, i+sub.len()-1) == sub) return 1;
    return 0;
  endfunction
  string line = "";
  logic [8:0] prev_o; bit prev_v=0;
  always @(posedge clk) if (dut.cptra_rst_b) begin
    if (!prev_v) begin prev_o <= dut.generic_output_wires[8:0]; prev_v <= 1; end
    else if (dut.generic_output_wires[8:0] != prev_o) begin
      prev_o <= dut.generic_output_wires[8:0];
      if (dut.generic_output_wires[7:0] == 8'h0a) begin
        $display("[%0d] LOG %s", cyc, line);
        if (m_fmc < 0 && (has(line, "[fmc") || has(line, "[alias rt"))) begin m_fmc = cyc; $display("[%0d] MILESTONE first FMC log line (ROM -> FMC handoff)", cyc); end
        if (m_rt < 0 && has(line, "[rt]")) begin m_rt = cyc; $display("[%0d] MILESTONE first RT log line (FMC -> RT handoff)", cyc); end
        line = "";
      end else if (dut.generic_output_wires[7:0] != 8'h0d) line = {line, string'(dut.generic_output_wires[7:0])};
    end
  end
endmodule

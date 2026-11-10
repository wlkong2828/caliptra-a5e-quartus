// tb_nios_top_fw.sv - simulates the REAL quartus_a5e_nios/rtl/nios_caliptra_top.sv (window decode,
// soc_fw_store, soc_fuse_ctrl, avmm_to_apb, 2FF reset sync, caliptra_passive_top + 1.x ROM)
// with a behavioral stand-in for the Platform Designer system (nios_caliptra_sys) that executes
// the same sequence as sw/app/main.c over the Avalon window. TEST KEYS/ENTROPY ONLY.
//
// Plusargs:
//   +test=prod     production cold boot through ready_for_runtime / FIRMWARE_LOAD (existing)
//   +test=sync     2FF reset-synchronizer behavior only
//   +test=pauser   lock PAUSER, write from wrong user, expect PSLVERR
//   +test=warm     prod, then warm reset (rst_b only) + START_DONE, back to ready_for_runtime
//   +test=fatal    prod (or boot to fuses if +fatal_early), then force fatal + pwrgood recovery
//   +test=all      sync + pauser + prod + warm + fatal recovery (default)
//   +max_cycles=N  timeout (default 200_000_000, enough for two full ROM+FW boots)
`timescale 1ns/1ps
module nios_caliptra_sys (
  input  logic clk_clk, reset_reset_n,
  output logic [17:0] caliptra_apb_address, output logic caliptra_apb_read, caliptra_apb_write,
  output logic [31:0] caliptra_apb_writedata, output logic [3:0] caliptra_apb_byteenable,
  input  logic [31:0] caliptra_apb_readdata, input logic caliptra_apb_readdatavalid, caliptra_apb_waitrequest,
  output logic [0:0] caliptra_apb_burstcount, output logic caliptra_apb_debugaccess,
  output logic [31:0] ctrl_pio_export, input logic [31:0] status_pio_export, output logic [31:0] magic_pio_export);
  wire clk = clk_clk;
  initial begin caliptra_apb_read=0; caliptra_apb_write=0; caliptra_apb_byteenable=4'hf;
    ctrl_pio_export=0; magic_pio_export=0; end
  bit busy=0;
  bit allow_fatal=0;
  string testname = "all";
  // Avalon host: drive/sample at negedge (no race with posedge NBA updates); a request is
  // accepted on the first posedge where waitrequest is low, like the Nios mm interconnect.
  task automatic wr(input [17:0] a, input [31:0] d);
    while (busy) @(negedge clk); busy=1;
    @(negedge clk); caliptra_apb_address=a; caliptra_apb_writedata=d; caliptra_apb_write=1;
    #1; while (caliptra_apb_waitrequest) @(negedge clk) ;
    @(negedge clk); caliptra_apb_write=0; busy=0;
  endtask
  task automatic rd(input [17:0] a, output [31:0] d);
    while (busy) @(negedge clk); busy=1;
    @(negedge clk); caliptra_apb_address=a; caliptra_apb_read=1;
    #1; while (caliptra_apb_waitrequest) @(negedge clk) ;
    @(negedge clk); caliptra_apb_read=0;
    while (!caliptra_apb_readdatavalid) @(negedge clk);
    d = caliptra_apb_readdata; busy=0;
  endtask
  function automatic logic last_pslverr();
    return tb_nios_top_fw.dut.u_bridge.err_q;
  endfunction
  // TRNG service, called from the polling loops exactly like trng_service() in main.c
  int trng_reqs=0;
  task automatic trng_svc();
    if (status_pio_export[7]) begin
      for (int i=0;i<12;i++) wr(18'h30078+4*i, $urandom);
      wr(18'h300ac, 2); trng_reqs++; $display("[%0d] TRNG request %0d serviced", cyc, trng_reqs);
      begin : trng_wait
        int tw;
        for (tw=0; tw<100000 && status_pio_export[7]; tw++) @(posedge clk);
        if (status_pio_export[7]) begin
          $display("TB_NIOS_TOP FAIL etrng_req stuck after TRNG %0d (PAUSER/DATA_WR_DONE?)", trng_reqs);
          $finish;
        end
      end
    end
  endtask
  task automatic handle_non_fatal();
    logic [31:0] hw, fw;
    if (status_pio_export[6]) begin
      rd(18'h30004, hw); rd(18'h3000c, fw);
      $display("[%0d] non_fatal HW=%h FW=%h (RW1C clear)", cyc, hw, fw);
      wr(18'h30004, hw); wr(18'h3000c, fw);
    end
  endtask
  task automatic wait_st(input int b);
    while (!status_pio_export[b]) begin
      if (status_pio_export[5] && !allow_fatal) begin
        logic [31:0] d, n;
        rd(18'h30000, d); rd(18'h30008, n);
        $display("TB_NIOS_TOP FAIL unexpected fatal at %0d HW_ERR_FATAL=%h FW_ERR_FATAL=%h", cyc, d, n);
        $finish;
      end
      handle_non_fatal();
      trng_svc();
      @(posedge clk);
    end
  endtask
  longint cyc=0; always @(posedge clk) cyc++;

  // ---- helpers matching main.c ----
  task automatic cold_release();
    ctrl_pio_export = 1; repeat (20) @(posedge clk);
    ctrl_pio_export = 3; repeat (8) @(posedge clk);
  endtask
  task automatic program_pauser_timer_wdt(input bit include_fuse);
    if (include_fuse) begin
      wr(18'h30108, 1); wr(18'h3010c, 1); // FUSE_VALID_PAUSER + LOCK (pwrgood-sticky)
    end
    wr(18'h30070, 1); wr(18'h30074, 1);   // TRNG_VALID_PAUSER + LOCK (rst_b domain)
    wr(18'h30048, 1); wr(18'h3005c, 1);   // MBOX_VALID_PAUSER0 + LOCK0 (rst_b domain)
    wr(18'h300b4, 32'd20000);             // TIMER_CONFIG = 20000 ps @ 50 MHz
    wr(18'h30110, 32'd100_000_000); wr(18'h30114, 0); // WDT_CFG
  endtask
  task automatic start_fuses(input bit done_only);
    logic [31:0] d, n;
    rd(18'h1f000, d); $display("[%0d] FUSE_CTRL ID=%h", cyc, d);
    if (d!=32'h46555345) begin $display("TB_NIOS_TOP FAIL fuse id"); $finish; end
    wr(18'h1f004, done_only ? 32'h4 : 32'h1); // START_DONE or START
    do rd(18'h1f008, d); while (d[0] || !(d[1]|d[2]));
    rd(18'h1f00c, n); $display("[%0d] FUSE_CTRL STATUS=%h COUNT=%0d (done_only=%0d)", cyc, d, n, done_only);
    if (d[2]) begin $display("TB_NIOS_TOP FAIL fuse err"); $finish; end
    if (done_only && n!=1) begin $display("TB_NIOS_TOP FAIL expected COUNT=1 on START_DONE"); $finish; end
    if (!done_only && n!=84) begin $display("TB_NIOS_TOP FAIL expected COUNT=84 on full START"); $finish; end
    rd(18'h300b0, d); $display("[%0d] FUSE_WR_DONE=%h", cyc, d);
    if (!d[0]) begin $display("TB_NIOS_TOP FAIL FUSE_WR_DONE not set"); $finish; end
  endtask
  task automatic load_fw_to_runtime();
    logic [31:0] d, n; int words;
    wait_st(1); magic_pio_export = 5; $display("[%0d] ready_for_fw_push trng=%0d", cyc, trng_reqs);
    rd(18'h1f010, n);
    do begin trng_svc(); rd(18'h20000, d); end while (d[0]);
    rd(18'h20004, d); $display("  MBOX_USER=%h", d);
    if (d != 32'h1) begin $display("TB_NIOS_TOP FAIL MBOX_USER"); $finish; end
    wr(18'h20008, 32'h46574C44); wr(18'h2000c, n);
    words = (n+3)/4;
    for (int i=0;i<words;i++) begin rd(4*i, d); wr(18'h20010, d); if ((i&255)==0) trng_svc(); end
    wr(18'h20018, 1); magic_pio_export = 6; $display("[%0d] FIRMWARE_LOAD %0d bytes from soc_fw_store", cyc, n);
    do begin repeat (1000) @(posedge clk); trng_svc(); rd(18'h2001c, d); end while (d[3:0]==0);
    $display("[%0d] MBOX_STATUS=%0d", cyc, d[3:0]); wr(18'h20018, 0);
    if (d[3:0]!=2) begin $display("TB_NIOS_TOP FAIL mbox"); $finish; end
    magic_pio_export = 7;
    wait_st(2); $display("[%0d] ready_for_runtime", cyc);
  endtask

  // 2FF: pwrgood async assert / sync deassert; rst_b async assert / sync deassert
  task automatic test_sync();
    int rise_pg, fall_pg, rise_rb, fall_rb;
    $display("[%0d] === test_sync: 2FF reset synchronizers ===", cyc);
    // start from known idle (both requests 0) after reset_n is already 1
    ctrl_pio_export = 0;
    repeat (8) @(posedge clk);
    if (tb_nios_top_fw.dut.cptra_pwrgood !== 1'b0 || tb_nios_top_fw.dut.cptra_rst_b !== 1'b0) begin
      $display("TB_SYNC FAIL idle pins not 0 pwrgood=%b rst_b=%b", tb_nios_top_fw.dut.cptra_pwrgood, tb_nios_top_fw.dut.cptra_rst_b);
      $finish;
    end
    // pwrgood async assert: set ctrl[0] just after a posedge; output may rise immediately
    @(negedge clk);
    ctrl_pio_export = 1;
    #1;
    if (tb_nios_top_fw.dut.cptra_pwrgood !== 1'b1) begin
      $display("TB_SYNC FAIL pwrgood did not assert asynchronously (got %b)", tb_nios_top_fw.dut.cptra_pwrgood);
      $finish;
    end
    $display("[%0d] pwrgood async assert OK", cyc);
    // pwrgood sync deassert: drop request; must stay 1 through the next posedge, 0 after 2 clocks
    @(negedge clk);
    ctrl_pio_export = 0;
    #1;
    if (tb_nios_top_fw.dut.cptra_pwrgood !== 1'b1) begin
      $display("TB_SYNC FAIL pwrgood dropped asynchronously (must be sync deassert)");
      $finish;
    end
    fall_pg = 0;
    for (int i=1; i<=8; i++) begin
      @(posedge clk); #1;
      if (tb_nios_top_fw.dut.cptra_pwrgood === 1'b0) begin fall_pg = i; break; end
    end
    if (fall_pg < 2 || fall_pg > 3) begin
      $display("TB_SYNC FAIL pwrgood sync deassert after %0d clocks (expect 2 or 3)", fall_pg);
      $finish;
    end
    $display("[%0d] pwrgood sync deassert after %0d clocks OK", cyc, fall_pg);
    // rst_b sync deassert: raise ctrl[1] with pwrgood; rst_b stays 0 then rises after 2 clocks
    @(negedge clk);
    ctrl_pio_export = 1; // pwrgood first
    #1;
    @(negedge clk);
    ctrl_pio_export = 3;
    #1;
    if (tb_nios_top_fw.dut.cptra_rst_b !== 1'b0) begin
      $display("TB_SYNC FAIL rst_b rose asynchronously (must be sync deassert)");
      $finish;
    end
    rise_rb = 0;
    for (int i=1; i<=8; i++) begin
      @(posedge clk); #1;
      if (tb_nios_top_fw.dut.cptra_rst_b === 1'b1) begin rise_rb = i; break; end
    end
    if (rise_rb < 2 || rise_rb > 3) begin
      $display("TB_SYNC FAIL rst_b sync deassert after %0d clocks (expect 2 or 3)", rise_rb);
      $finish;
    end
    $display("[%0d] rst_b sync deassert after %0d clocks OK", cyc, rise_rb);
    // rst_b async assert
    @(negedge clk);
    ctrl_pio_export = 1; // drop rst_b request, hold pwrgood
    #1;
    if (tb_nios_top_fw.dut.cptra_rst_b !== 1'b0) begin
      $display("TB_SYNC FAIL rst_b did not assert asynchronously (got %b)", tb_nios_top_fw.dut.cptra_rst_b);
      $finish;
    end
    $display("[%0d] rst_b async assert OK", cyc);
    // leave Caliptra in reset for the subsequent boot (ctrl=0 after pwrgood sync fall)
    @(negedge clk); ctrl_pio_export = 0;
    repeat (6) @(posedge clk);
    $display("TB_SYNC PASS");
  endtask

  task automatic test_pauser();
    logic [31:0] d;
    $display("[%0d] === test_pauser: wrong-user write rejected ===", cyc);
    // MBOX access with PAUSER=2 must PSLVERR (default valid user is only 0xFFFFFFFF until we lock 1)
    force tb_nios_top_fw.dut.nios_pauser = 32'h2;
    wr(18'h20000, 32'h0); // MBOX_LOCK
    if (!last_pslverr()) begin
      $display("TB_PAUSER FAIL expected PSLVERR on MBOX write with PAUSER=2");
      $finish;
    end
    $display("[%0d] MBOX write PAUSER=2 -> PSLVERR OK", cyc);
    // Fuse-range write with PAUSER=2 must also PSLVERR once FUSE_PAUSER is locked
    wr(18'h30200, 32'hdeadbeef); // FUSE_UDS_SEED_0
    if (!last_pslverr()) begin
      $display("TB_PAUSER FAIL expected PSLVERR on fuse write with PAUSER=2");
      $finish;
    end
    $display("[%0d] fuse write PAUSER=2 -> PSLVERR OK", cyc);
    force tb_nios_top_fw.dut.nios_pauser = 32'h1;
    // Confirm the intended user is accepted (read HW_REV_ID; no PSLVERR)
    rd(18'h300d4, d);
    if (last_pslverr()) begin
      $display("TB_PAUSER FAIL unexpected PSLVERR on HW_REV_ID with PAUSER=1");
      $finish;
    end
    $display("[%0d] PAUSER=1 HW_REV_ID=%h accepted OK", cyc, d);
    $display("TB_PAUSER PASS");
  endtask

  task automatic do_prod_from_reset();
    logic [31:0] d;
    magic_pio_export = 1;
    cold_release();
    wait_st(0); magic_pio_export = 2;
    rd(18'h300d4, d); $display("[%0d] HW_REV_ID=%h", cyc, d);
    if (tb_nios_top_fw.dut.generic_input_wires !== 64'b0) begin
      $display("TB_NIOS_TOP FAIL generic_input_wires=%h (must be 0; bit0=zeroization tie-off)", tb_nios_top_fw.dut.generic_input_wires);
      $finish;
    end
    program_pauser_timer_wdt(1);
    magic_pio_export = 3;
  endtask

  initial begin
    logic [31:0] d, n; longint maxc = 200_000_000;
    void'($value$plusargs("max_cycles=%d", maxc));
    void'($value$plusargs("test=%s", testname));
    $display("TB_NIOS_TOP test=%s max_cycles=%0d", testname, maxc);
    fork begin wait (cyc>=maxc); $display("TB_NIOS_TOP TIMEOUT magic=%h trng=%0d test=%s", magic_pio_export, trng_reqs, testname); $finish; end join_none
    wait (reset_reset_n); repeat (5) @(posedge clk);

    if (testname=="sync" || testname=="all") begin
      test_sync();
      if (testname=="sync") begin $display("TB_NIOS_TOP PASS test=sync"); $finish; end
    end

    do_prod_from_reset();

    if (testname=="pauser" || testname=="all") begin
      test_pauser();
      if (testname=="pauser") begin $display("TB_NIOS_TOP PASS test=pauser"); $finish; end
    end

    start_fuses(0);
    magic_pio_export = 4;
    load_fw_to_runtime();
    magic_pio_export = 32'hCA11F00D;
    $display("TB_NIOS_TOP PASS cyc=%0d trng=%0d (prod)", cyc, trng_reqs);
    if (testname=="prod") $finish;

    if (testname=="warm" || testname=="all") begin
      $display("[%0d] === test_warm: rst_b only, START_DONE ===", cyc);
      // hold pwrgood, pulse rst_b
      ctrl_pio_export = 1;
      repeat (20) @(posedge clk);
      if (tb_nios_top_fw.dut.cptra_pwrgood !== 1'b1) begin
        $display("TB_WARM FAIL pwrgood dropped"); $finish;
      end
      if (tb_nios_top_fw.dut.cptra_rst_b !== 1'b0) begin
        $display("TB_WARM FAIL rst_b did not assert"); $finish;
      end
      ctrl_pio_export = 3;
      repeat (8) @(posedge clk);
      wait_st(0);
      $display("[%0d] warm ready_for_fuses", cyc);
      // fuses must still be programmed (pwrgood sticky); only rewrite DONE
      rd(18'h300b0, d);
      $display("[%0d] FUSE_WR_DONE still %h after warm (persists until rewritten)", cyc, d);
      program_pauser_timer_wdt(0); // re-lock TRNG+mailbox (rst_b domain); skip fuse
      magic_pio_export = 32'h13;
      wr(18'h1f004, 2); // CLEAR
      start_fuses(1);
      magic_pio_export = 32'h14;
      // rom-1.1.1 WarmResetFlow jumps to existing FW after a successful cold boot;
      // ready_for_fw_push / FIRMWARE_LOAD are not part of that path. If fw_push
      // does assert (previous cold boot incomplete), load the bundle as usual.
      $display("[%0d] waiting for ready_for_runtime after warm START_DONE", cyc);
      while (!status_pio_export[2]) begin
        if (status_pio_export[1]) begin
          $display("[%0d] ready_for_fw_push after warm (unexpected if prev cold completed); loading FW", cyc);
          load_fw_to_runtime();
          break;
        end
        if (status_pio_export[5] && !allow_fatal) begin
          $display("TB_WARM FAIL unexpected fatal at %0d", cyc); $finish;
        end
        handle_non_fatal();
        trng_svc();
        @(posedge clk);
      end
      if (!status_pio_export[2]) wait_st(2);
      $display("[%0d] ready_for_runtime after warm reset", cyc);
      magic_pio_export = 32'hCA11F00D;
      $display("TB_WARM PASS cyc=%0d trng=%0d", cyc, trng_reqs);
      if (testname=="warm") $finish;
    end

    if (testname=="fatal" || testname=="all") begin
      $display("[%0d] === test_fatal: pwrgood-cycle recovery ===", cyc);
      allow_fatal = 1;
      force tb_nios_top_fw.dut.cptra_error_fatal = 1'b1;
      repeat (4) @(posedge clk);
      if (!status_pio_export[5]) begin
        $display("TB_FATAL FAIL status bit5 not set"); $finish;
      end
      $display("[%0d] saw cptra_error_fatal; starting pwrgood cycle", cyc);
      ctrl_pio_export = 0;
      // pwrgood must sync-deassert before we release the force
      wait (tb_nios_top_fw.dut.cptra_pwrgood === 1'b0);
      release tb_nios_top_fw.dut.cptra_error_fatal;
      repeat (20) @(posedge clk);
      allow_fatal = 0;
      cold_release();
      wait_st(0);
      $display("[%0d] recovered ready_for_fuses after pwrgood cycle", cyc);
      // cold: fuses were cleared; full START required
      program_pauser_timer_wdt(1);
      start_fuses(0);
      $display("TB_FATAL PASS cyc=%0d (recovered through full fuse push)", cyc);
    end

    $display("TB_ALL PASS cyc=%0d trng=%0d", cyc, trng_reqs);
    $finish;
  end
endmodule

module tb_nios_top_fw;
  logic clk=0, rst_n=0; always #5 clk=~clk;
  initial begin repeat (5) @(posedge clk); rst_n=1; end
  logic [7:0] led;
  nios_caliptra_top dut (.clk, .reset_n(rst_n), .led);
  always @(posedge dut.etrng_req) $display("[tb] etrng_req rise status=%h", dut.status_in);
  // Caliptra ROM/FW log on generic_output_wires[7:0] (bit8 toggles per char)
  logic [8:0] prev_o; bit prev_v=0;
  always @(posedge clk) if (dut.cptra_rst_b) begin
    if (!prev_v) begin prev_o <= dut.generic_output_wires[8:0]; prev_v <= 1; end
    else if (dut.generic_output_wires[8:0] != prev_o) begin prev_o <= dut.generic_output_wires[8:0];
      $write("%c", dut.generic_output_wires[7:0]); $fflush; end
  end
endmodule

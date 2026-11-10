// Simulation stand-in (Verilator TB) for the Agilex 5 Reset Release IP (altera_s10_user_rst_clkgate,
// quartus_a5e_nios/ip/rst_release.ip). Like the vendor sim model, ninit_done is 1
// at time 0 (device still initializing) and drops to 0 shortly after; here it is
// held for 25 ns so the TB exercises the sys_reset_n = reset_n & ~ninit_done gate.
`timescale 1ns/1ps
module rst_release (output logic ninit_done);
  initial begin
    ninit_done = 1'b1;
    #25 ninit_done = 1'b0;
  end
endmodule

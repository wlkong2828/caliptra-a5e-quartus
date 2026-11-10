// Synthesis-only replacement for caliptra-rtl libs/rtl/caliptra_sram.sv (word-wide RAM, infers M20K).
// Initialized to 0 in the FPGA bitstream (config-time only; used here only for the
// mailbox SRAM; needs QSF VERILOG_CONSTANT_LOOP_LIMIT >= DEPTH). This is NOT a
// Caliptra-spec SRAM zeroization sweep on cptra_pwrgood (internal SRAM ports
// are owned by the TCB and are not muxed here). See docs/NIOS_CALIPTRA_INTEGRATION.md M8.
module caliptra_sram #(parameter DEPTH=64, parameter DATA_WIDTH=32, parameter ADDR_WIDTH=$clog2(DEPTH)) (
  input logic clk_i, input logic cs_i, input logic we_i,
  input logic [ADDR_WIDTH-1:0] addr_i, input logic [DATA_WIDTH-1:0] wdata_i,
  output logic [DATA_WIDTH-1:0] rdata_o);
  logic [DATA_WIDTH-1:0] ram [DEPTH];
  integer zi;
  initial begin
    for (zi = 0; zi < DEPTH; zi++) ram[zi] = '0;
    rdata_o = '0;
  end
  always_ff @(posedge clk_i) begin
    if (cs_i & we_i)  ram[addr_i] <= wdata_i;
    if (cs_i & ~we_i) rdata_o <= ram[addr_i];
  end
endmodule

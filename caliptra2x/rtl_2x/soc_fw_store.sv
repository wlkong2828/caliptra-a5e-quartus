// soc_fw_store.sv: read-only on-chip memory (M20K) holding the Caliptra (1.x: 28672 words; 2.x: 63360 words used of 65536)
// FMC+RT firmware bundle, initialised from FW_INIT_FILE (one 32-bit LE word per line).
// Stand-in for the SoC boot flash a real host would read the image from.
module soc_fw_store #(parameter int DEPTH = 28672, parameter string FW_INIT_FILE = "../fw/caliptra-fw-bundle.hex") (
  input  logic clk, input logic rd, input logic [$clog2(DEPTH)-1:0] waddr, output logic [31:0] rdata);
  logic [31:0] mem [DEPTH];
  initial $readmemh(FW_INIT_FILE, mem);
  always_ff @(posedge clk) if (rd) rdata <= mem[waddr];
endmodule

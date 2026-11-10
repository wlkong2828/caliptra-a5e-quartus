// Synthesis-only replacement for adams-bridge abr_1r1w_512x4_ram.sv (unpacked -> RAM inference).
module abr_1r1w_512x4_ram #(
     parameter DEPTH      = 512
    ,parameter DATA_WIDTH = 4
    ,parameter ADDR_WIDTH = $clog2(DEPTH)
)(
    input  logic                  clk_i,
    input  logic                  we_i,
    input  logic [ADDR_WIDTH-1:0] waddr_i,
    input  logic [DATA_WIDTH-1:0] wdata_i,
    input  logic                  re_i,
    input  logic [ADDR_WIDTH-1:0] raddr_i,
    output logic [DATA_WIDTH-1:0] rdata_o
);
    logic [DATA_WIDTH-1:0] ram [0:DEPTH-1];
    always_ff @(posedge clk_i) if (we_i) ram[waddr_i] <= wdata_i;
    always_ff @(posedge clk_i) if (re_i) rdata_o <= ram[raddr_i];
endmodule

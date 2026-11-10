// Synthesis-only replacement for adams-bridge abr_libs/rtl/abr_1r1w_be_ram.sv.
// Byte-enable simple dual-port RAM in the Quartus byte-enable inference template.
module abr_1r1w_be_ram #(
     parameter DEPTH        = 64
    ,parameter DATA_WIDTH   = 32
    ,parameter STROBE_WIDTH = 8
    ,localparam ADDR_WIDTH  = $clog2(DEPTH)
    ,localparam NB          = DATA_WIDTH/STROBE_WIDTH
)(
    input  logic                              clk_i,
    input  logic                              we_i,
    input  logic [NB-1:0]                     wstrobe_i,
    input  logic [ADDR_WIDTH-1:0]             waddr_i,
    input  logic [NB-1:0][STROBE_WIDTH-1:0]   wdata_i,
    input  logic                              re_i,
    input  logic [ADDR_WIDTH-1:0]             raddr_i,
    output logic [DATA_WIDTH-1:0]             rdata_o
);
    logic [NB-1:0][STROBE_WIDTH-1:0] ram [0:DEPTH-1];
    always_ff @(posedge clk_i) begin
        if (we_i) for (int b = 0; b < NB; b++) if (wstrobe_i[b]) ram[waddr_i][b] <= wdata_i[b];
    end
    always_ff @(posedge clk_i) if (re_i) rdata_o <= ram[raddr_i];
endmodule

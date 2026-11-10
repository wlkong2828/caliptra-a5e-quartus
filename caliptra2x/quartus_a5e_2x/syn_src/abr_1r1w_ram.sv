// Synthesis-only replacement for adams-bridge abr_libs/rtl/abr_1r1w_ram.sv (v2.1.2 / b77e3d8).
// Same ports/behaviour (1W1R, flopped read on re_i). Upstream uses a PACKED array, which Quartus
// may implement in registers; this version uses an unpacked array so it infers M20K/MLAB.
module abr_1r1w_ram #(
     parameter DEPTH      = 64
    ,parameter DATA_WIDTH = 32
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

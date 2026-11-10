// avmm_to_axi.sv - Avalon-MM agent (waitrequest + readdatavalid, no bursts/pipelining) ->
// AXI4 manager, single beat (AxLEN=0, AxSIZE=2 (32 b), AxBURST=INCR, WSTRB=4'hF, AxLOCK=0),
// one outstanding transaction. AxUSER/WUSER = user_i (the Nios AXI user ID, unique per agent).
// Caliptra 2.x (Integration Spec "Unsupported features"): single outstanding, in-order, no narrow
// writes to mbox_datain / TRNG_DATA -> full-word only. BRESP/RRESP != OKAY -> avs_response=SLVERR.
module avmm_to_axi #(
  parameter int AW = 18,      // Caliptra SoC AXI address width
  parameter int IW = 8,
  parameter int UW = 32
)(
  input  logic          clk, rst_n,
  // Avalon-MM agent (Platform Designer exported mm_bridge master)
  input  logic [AW-1:0] avs_address,      // byte address
  input  logic          avs_read, avs_write,
  input  logic [31:0]   avs_writedata,
  input  logic [3:0]    avs_byteenable,   // ignored: Caliptra SoC registers are 32-bit
  output logic [31:0]   avs_readdata,
  output logic          avs_readdatavalid,
  output logic          avs_waitrequest,
  output logic [1:0]    avs_response,     // 2'b10 SLVERR (last transaction)
  input  logic [UW-1:0] user_i,
  // AXI4 manager
  output logic [AW-1:0] awaddr,  output logic [1:0] awburst, output logic [2:0] awsize,
  output logic [7:0]    awlen,   output logic [UW-1:0] awuser, output logic [IW-1:0] awid,
  output logic          awlock,  output logic awvalid, input logic awready,
  output logic [31:0]   wdata,   output logic [3:0] wstrb, output logic [UW-1:0] wuser,
  output logic          wvalid,  input logic wready, output logic wlast,
  input  logic [1:0]    bresp,   input logic bvalid, output logic bready,
  output logic [AW-1:0] araddr,  output logic [1:0] arburst, output logic [2:0] arsize,
  output logic [7:0]    arlen,   output logic [UW-1:0] aruser, output logic [IW-1:0] arid,
  output logic          arlock,  output logic arvalid, input logic arready,
  input  logic [31:0]   rdata,   input logic [1:0] rresp, input logic rvalid, output logic rready,
  output logic          idle     // no transaction in flight (warm-reset quiesce)
);
  typedef enum logic [2:0] {IDLE, WADDR, WRESP, RADDR, RDATA, DONE, RESP} st_t;
  st_t st;
  logic [AW-1:0] addr_q; logic [31:0] wdata_q, rdata_q; logic wr_q, err_q, aw_done, w_done;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      st <= IDLE; addr_q <= '0; wdata_q <= '0; rdata_q <= '0; wr_q <= 1'b0; err_q <= 1'b0;
      aw_done <= 1'b0; w_done <= 1'b0;
    end else begin
      case (st)
        IDLE:  if (avs_read || avs_write) begin
                 addr_q <= {avs_address[AW-1:2], 2'b00}; wdata_q <= avs_writedata; wr_q <= avs_write;
                 aw_done <= 1'b0; w_done <= 1'b0;
                 st <= avs_write ? WADDR : RADDR;
               end
        WADDR: begin   // AW and W issued together, each dropped on its own handshake
                 if (awvalid && awready) aw_done <= 1'b1;
                 if (wvalid && wready)   w_done  <= 1'b1;
                 if ((aw_done || awready) && (w_done || wready)) st <= WRESP;
               end
        WRESP: if (bvalid) begin err_q <= (bresp != 2'b00); st <= DONE; end
        RADDR: if (arready) st <= RDATA;
        RDATA: if (rvalid) begin rdata_q <= rdata; err_q <= (rresp != 2'b00); st <= DONE; end
        DONE:  st <= wr_q ? IDLE : RESP;   // waitrequest low for one cycle = accept
        RESP:  st <= IDLE;                  // readdatavalid
        default: st <= IDLE;
      endcase
    end
  end
  assign awaddr = addr_q; assign araddr = addr_q;
  assign awburst = 2'b01; assign arburst = 2'b01; assign awsize = 3'd2; assign arsize = 3'd2;
  assign awlen = 8'd0; assign arlen = 8'd0; assign awlock = 1'b0; assign arlock = 1'b0;
  assign awid = '0; assign arid = '0; assign awuser = user_i; assign aruser = user_i; assign wuser = user_i;
  assign awvalid = (st == WADDR) && !aw_done;
  assign wvalid  = (st == WADDR) && !w_done;
  assign wdata = wdata_q; assign wstrb = 4'hF; assign wlast = 1'b1;
  assign bready  = (st == WRESP);
  assign arvalid = (st == RADDR);
  assign rready  = (st == RDATA);
  assign avs_waitrequest   = !(st == DONE);
  assign avs_readdata      = rdata_q;
  assign avs_readdatavalid = (st == RESP);
  assign avs_response      = err_q ? 2'b10 : 2'b00;
  assign idle = (st == IDLE);
endmodule

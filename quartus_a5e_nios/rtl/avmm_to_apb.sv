// avmm_to_apb.sv - Avalon-MM (waitrequest, no pipelining) -> APB3 subordinate bridge.
// One transfer at a time: SETUP (PSEL) -> ACCESS (PSEL+PENABLE) until PREADY.
// PAUSER is driven from pauser_i (the Nios AXI/APB user ID; default PAUSER_VAL=1).
module avmm_to_apb #(
  parameter int AW = 18,
  parameter logic [31:0] PAUSER_VAL = 32'h0000_0001
)(
  input  logic          clk, rst_n,
  // Avalon-MM agent (from Platform Designer exported mm_bridge master)
  input  logic [AW-1:0] avs_address,      // byte address
  input  logic          avs_read, avs_write,
  input  logic [31:0]   avs_writedata,
  input  logic [3:0]    avs_byteenable,   // ignored: Caliptra 1.x APB is 32-bit only
  output logic [31:0]   avs_readdata,
  output logic          avs_readdatavalid,
  output logic          avs_waitrequest,
  output logic [1:0]    avs_response,     // 2'b10 SLVERR when PSLVERR
  input  logic [31:0]   pauser_i,         // Nios AXI/APB user ID (tie to PAUSER_VAL)
  // APB requester
  output logic [31:0]   PADDR,
  output logic [2:0]    PPROT,
  output logic          PSEL, PENABLE, PWRITE,
  output logic [31:0]   PWDATA,
  output logic [31:0]   PAUSER,
  input  logic          PREADY, PSLVERR,
  input  logic [31:0]   PRDATA
);
  typedef enum logic [2:0] {IDLE, SETUP, ACCESS, DONE, RESP} st_t;
  st_t st;
  logic [31:0] addr_q, wdata_q, rdata_q;
  logic        wr_q, err_q;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      st <= IDLE; addr_q <= '0; wdata_q <= '0; wr_q <= 1'b0; rdata_q <= '0; err_q <= 1'b0;
    end else begin
      case (st)
        IDLE:   if (avs_read || avs_write) begin
                  addr_q  <= {{(32-AW){1'b0}}, avs_address[AW-1:2], 2'b00};
                  wdata_q <= avs_writedata;
                  wr_q    <= avs_write;
                  st      <= SETUP;
                end
        SETUP:  st <= ACCESS;
        ACCESS: if (PREADY) begin rdata_q <= PRDATA; err_q <= PSLVERR; st <= DONE; end
        DONE:   st <= wr_q ? IDLE : RESP;  // command accepted (waitrequest low)
        RESP:   st <= IDLE;               // readdatavalid one cycle after accept
        default: st <= IDLE;
      endcase
    end
  end

  assign PADDR   = addr_q;
  assign PPROT   = 3'b000;
  assign PSEL    = (st == SETUP) || (st == ACCESS);
  assign PENABLE = (st == ACCESS);
  assign PWRITE  = wr_q;
  assign PWDATA  = wdata_q;
  assign PAUSER  = pauser_i;

  // waitrequest held until DONE (accept); readdatavalid in RESP for reads
  assign avs_waitrequest   = !(st == DONE);
  assign avs_readdata      = rdata_q;
  assign avs_readdatavalid = (st == RESP);
  assign avs_response      = err_q ? 2'b10 : 2'b00; // unused unless mm_bridge USE_RESPONSE=1
endmodule

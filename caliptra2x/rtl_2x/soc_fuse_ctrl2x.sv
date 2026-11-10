// soc_fuse_ctrl2x.sv - SoC fuse controller soft IP for Caliptra 2.x passive mode (FPGA stand-in for
// OEM OTP + fuse sequencer). Port of quartus_a5e_nios/rtl/soc_fuse_ctrl.sv (1.x, APB) to AXI4.
// After ready_for_fuses it writes every entry of the on-chip "OTP" image (FUSE_IMAGE_FILE:
// {addr[31:0],data[31:0]} per line from scripts/gen_fuse_image_2x.py: 104 FUSE_* words incl.
// FUSE_PQC_KEY_TYPE, then CPTRA_OWNER_PK_HASH[12] + CPTRA_OWNER_PK_HASH_LOCK) and finally
// CPTRA_FUSE_WR_DONE=1, using its own AXI user FUSE_AXI_USER (host programs
// CPTRA_FUSE_VALID_AXI_USER = FUSE_AXI_USER + lock first). UDS/FE are never visible to the host CPU.
// TEST FUSE VALUES ONLY.
// Cold reset (pwrgood cycle): START (full image + DONE). Warm reset (rst_b only): START_DONE
// (FUSE_WR_DONE only; fuse and owner-hash registers are pwrgood-domain and persist).
// Nios MMIO (word regs, 4 KiB window), same map as the 1.x block:
//   0x00 ID RO 0x4655_5345 ("FUSE") | 0x04 CTRL WO bit0 START, bit1 CLEAR, bit2 START_DONE
//   0x08 STATUS RO bit0 BUSY, bit1 DONE, bit2 ERR, bit3 READY_FOR_FUSES | 0x0C COUNT RO
//   0x10 FW_BYTES RO | 0x14 NUM_FUSES RO (image entries)
module soc_fuse_ctrl2x #(
  parameter string       FUSE_IMAGE_FILE = "../fw_2x/fuse_image_2x.hex",
  parameter int          NUM_FUSES       = 117,
  parameter int          AW              = 18,
  parameter int          UW              = 32,
  parameter logic [31:0] FUSE_WR_DONE    = 32'h0003_00B0,
  parameter logic [31:0] FUSE_AXI_USER   = 32'h2,
  parameter logic [31:0] FW_BYTES        = 32'd253440
)(
  input  logic          clk, rst_n,
  input  logic          ready_for_fuses,
  input  logic          mmio_read, mmio_write,
  input  logic [11:0]   mmio_addr,
  input  logic [31:0]   mmio_wdata,
  output logic [31:0]   mmio_rdata,
  output logic          busy,            // owns the Caliptra AXI write channels while 1
  output logic [AW-1:0] awaddr, output logic awvalid, input logic awready,
  output logic [31:0]   wdata,  output logic wvalid,  input logic wready,
  output logic [UW-1:0] axi_user,
  input  logic [1:0]    bresp,  input logic bvalid,   output logic bready
);
  logic [63:0] img [NUM_FUSES];
  initial $readmemh(FUSE_IMAGE_FILE, img);

  typedef enum logic [2:0] {IDLE, NEXT, SEND, RESP, DONE, ERR} st_t;
  st_t st;
  logic [7:0]  idx;
  logic [31:0] cnt, addr_q, data_q;
  logic        done_q, err_q, aw_done, w_done, last;
  assign last = (idx == NUM_FUSES[7:0]);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      st <= IDLE; idx <= '0; cnt <= '0; done_q <= 1'b0; err_q <= 1'b0;
      addr_q <= '0; data_q <= '0; aw_done <= 1'b0; w_done <= 1'b0;
    end else begin
      if (mmio_write && mmio_addr[11:2] == 10'h1 && mmio_wdata[1]) begin done_q <= 1'b0; err_q <= 1'b0; end
      case (st)
        IDLE: if (mmio_write && mmio_addr[11:2] == 10'h1 && (mmio_wdata[0] || mmio_wdata[2])) begin
                if (!ready_for_fuses) begin err_q <= 1'b1; st <= ERR; end
                else begin
                  idx <= mmio_wdata[0] ? '0 : NUM_FUSES[7:0];   // START wins over START_DONE
                  cnt <= '0; done_q <= 1'b0; err_q <= 1'b0; st <= NEXT;
                end
              end
        NEXT: begin
                addr_q <= last ? FUSE_WR_DONE : img[idx][63:32];
                data_q <= last ? 32'h1        : img[idx][31:0];
                aw_done <= 1'b0; w_done <= 1'b0; st <= SEND;
              end
        SEND: begin
                if (awvalid && awready) aw_done <= 1'b1;
                if (wvalid && wready)   w_done  <= 1'b1;
                if ((aw_done || awready) && (w_done || wready)) st <= RESP;
              end
        RESP: if (bvalid) begin
                cnt <= cnt + 1;
                if (bresp != 2'b00) begin err_q <= 1'b1; st <= ERR; end
                else if (last) begin done_q <= 1'b1; st <= DONE; end
                else begin idx <= idx + 1; st <= NEXT; end
              end
        DONE, ERR: st <= IDLE;
        default: st <= IDLE;
      endcase
    end
  end
  assign busy     = (st == NEXT) || (st == SEND) || (st == RESP);
  assign awaddr   = addr_q[AW-1:0];
  assign wdata    = data_q;
  assign awvalid  = (st == SEND) && !aw_done;
  assign wvalid   = (st == SEND) && !w_done;
  assign bready   = (st == RESP);
  assign axi_user = FUSE_AXI_USER;

  always_ff @(posedge clk) if (mmio_read)
    case (mmio_addr[11:2])
      10'h0: mmio_rdata <= 32'h4655_5345;
      10'h2: mmio_rdata <= {28'h0, ready_for_fuses, err_q, done_q, busy};
      10'h3: mmio_rdata <= cnt;
      10'h4: mmio_rdata <= FW_BYTES;
      10'h5: mmio_rdata <= NUM_FUSES;
      default: mmio_rdata <= 32'h0;
    endcase
endmodule

// soc_fuse_ctrl.sv - SoC fuse controller soft IP (FPGA stand-in for OEM OTP + fuse sequencer).
// Real Caliptra 1.x integration: after cptra_rst_b the SoC fuse controller waits for
// ready_for_fuses, writes every FUSE_* register in soc_ifc over APB, then sets
// CPTRA_FUSE_WR_DONE. This block does exactly that from an on-chip "OTP" image
// (FUSE_IMAGE_FILE, 83 words for soc_ifc 0x200..0x348). UDS/field entropy are never
// readable by the host CPU (as with real OTP) - Nios only kicks START / START_DONE
// and reads status.
// TEST FUSE VALUES ONLY.
//
// Cold reset (pwrgood deasserted): fuses and FUSE_WR_DONE are cleared; SoC must
// re-push the full OTP image + FUSE_WR_DONE (CTRL bit0 START).
// Warm reset (rst_b only, pwrgood held): fuse contents and FUSE_WR_DONE persist,
// but the Boot FSM needs to observe a FUSE_WR_DONE write (swmod) after
// ready_for_fuses. Use CTRL bit2 START_DONE to write only CPTRA_FUSE_WR_DONE=1.
//
// Nios MMIO (word regs, 4 KiB window):
//   0x00 ID        RO  0x4655_5345 ("FUSE")
//   0x04 CTRL      WO  bit0 START (full 83 words + DONE), bit1 CLEAR (clear DONE/ERR),
//                      bit2 START_DONE (write only CPTRA_FUSE_WR_DONE; warm-reset path)
//   0x08 STATUS    RO  bit0 BUSY, bit1 DONE, bit2 ERR, bit3 READY_FOR_FUSES (live)
//   0x0C COUNT     RO  fuse words written (83+1 on full START, 1 on START_DONE)
//   0x10 FW_BYTES  RO  size of the FW bundle in soc_fw_store (bytes)
//   0x14 NUM_FUSES RO  83
module soc_fuse_ctrl #(
  parameter string       FUSE_IMAGE_FILE = "../fw/fuse_image.hex",
  parameter int          NUM_FUSES       = 83,
  parameter logic [31:0] FUSE_BASE       = 32'h0003_0200,   // soc_ifc FUSE_UDS_SEED_0
  parameter logic [31:0] FUSE_WR_DONE    = 32'h0003_00B0,   // soc_ifc CPTRA_FUSE_WR_DONE
  parameter logic [31:0] FW_BYTES        = 32'd109000
)(
  input  logic        clk, rst_n,
  input  logic        ready_for_fuses,
  // local MMIO from window decoder (1-cycle read latency)
  input  logic        mmio_read, mmio_write,
  input  logic [11:0] mmio_addr,
  input  logic [31:0] mmio_wdata,
  output logic [31:0] mmio_rdata,
  // APB requester (owns Caliptra APB while busy)
  output logic        busy,
  output logic [31:0] PADDR, PWDATA,
  output logic        PSEL, PENABLE, PWRITE,
  input  logic        PREADY, PSLVERR
);
  logic [31:0] img [NUM_FUSES];
  initial $readmemh(FUSE_IMAGE_FILE, img);

  typedef enum logic [2:0] {IDLE, SETUP, ACCESS, NEXT, DONE, ERR} st_t;
  st_t st;
  logic [7:0]  idx;          // 0..NUM_FUSES-1 = fuse words, NUM_FUSES = FUSE_WR_DONE
  logic [31:0] cnt;
  logic        done_q, err_q;
  logic        last;
  assign last = (idx == NUM_FUSES[7:0]);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      st <= IDLE; idx <= '0; cnt <= '0; done_q <= 1'b0; err_q <= 1'b0;
      PADDR <= '0; PWDATA <= '0;
    end else begin
      if (mmio_write && mmio_addr[11:2] == 10'h1 && mmio_wdata[1]) begin done_q <= 1'b0; err_q <= 1'b0; end
      case (st)
        IDLE: if (mmio_write && mmio_addr[11:2] == 10'h1 && (mmio_wdata[0] || mmio_wdata[2])) begin
                if (!ready_for_fuses) begin err_q <= 1'b1; st <= ERR; end
                else begin
                  // bit0 START (full image) wins over bit2 START_DONE if both are set
                  idx    <= mmio_wdata[0] ? '0 : NUM_FUSES[7:0];
                  cnt    <= '0; done_q <= 1'b0; err_q <= 1'b0;
                  st     <= NEXT;
                end
              end
        NEXT: begin   // load address/data for idx
                PADDR  <= last ? FUSE_WR_DONE : FUSE_BASE + {22'h0, idx, 2'b00};
                PWDATA <= last ? 32'h1 : img[idx];
                st     <= SETUP;
              end
        SETUP:  st <= ACCESS;
        ACCESS: if (PREADY) begin
                  cnt <= cnt + 1;
                  if (PSLVERR) begin err_q <= 1'b1; st <= ERR; end
                  else if (last) begin done_q <= 1'b1; st <= DONE; end
                  else begin idx <= idx + 1; st <= NEXT; end
                end
        DONE, ERR: st <= IDLE;
        default: st <= IDLE;
      endcase
    end
  end

  assign busy    = (st == NEXT) || (st == SETUP) || (st == ACCESS);
  assign PSEL    = (st == SETUP) || (st == ACCESS);
  assign PENABLE = (st == ACCESS);
  assign PWRITE  = 1'b1;

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

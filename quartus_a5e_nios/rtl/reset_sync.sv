// reset_sync.sv - Caliptra Integration Spec Table 4 / Reset-Domain Crossing:
//   cptra_pwrgood and cptra_rst_b must have asynchronous assertion and
//   synchronous deassertion to clk.
//
// cptra_rst_b is active-low: assert (1->0) is asynchronous; deassert (0->1)
//   is synchronized through STAGES flip-flops on clk.
// cptra_pwrgood is active-high: assert (0->1) is asynchronous; deassert
//   (1->0) is synchronized through STAGES flip-flops on clk.
//
// These blocks live *outside* the TCB, in the SoC glue, as required by the
// 1.x integration specification.

module rst_sync_async_assert #(
  parameter int STAGES = 2
)(
  input  logic clk,
  input  logic async_rst_n, // raw, active-low
  output logic rst_n        // sync-deasserted, active-low
);
  (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
  logic [STAGES-1:0] ff;
  always_ff @(posedge clk or negedge async_rst_n) begin
    if (!async_rst_n) ff <= '0;
    else              ff <= {ff[STAGES-2:0], 1'b1};
  end
  assign rst_n = ff[STAGES-1];
endmodule

module pwrgood_sync_async_assert #(
  parameter int STAGES = 2
)(
  input  logic clk,
  input  logic async_pwrgood, // raw, active-high
  output logic pwrgood        // sync-deasserted, active-high
);
  (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
  logic [STAGES-1:0] ff;
  // Async set when power-good asserts; shift zeros in on clk once it drops
  // so the falling edge is synchronous to clk.
  always_ff @(posedge clk or posedge async_pwrgood) begin
    if (async_pwrgood) ff <= '1;
    else               ff <= {ff[STAGES-2:0], 1'b0};
  end
  assign pwrgood = ff[STAGES-1];
endmodule

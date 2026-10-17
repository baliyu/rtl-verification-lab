// async_fifo.v - asynchronous FIFO: a queue between a write clock and an unrelated read clock (Verilog-2001).
//
// The classic design with Gray-coded pointers (after Cummings, "Simulation and Synthesis Techniques for Asynchronous FIFO Design").
// The memory holds 2**ADDR_WIDTH words. Each side keeps a binary pointer for addressing the memory and a Gray-coded copy of it that is
// sent to the other clock domain through a two-flop synchroniser (sync_2ff). Only one bit of a Gray code changes at a time, so the
// other side always sees either the old or the new pointer, never a mixture. Each side compares the other side's (old) pointer with
// its own to decide its flag, so the flags are cautious: w_full can rise a little early and fall a little late, r_empty can fall a
// little late, but a write is never accepted into a full FIFO and a read never returns data that is not there.
//
// Write side (wclk): a word is stored on the clock edge where w_en is 1 and w_full is 0; w_en while w_full is 1 is ignored.
// Read side (rclk): "first word fall through": while r_empty is 0, r_data already shows the oldest word. The word is removed on the
// clock edge where r_en is 1 and r_empty is 0; r_en while r_empty is 1 is ignored.
// Resets are synchronous and active high, one per clock domain. Assert BOTH together, for at least two cycles of the slower clock, and
// do not read or write until both have been released.
module async_fifo #(
    parameter DATA_WIDTH = 8,
    parameter ADDR_WIDTH = 4             // at least 2
) (
    input  wire                  wclk,
    input  wire                  wrst,
    input  wire                  w_en,
    input  wire [DATA_WIDTH-1:0] w_data,
    output reg                   w_full,
    input  wire                  rclk,
    input  wire                  rrst,
    input  wire                  r_en,
    output wire [DATA_WIDTH-1:0] r_data,
    output reg                   r_empty
);
    localparam DEPTH = 1 << ADDR_WIDTH;

    reg [DATA_WIDTH-1:0] mem [0:DEPTH-1];

    reg  [ADDR_WIDTH:0] wbin;            // write pointer, binary (addresses the memory)
    reg  [ADDR_WIDTH:0] wptr;            // the same, Gray-coded (crosses to the read clock)
    reg  [ADDR_WIDTH:0] rbin;
    reg  [ADDR_WIDTH:0] rptr;
    wire [ADDR_WIDTH:0] wq_rptr;         // the read pointer, as seen by the write clock
    wire [ADDR_WIDTH:0] rq_wptr;         // the write pointer, as seen by the read clock

    sync_2ff #(.WIDTH(ADDR_WIDTH + 1)) u_sync_r2w (.clk(wclk), .rst(wrst), .d(rptr), .q(wq_rptr));
    sync_2ff #(.WIDTH(ADDR_WIDTH + 1)) u_sync_w2r (.clk(rclk), .rst(rrst), .d(wptr), .q(rq_wptr));

    // write side
    wire                w_push      = w_en && !w_full;
    wire [ADDR_WIDTH:0] wbin_next   = wbin + (w_push ? 1 : 0);
    wire [ADDR_WIDTH:0] wgray_next  = (wbin_next >> 1) ^ wbin_next;
    wire                full_next   = (wgray_next == {~wq_rptr[ADDR_WIDTH:ADDR_WIDTH-1], wq_rptr[ADDR_WIDTH-2:0]});

    always @(posedge wclk) begin
        if (wrst) begin
            wbin   <= {(ADDR_WIDTH + 1){1'b0}};
            wptr   <= {(ADDR_WIDTH + 1){1'b0}};
            w_full <= 1'b0;
        end else begin
            if (w_push) mem[wbin[ADDR_WIDTH-1:0]] <= w_data;
            wbin   <= wbin_next;
            wptr   <= wgray_next;
            w_full <= full_next;
        end
    end

    // read side
    wire                r_pop       = r_en && !r_empty;
    wire [ADDR_WIDTH:0] rbin_next   = rbin + (r_pop ? 1 : 0);
    wire [ADDR_WIDTH:0] rgray_next  = (rbin_next >> 1) ^ rbin_next;
    wire                empty_next  = (rgray_next == rq_wptr);

    assign r_data = mem[rbin[ADDR_WIDTH-1:0]];

    always @(posedge rclk) begin
        if (rrst) begin
            rbin    <= {(ADDR_WIDTH + 1){1'b0}};
            rptr    <= {(ADDR_WIDTH + 1){1'b0}};
            r_empty <= 1'b1;
        end else begin
            rbin    <= rbin_next;
            rptr    <= rgray_next;
            r_empty <= empty_next;
        end
    end
endmodule

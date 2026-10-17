// uart_rx.v - 8N1 UART receiver (Verilog-2001).
//
// Waits for a falling edge on rxd, confirms the start bit again half a bit later (a shorter glitch is ignored),
// then samples every CLKS_PER_BIT cycles, near the middle of each bit. rxd goes through a two-flop synchroniser.
//
// A good frame (stop bit = 1) gives a one-cycle pulse on rx_valid with the byte on rx_data. A bad stop bit gives
// a one-cycle pulse on rx_error instead, and the receiver then waits for the line to go high before it looks
// for the next start bit (so a long "break", with the line held low, gives one error and not a stream of them).
// Reset is synchronous and active high.
module uart_rx #(
    parameter CLKS_PER_BIT = 16          // clock cycles per bit, at least 4
) (
    input  wire       clk,
    input  wire       rst,
    input  wire       rxd,
    output reg  [7:0] rx_data,
    output reg        rx_valid,
    output reg        rx_error
);
    localparam S_IDLE = 3'd0, S_START = 3'd1, S_DATA = 3'd2, S_STOP = 3'd3, S_WAIT = 3'd4;

    reg        rxd_m, rxd_s;             // synchroniser
    reg [2:0]  state;
    reg [31:0] clk_cnt;
    reg [2:0]  bit_idx;
    reg [7:0]  shreg;

    always @(posedge clk) begin
        if (rst) begin
            rxd_m    <= 1'b1;
            rxd_s    <= 1'b1;
            state    <= S_IDLE;
            clk_cnt  <= 32'd0;
            bit_idx  <= 3'd0;
            shreg    <= 8'd0;
            rx_data  <= 8'd0;
            rx_valid <= 1'b0;
            rx_error <= 1'b0;
        end else begin
            rxd_m <= rxd;
            rxd_s <= rxd_m;
            case (state)
                S_IDLE: begin
                    rx_valid <= 1'b0;
                    rx_error <= 1'b0;
                    if (rxd_s == 1'b0) begin
                        clk_cnt <= 32'd0;
                        state   <= S_START;
                    end
                end
                S_START: begin
                    if (clk_cnt == (CLKS_PER_BIT / 2) - 1) begin
                        if (rxd_s == 1'b0) begin         // still low: a real start bit
                            clk_cnt <= 32'd0;
                            bit_idx <= 3'd0;
                            state   <= S_DATA;
                        end else begin                   // a glitch
                            state <= S_IDLE;
                        end
                    end else begin
                        clk_cnt <= clk_cnt + 32'd1;
                    end
                end
                S_DATA: begin
                    if (clk_cnt == CLKS_PER_BIT - 1) begin
                        clk_cnt <= 32'd0;
                        shreg   <= {rxd_s, shreg[7:1]};  // least significant bit arrives first
                        if (bit_idx == 3'd7) state <= S_STOP;
                        else                 bit_idx <= bit_idx + 3'd1;
                    end else begin
                        clk_cnt <= clk_cnt + 32'd1;
                    end
                end
                S_STOP: begin
                    if (clk_cnt == CLKS_PER_BIT - 1) begin
                        clk_cnt <= 32'd0;
                        if (rxd_s == 1'b1) begin
                            rx_data  <= shreg;
                            rx_valid <= 1'b1;
                            state    <= S_IDLE;
                        end else begin
                            rx_error <= 1'b1;
                            state    <= S_WAIT;
                        end
                    end else begin
                        clk_cnt <= clk_cnt + 32'd1;
                    end
                end
                S_WAIT: begin
                    rx_error <= 1'b0;
                    if (rxd_s == 1'b1) state <= S_IDLE;
                end
                default: state <= S_IDLE;
            endcase
        end
    end
endmodule

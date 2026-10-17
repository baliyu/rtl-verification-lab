// uart_tx.v - 8N1 UART transmitter (Verilog-2001).
//
// One byte per transfer: a start bit (0), eight data bits least-significant first, one stop bit (1).
// Every bit lasts exactly CLKS_PER_BIT clock cycles. The line idles high.
//
// Handshake: a byte is taken on the clock edge where tx_valid and tx_ready are both 1. tx_ready is 1 only
// while the transmitter is idle. A tx_valid pulse that arrives while a frame is being sent is ignored.
// Reset is synchronous and active high.
module uart_tx #(
    parameter CLKS_PER_BIT = 16          // clock cycles per bit, at least 4
) (
    input  wire       clk,
    input  wire       rst,
    input  wire [7:0] tx_data,
    input  wire       tx_valid,
    output wire       tx_ready,
    output reg        txd
);
    localparam S_IDLE = 2'd0, S_START = 2'd1, S_DATA = 2'd2, S_STOP = 2'd3;

    reg [1:0]  state;
    reg [31:0] clk_cnt;
    reg [2:0]  bit_idx;
    reg [7:0]  shreg;

    assign tx_ready = (state == S_IDLE);

    always @(posedge clk) begin
        if (rst) begin
            state   <= S_IDLE;
            txd     <= 1'b1;
            clk_cnt <= 32'd0;
            bit_idx <= 3'd0;
            shreg   <= 8'd0;
        end else begin
            case (state)
                S_IDLE: begin
                    txd <= 1'b1;
                    if (tx_valid) begin
                        shreg   <= tx_data;
                        txd     <= 1'b0;                 // start bit begins on the next clock
                        clk_cnt <= 32'd0;
                        state   <= S_START;
                    end
                end
                S_START: begin
                    if (clk_cnt == CLKS_PER_BIT - 1) begin
                        clk_cnt <= 32'd0;
                        bit_idx <= 3'd0;
                        txd     <= shreg[0];
                        state   <= S_DATA;
                    end else begin
                        clk_cnt <= clk_cnt + 32'd1;
                    end
                end
                S_DATA: begin
                    if (clk_cnt == CLKS_PER_BIT - 1) begin
                        clk_cnt <= 32'd0;
                        if (bit_idx == 3'd7) begin
                            txd   <= 1'b1;               // stop bit
                            state <= S_STOP;
                        end else begin
                            bit_idx <= bit_idx + 3'd1;
                            txd     <= shreg[bit_idx + 3'd1];
                        end
                    end else begin
                        clk_cnt <= clk_cnt + 32'd1;
                    end
                end
                S_STOP: begin
                    if (clk_cnt == CLKS_PER_BIT - 1) begin
                        clk_cnt <= 32'd0;
                        state   <= S_IDLE;
                    end else begin
                        clk_cnt <= clk_cnt + 32'd1;
                    end
                end
                default: state <= S_IDLE;
            endcase
        end
    end
endmodule

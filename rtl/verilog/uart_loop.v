// uart_loop.v - a transmitter wired to a receiver, for end-to-end tests.
module uart_loop #(
    parameter CLKS_PER_BIT = 16
) (
    input  wire       clk,
    input  wire       rst,
    input  wire [7:0] tx_data,
    input  wire       tx_valid,
    output wire       tx_ready,
    output wire [7:0] rx_data,
    output wire       rx_valid,
    output wire       rx_error
);
    wire line;
    uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_tx (
        .clk(clk), .rst(rst), .tx_data(tx_data), .tx_valid(tx_valid), .tx_ready(tx_ready), .txd(line));
    uart_rx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_rx (
        .clk(clk), .rst(rst), .rxd(line), .rx_data(rx_data), .rx_valid(rx_valid), .rx_error(rx_error));
endmodule

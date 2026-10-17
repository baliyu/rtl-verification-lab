// spi_master.v - SPI master, all four modes, one chip select (Verilog-2001).
//
// A transfer sends WIDTH bits on mosi, most-significant bit first, and receives WIDTH bits from miso at the same time.
// The mode is chosen by cpol (the level sclk idles at) and cpha (0: data is sampled on the first sclk edge and changes on the second;
// 1: data changes on the first edge and is sampled on the second). cpol, cpha and tx_data are copied when the transfer starts,
// so changing them during a transfer has no effect.
//
// Handshake: a transfer starts on the clock edge where start is 1 and busy is 0. busy is 1 from the next clock until the transfer has
// finished; a start pulse while busy is ignored. When the transfer finishes, done is 1 for one clock and rx_data holds the received word
// (it keeps that value until the next transfer finishes).
//
// Timing, with H = CLKS_PER_HALF system clocks per half period of sclk: cs_n goes low, the first sclk edge comes H clocks later,
// then there are 2*WIDTH edges H clocks apart, and cs_n goes high H clocks after the last edge: cs_n is low for (2*WIDTH+1)*H clocks.
// Between two transfers cs_n is high for at least one clock. mosi and sclk change on the same clock edge (the RTL has no delay between them).
// Reset is synchronous and active high.
module spi_master #(
    parameter CLKS_PER_HALF = 4,         // system clocks per half sclk period, at least 1
    parameter WIDTH         = 8          // bits per transfer, at least 2
) (
    input  wire             clk,
    input  wire             rst,
    input  wire             start,
    input  wire [WIDTH-1:0] tx_data,
    input  wire             cpol,
    input  wire             cpha,
    output reg              busy,
    output reg              done,
    output reg  [WIDTH-1:0] rx_data,
    output reg              sclk,
    output reg              mosi,
    input  wire             miso,
    output reg              cs_n
);
    localparam S_IDLE = 2'd0, S_XFER = 2'd1, S_HOLD = 2'd2;

    reg [1:0]       state;
    reg [31:0]      cnt;                 // clocks into the current half period
    reg [31:0]      edge_cnt;            // sclk edges so far in this transfer
    reg [WIDTH-1:0] tx_r;
    reg [WIDTH-1:0] rx_r;
    reg             cpha_r;

    always @(posedge clk) begin
        if (rst) begin
            state    <= S_IDLE;
            busy     <= 1'b0;
            done     <= 1'b0;
            rx_data  <= {WIDTH{1'b0}};
            sclk     <= cpol;
            mosi     <= 1'b0;
            cs_n     <= 1'b1;
            cnt      <= 32'd0;
            edge_cnt <= 32'd0;
            tx_r     <= {WIDTH{1'b0}};
            rx_r     <= {WIDTH{1'b0}};
            cpha_r   <= 1'b0;
        end else begin
            done <= 1'b0;
            case (state)
                S_IDLE: begin
                    sclk <= cpol;
                    mosi <= 1'b0;
                    cs_n <= 1'b1;
                    if (start) begin
                        tx_r     <= tx_data;
                        cpha_r   <= cpha;
                        rx_r     <= {WIDTH{1'b0}};
                        cs_n     <= 1'b0;
                        mosi     <= cpha ? 1'b0 : tx_data[WIDTH-1];   // mode 0 and 2: the first bit is ready before the first edge
                        busy     <= 1'b1;
                        cnt      <= 32'd0;
                        edge_cnt <= 32'd0;
                        state    <= S_XFER;
                    end
                end
                S_XFER: begin
                    if (cnt == CLKS_PER_HALF - 1) begin
                        cnt  <= 32'd0;
                        sclk <= ~sclk;
                        if (edge_cnt[0] == 1'b0) begin                 // first edge of a bit
                            if (cpha_r == 1'b0) rx_r <= {rx_r[WIDTH-2:0], miso};
                            else                mosi <= tx_r[WIDTH-1 - (edge_cnt >> 1)];
                        end else begin                                 // second edge of a bit
                            if (cpha_r == 1'b1) rx_r <= {rx_r[WIDTH-2:0], miso};
                            else if ((edge_cnt >> 1) < WIDTH - 1) mosi <= tx_r[WIDTH-2 - (edge_cnt >> 1)];
                        end
                        edge_cnt <= edge_cnt + 32'd1;
                        if (edge_cnt == 2 * WIDTH - 1) begin
                            state <= S_HOLD;
                        end
                    end else begin
                        cnt <= cnt + 32'd1;
                    end
                end
                S_HOLD: begin
                    if (cnt == CLKS_PER_HALF - 1) begin
                        cnt     <= 32'd0;
                        cs_n    <= 1'b1;
                        mosi    <= 1'b0;
                        busy    <= 1'b0;
                        done    <= 1'b1;
                        rx_data <= rx_r;
                        state   <= S_IDLE;
                    end else begin
                        cnt <= cnt + 32'd1;
                    end
                end
                default: state <= S_IDLE;
            endcase
        end
    end
endmodule

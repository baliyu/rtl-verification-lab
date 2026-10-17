// sync_2ff_meta.v - a deliberately nasty stand-in for sync_2ff, used only by the tests (never part of the design).
//
// Same ports as sync_2ff. It models a bus whose wires are not equally fast. Each time the input changes, every bit that changed gets its own random
// arrival time between 0 and WINDOW nanoseconds (a fixed-seed shift register, so every run is the same); until that time has passed, the receiving
// flops still see that bit's OLD value, afterwards its NEW value, and it never goes back. Only the most recent change is tracked.
//
// A Gray-coded pointer changes one bit at a time, so the receiver sees the old or the new pointer whatever the skew. A plain binary pointer
// changes several bits at once (0111 -> 1000), so for a while the receiver can see a mixture that never existed; if the receiving clock is
// faster than the window, that is several clocks in a row. This is the hazard that a zero-delay simulation cannot show.
module sync_2ff #(
    parameter WIDTH = 1
) (
    input  wire             clk,
    input  wire             rst,
    input  wire [WIDTH-1:0] d,
    output wire [WIDTH-1:0] q
);
    localparam real WINDOW = 8.0;        // nanoseconds (the testbench builds with a 1 ns time unit)

    reg [WIDTH-1:0] s1;
    reg [WIDTH-1:0] s2;
    reg [WIDTH-1:0] d_old;               // the input just before its latest change
    reg [WIDTH-1:0] d_cur;
    real            arrive [0:WIDTH-1];  // per bit: how long after the latest change its new value reaches the flops
    realtime        t_change;            // when the latest change happened
    reg [15:0]      lfsr;
    integer         i;
    integer         k;

    assign q = s2;

    initial begin
        d_old    = {WIDTH{1'b0}};
        d_cur    = {WIDTH{1'b0}};
        t_change = 0.0;
        lfsr     = 16'hACE1;
        for (k = 0; k < WIDTH; k = k + 1) arrive[k] = 0.0;
    end

    always @(d) begin
        d_old    = d_cur;
        d_cur    = d;
        t_change = $realtime;
        for (k = 0; k < WIDTH; k = k + 1) begin
            lfsr      = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
            arrive[k] = WINDOW * (lfsr[7:0] / 256.0);
        end
    end

    always @(posedge clk) begin
        if (rst) begin
            s1 <= {WIDTH{1'b0}};
            s2 <= {WIDTH{1'b0}};
        end else begin
            for (i = 0; i < WIDTH; i = i + 1) begin
                if (d[i] !== d_old[i] && ($realtime - t_change) < arrive[i]) s1[i] <= d_old[i];   // the new value has not reached us yet
                else                                                         s1[i] <= d[i];
            end
            s2 <= s1;
        end
    end
endmodule

// sync_2ff.v - two-flop synchroniser: brings a signal from another clock domain into this one (Verilog-2001).
//
// A signal that changes at an unrelated moment can be caught by a flop in the middle of its change (metastability). The first flop may
// settle to either value; the second flop gives it a whole clock period to settle before anything uses it. Only a signal in which at most
// ONE bit changes at a time (such as a Gray-coded counter) may be passed through this way: for a multi-bit change each bit settles
// on its own, and the receiver can see a mixture of old and new bits that never existed.
// Reset is synchronous and active high.
module sync_2ff #(
    parameter WIDTH = 1
) (
    input  wire             clk,         // the receiving clock
    input  wire             rst,
    input  wire [WIDTH-1:0] d,           // from the other clock domain
    output wire [WIDTH-1:0] q
);
    reg [WIDTH-1:0] s1;
    reg [WIDTH-1:0] s2;

    assign q = s2;

    always @(posedge clk) begin
        if (rst) begin
            s1 <= {WIDTH{1'b0}};
            s2 <= {WIDTH{1'b0}};
        end else begin
            s1 <= d;
            s2 <= s1;
        end
    end
endmodule

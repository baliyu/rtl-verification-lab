-- uart_tx.vhd - 8N1 UART transmitter (VHDL-93).
--
-- One byte per transfer: a start bit (0), eight data bits least-significant first, one stop bit (1).
-- Every bit lasts exactly CLKS_PER_BIT clock cycles. The line idles high.
--
-- Handshake: a byte is taken on the clock edge where tx_valid and tx_ready are both 1. tx_ready is 1 only
-- while the transmitter is idle. A tx_valid pulse that arrives while a frame is being sent is ignored.
-- Reset is synchronous and active high.
library ieee;
use ieee.std_logic_1164.all;

entity uart_tx is
  generic (
    CLKS_PER_BIT : positive := 16          -- clock cycles per bit, at least 4
  );
  port (
    clk      : in  std_logic;
    rst      : in  std_logic;
    tx_data  : in  std_logic_vector(7 downto 0);
    tx_valid : in  std_logic;
    tx_ready : out std_logic;
    txd      : out std_logic
  );
end entity uart_tx;

architecture rtl of uart_tx is
  type state_t is (S_IDLE, S_START, S_DATA, S_STOP);
  signal state   : state_t := S_IDLE;
  signal clk_cnt : integer range 0 to CLKS_PER_BIT - 1 := 0;
  signal bit_idx : integer range 0 to 7 := 0;
  signal shreg   : std_logic_vector(7 downto 0) := (others => '0');
  signal txd_r   : std_logic := '1';
begin
  tx_ready <= '1' when state = S_IDLE else '0';
  txd      <= txd_r;

  process (clk)
  begin
    if rising_edge(clk) then
      if rst = '1' then
        state   <= S_IDLE;
        txd_r   <= '1';
        clk_cnt <= 0;
        bit_idx <= 0;
        shreg   <= (others => '0');
      else
        case state is
          when S_IDLE =>
            txd_r <= '1';
            if tx_valid = '1' then
              shreg   <= tx_data;
              txd_r   <= '0';                       -- start bit begins on the next clock
              clk_cnt <= 0;
              state   <= S_START;
            end if;

          when S_START =>
            if clk_cnt = CLKS_PER_BIT - 1 then
              clk_cnt <= 0;
              bit_idx <= 0;
              txd_r   <= shreg(0);
              state   <= S_DATA;
            else
              clk_cnt <= clk_cnt + 1;
            end if;

          when S_DATA =>
            if clk_cnt = CLKS_PER_BIT - 1 then
              clk_cnt <= 0;
              if bit_idx = 7 then
                txd_r <= '1';                       -- stop bit
                state <= S_STOP;
              else
                bit_idx <= bit_idx + 1;
                txd_r   <= shreg(bit_idx + 1);
              end if;
            else
              clk_cnt <= clk_cnt + 1;
            end if;

          when S_STOP =>
            if clk_cnt = CLKS_PER_BIT - 1 then
              clk_cnt <= 0;
              state   <= S_IDLE;
            else
              clk_cnt <= clk_cnt + 1;
            end if;
        end case;
      end if;
    end if;
  end process;
end architecture rtl;

-- uart_rx.vhd - 8N1 UART receiver (VHDL-93).
--
-- Waits for a falling edge on rxd, confirms the start bit again half a bit later (a shorter glitch is ignored),
-- then samples every CLKS_PER_BIT cycles, near the middle of each bit. rxd goes through a two-flop synchroniser.
--
-- A good frame (stop bit = 1) gives a one-cycle pulse on rx_valid with the byte on rx_data. A bad stop bit gives
-- a one-cycle pulse on rx_error instead, and the receiver then waits for the line to go high before it looks
-- for the next start bit (so a long "break", with the line held low, gives one error and not a stream of them).
-- Reset is synchronous and active high.
library ieee;
use ieee.std_logic_1164.all;

entity uart_rx is
  generic (
    CLKS_PER_BIT : positive := 16          -- clock cycles per bit, at least 4
  );
  port (
    clk      : in  std_logic;
    rst      : in  std_logic;
    rxd      : in  std_logic;
    rx_data  : out std_logic_vector(7 downto 0);
    rx_valid : out std_logic;
    rx_error : out std_logic
  );
end entity uart_rx;

architecture rtl of uart_rx is
  type state_t is (S_IDLE, S_START, S_DATA, S_STOP, S_WAIT);
  signal state    : state_t := S_IDLE;
  signal rxd_m    : std_logic := '1';             -- synchroniser
  signal rxd_s    : std_logic := '1';
  signal clk_cnt  : integer range 0 to CLKS_PER_BIT - 1 := 0;
  signal bit_idx  : integer range 0 to 7 := 0;
  signal shreg    : std_logic_vector(7 downto 0) := (others => '0');
  signal data_r   : std_logic_vector(7 downto 0) := (others => '0');
  signal valid_r  : std_logic := '0';
  signal error_r  : std_logic := '0';
begin
  rx_data  <= data_r;
  rx_valid <= valid_r;
  rx_error <= error_r;

  process (clk)
  begin
    if rising_edge(clk) then
      if rst = '1' then
        rxd_m   <= '1';
        rxd_s   <= '1';
        state   <= S_IDLE;
        clk_cnt <= 0;
        bit_idx <= 0;
        shreg   <= (others => '0');
        data_r  <= (others => '0');
        valid_r <= '0';
        error_r <= '0';
      else
        rxd_m <= rxd;
        rxd_s <= rxd_m;
        case state is
          when S_IDLE =>
            valid_r <= '0';
            error_r <= '0';
            if rxd_s = '0' then
              clk_cnt <= 0;
              state   <= S_START;
            end if;

          when S_START =>
            if clk_cnt = (CLKS_PER_BIT / 2) - 1 then
              if rxd_s = '0' then                   -- still low: a real start bit
                clk_cnt <= 0;
                bit_idx <= 0;
                state   <= S_DATA;
              else                                  -- a glitch
                state <= S_IDLE;
              end if;
            else
              clk_cnt <= clk_cnt + 1;
            end if;

          when S_DATA =>
            if clk_cnt = CLKS_PER_BIT - 1 then
              clk_cnt <= 0;
              shreg   <= rxd_s & shreg(7 downto 1); -- least significant bit arrives first
              if bit_idx = 7 then
                state <= S_STOP;
              else
                bit_idx <= bit_idx + 1;
              end if;
            else
              clk_cnt <= clk_cnt + 1;
            end if;

          when S_STOP =>
            if clk_cnt = CLKS_PER_BIT - 1 then
              clk_cnt <= 0;
              if rxd_s = '1' then
                data_r  <= shreg;
                valid_r <= '1';
                state   <= S_IDLE;
              else
                error_r <= '1';
                state   <= S_WAIT;
              end if;
            else
              clk_cnt <= clk_cnt + 1;
            end if;

          when S_WAIT =>
            error_r <= '0';
            if rxd_s = '1' then
              state <= S_IDLE;
            end if;
        end case;
      end if;
    end if;
  end process;
end architecture rtl;

-- spi_master.vhd - SPI master, all four modes, one chip select (VHDL-93).
--
-- A transfer sends WIDTH bits on mosi, most-significant bit first, and receives WIDTH bits from miso at the same time.
-- The mode is chosen by cpol (the level sclk idles at) and cpha (0: data is sampled on the first sclk edge and changes on the second;
-- 1: data changes on the first edge and is sampled on the second). cpol, cpha and tx_data are copied when the transfer starts,
-- so changing them during a transfer has no effect.
--
-- Handshake: a transfer starts on the clock edge where start is 1 and busy is 0. busy is 1 from the next clock until the transfer has
-- finished; a start pulse while busy is ignored. When the transfer finishes, done is 1 for one clock and rx_data holds the received word
-- (it keeps that value until the next transfer finishes).
--
-- Timing, with H = CLKS_PER_HALF system clocks per half period of sclk: cs_n goes low, the first sclk edge comes H clocks later,
-- then there are 2*WIDTH edges H clocks apart, and cs_n goes high H clocks after the last edge: cs_n is low for (2*WIDTH+1)*H clocks.
-- Between two transfers cs_n is high for at least one clock. mosi and sclk change on the same clock edge (the RTL has no delay between them).
-- Reset is synchronous and active high.
library ieee;
use ieee.std_logic_1164.all;

entity spi_master is
  generic (
    CLKS_PER_HALF : positive := 4;                  -- system clocks per half sclk period, at least 1
    WIDTH         : integer range 2 to 64 := 8      -- bits per transfer, at least 2
  );
  port (
    clk     : in  std_logic;
    rst     : in  std_logic;
    start   : in  std_logic;
    tx_data : in  std_logic_vector(WIDTH - 1 downto 0);
    cpol    : in  std_logic;
    cpha    : in  std_logic;
    busy    : out std_logic;
    done    : out std_logic;
    rx_data : out std_logic_vector(WIDTH - 1 downto 0);
    sclk    : out std_logic;
    mosi    : out std_logic;
    miso    : in  std_logic;
    cs_n    : out std_logic
  );
end entity spi_master;

architecture rtl of spi_master is
  type state_t is (S_IDLE, S_XFER, S_HOLD);
  signal state     : state_t := S_IDLE;
  signal cnt       : integer range 0 to CLKS_PER_HALF - 1 := 0;     -- clocks into the current half period
  signal edge_cnt  : integer range 0 to 2 * WIDTH - 1 := 0;         -- sclk edges so far in this transfer
  signal tx_r      : std_logic_vector(WIDTH - 1 downto 0) := (others => '0');
  signal rx_r      : std_logic_vector(WIDTH - 1 downto 0) := (others => '0');
  signal cpha_r    : std_logic := '0';
  signal busy_r    : std_logic := '0';
  signal done_r    : std_logic := '0';
  signal rx_data_r : std_logic_vector(WIDTH - 1 downto 0) := (others => '0');
  signal sclk_r    : std_logic := '0';
  signal mosi_r    : std_logic := '0';
  signal cs_n_r    : std_logic := '1';
begin
  busy    <= busy_r;
  done    <= done_r;
  rx_data <= rx_data_r;
  sclk    <= sclk_r;
  mosi    <= mosi_r;
  cs_n    <= cs_n_r;

  process (clk)
  begin
    if rising_edge(clk) then
      if rst = '1' then
        state     <= S_IDLE;
        busy_r    <= '0';
        done_r    <= '0';
        rx_data_r <= (others => '0');
        sclk_r    <= cpol;
        mosi_r    <= '0';
        cs_n_r    <= '1';
        cnt       <= 0;
        edge_cnt  <= 0;
        tx_r      <= (others => '0');
        rx_r      <= (others => '0');
        cpha_r    <= '0';
      else
        done_r <= '0';
        case state is
          when S_IDLE =>
            sclk_r <= cpol;
            mosi_r <= '0';
            cs_n_r <= '1';
            if start = '1' then
              tx_r     <= tx_data;
              cpha_r   <= cpha;
              rx_r     <= (others => '0');
              cs_n_r   <= '0';
              if cpha = '1' then                    -- mode 0 and 2: the first bit is ready before the first edge
                mosi_r <= '0';
              else
                mosi_r <= tx_data(WIDTH - 1);
              end if;
              busy_r   <= '1';
              cnt      <= 0;
              edge_cnt <= 0;
              state    <= S_XFER;
            end if;

          when S_XFER =>
            if cnt = CLKS_PER_HALF - 1 then
              cnt    <= 0;
              sclk_r <= not sclk_r;
              if edge_cnt mod 2 = 0 then            -- first edge of a bit
                if cpha_r = '0' then
                  rx_r <= rx_r(WIDTH - 2 downto 0) & miso;
                else
                  mosi_r <= tx_r(WIDTH - 1 - edge_cnt / 2);
                end if;
              else                                  -- second edge of a bit
                if cpha_r = '1' then
                  rx_r <= rx_r(WIDTH - 2 downto 0) & miso;
                elsif edge_cnt / 2 < WIDTH - 1 then
                  mosi_r <= tx_r(WIDTH - 2 - edge_cnt / 2);
                end if;
              end if;
              if edge_cnt = 2 * WIDTH - 1 then
                state <= S_HOLD;
              else
                edge_cnt <= edge_cnt + 1;
              end if;
            else
              cnt <= cnt + 1;
            end if;

          when S_HOLD =>
            if cnt = CLKS_PER_HALF - 1 then
              cnt       <= 0;
              cs_n_r    <= '1';
              mosi_r    <= '0';
              busy_r    <= '0';
              done_r    <= '1';
              rx_data_r <= rx_r;
              state     <= S_IDLE;
            else
              cnt <= cnt + 1;
            end if;
        end case;
      end if;
    end if;
  end process;
end architecture rtl;

-- uart_loop.vhd - a transmitter wired to a receiver, for end-to-end tests.
library ieee;
use ieee.std_logic_1164.all;

entity uart_loop is
  generic (
    CLKS_PER_BIT : positive := 16
  );
  port (
    clk      : in  std_logic;
    rst      : in  std_logic;
    tx_data  : in  std_logic_vector(7 downto 0);
    tx_valid : in  std_logic;
    tx_ready : out std_logic;
    rx_data  : out std_logic_vector(7 downto 0);
    rx_valid : out std_logic;
    rx_error : out std_logic
  );
end entity uart_loop;

architecture rtl of uart_loop is
  signal line : std_logic;
begin
  u_tx : entity work.uart_tx
    generic map (CLKS_PER_BIT => CLKS_PER_BIT)
    port map (clk => clk, rst => rst, tx_data => tx_data, tx_valid => tx_valid, tx_ready => tx_ready, txd => line);

  u_rx : entity work.uart_rx
    generic map (CLKS_PER_BIT => CLKS_PER_BIT)
    port map (clk => clk, rst => rst, rxd => line, rx_data => rx_data, rx_valid => rx_valid, rx_error => rx_error);
end architecture rtl;

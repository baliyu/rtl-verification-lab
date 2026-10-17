-- sync_2ff.vhd - two-flop synchroniser: brings a signal from another clock domain into this one (VHDL-93).
--
-- A signal that changes at an unrelated moment can be caught by a flop in the middle of its change (metastability). The first flop may
-- settle to either value; the second flop gives it a whole clock period to settle before anything uses it. Only a signal in which at most
-- ONE bit changes at a time (such as a Gray-coded counter) may be passed through this way: for a multi-bit change each bit settles
-- on its own, and the receiver can see a mixture of old and new bits that never existed.
-- Reset is synchronous and active high.
library ieee;
use ieee.std_logic_1164.all;

entity sync_2ff is
  generic (
    WIDTH : positive := 1
  );
  port (
    clk : in  std_logic;                                -- the receiving clock
    rst : in  std_logic;
    d   : in  std_logic_vector(WIDTH - 1 downto 0);     -- from the other clock domain
    q   : out std_logic_vector(WIDTH - 1 downto 0)
  );
end entity sync_2ff;

architecture rtl of sync_2ff is
  signal s1 : std_logic_vector(WIDTH - 1 downto 0) := (others => '0');
  signal s2 : std_logic_vector(WIDTH - 1 downto 0) := (others => '0');
begin
  q <= s2;

  process (clk)
  begin
    if rising_edge(clk) then
      if rst = '1' then
        s1 <= (others => '0');
        s2 <= (others => '0');
      else
        s1 <= d;
        s2 <= s1;
      end if;
    end if;
  end process;
end architecture rtl;

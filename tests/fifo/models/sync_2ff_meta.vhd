-- sync_2ff_meta.vhd - a deliberately nasty stand-in for sync_2ff, used only by the tests (never part of the design).
--
-- Same ports as sync_2ff. It models a bus whose wires are not equally fast. Each time the input changes, every bit that changed gets its own random
-- arrival time between 0 and WINDOW (a fixed-seed shift register, so every run is the same); until that time has passed, the receiving
-- flops still see that bit's OLD value, afterwards its NEW value, and it never goes back. Only the most recent change is tracked.
--
-- A Gray-coded pointer changes one bit at a time, so the receiver sees the old or the new pointer whatever the skew. A plain binary pointer
-- changes several bits at once (0111 -> 1000), so for a while the receiver can see a mixture that never existed; if the receiving clock is
-- faster than the window, that is several clocks in a row. This is the hazard that a zero-delay simulation cannot show.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity sync_2ff is
  generic (
    WIDTH : positive := 1
  );
  port (
    clk : in  std_logic;
    rst : in  std_logic;
    d   : in  std_logic_vector(WIDTH - 1 downto 0);
    q   : out std_logic_vector(WIDTH - 1 downto 0)
  );
end entity sync_2ff;

architecture meta of sync_2ff is
  constant WINDOW : time := 8 ns;
  type arrival_t is array (0 to WIDTH - 1) of time;
  signal s1 : std_logic_vector(WIDTH - 1 downto 0) := (others => '0');
  signal s2 : std_logic_vector(WIDTH - 1 downto 0) := (others => '0');
begin
  q <= s2;

  process (clk, d)
    variable d_old    : std_logic_vector(WIDTH - 1 downto 0) := (others => '0');   -- the input just before its latest change
    variable d_cur    : std_logic_vector(WIDTH - 1 downto 0) := (others => '0');
    variable arrive   : arrival_t := (others => 0 ns);                             -- per bit: how long after the latest change its new value reaches the flops
    variable t_change : time := 0 ns;                                              -- when the latest change happened
    variable lfsr     : std_logic_vector(15 downto 0) := x"ACE1";
  begin
    if d'event then
      d_old    := d_cur;
      d_cur    := d;
      t_change := now;
      for k in 0 to WIDTH - 1 loop
        lfsr      := lfsr(14 downto 0) & (lfsr(15) xor lfsr(13) xor lfsr(12) xor lfsr(10));
        arrive(k) := (WINDOW * to_integer(unsigned(lfsr(7 downto 0)))) / 256;
      end loop;
    end if;
    if rising_edge(clk) then
      if rst = '1' then
        s1 <= (others => '0');
        s2 <= (others => '0');
      else
        for i in 0 to WIDTH - 1 loop
          if d(i) /= d_old(i) and (now - t_change) < arrive(i) then                -- the new value has not reached us yet
            s1(i) <= d_old(i);
          else
            s1(i) <= d(i);
          end if;
        end loop;
        s2 <= s1;
      end if;
    end if;
  end process;
end architecture meta;

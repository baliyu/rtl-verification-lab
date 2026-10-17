-- async_fifo.vhd - asynchronous FIFO: a queue between a write clock and an unrelated read clock (VHDL-93).
--
-- The classic design with Gray-coded pointers (after Cummings, "Simulation and Synthesis Techniques for Asynchronous FIFO Design").
-- The memory holds 2**ADDR_WIDTH words. Each side keeps a binary pointer for addressing the memory and a Gray-coded copy of it that is
-- sent to the other clock domain through a two-flop synchroniser (sync_2ff). Only one bit of a Gray code changes at a time, so the
-- other side always sees either the old or the new pointer, never a mixture. Each side compares the other side's (old) pointer with
-- its own to decide its flag, so the flags are cautious: w_full can rise a little early and fall a little late, r_empty can fall a
-- little late, but a write is never accepted into a full FIFO and a read never returns data that is not there.
--
-- Write side (wclk): a word is stored on the clock edge where w_en is 1 and w_full is 0; w_en while w_full is 1 is ignored.
-- Read side (rclk): "first word fall through": while r_empty is 0, r_data already shows the oldest word. The word is removed on the
-- clock edge where r_en is 1 and r_empty is 0; r_en while r_empty is 1 is ignored.
-- Resets are synchronous and active high, one per clock domain. Assert BOTH together, for at least two cycles of the slower clock, and
-- do not read or write until both have been released.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity async_fifo is
  generic (
    DATA_WIDTH : positive := 8;
    ADDR_WIDTH : integer range 2 to 16 := 4          -- at least 2
  );
  port (
    wclk    : in  std_logic;
    wrst    : in  std_logic;
    w_en    : in  std_logic;
    w_data  : in  std_logic_vector(DATA_WIDTH - 1 downto 0);
    w_full  : out std_logic;
    rclk    : in  std_logic;
    rrst    : in  std_logic;
    r_en    : in  std_logic;
    r_data  : out std_logic_vector(DATA_WIDTH - 1 downto 0);
    r_empty : out std_logic
  );
end entity async_fifo;

architecture rtl of async_fifo is
  constant DEPTH : positive := 2 ** ADDR_WIDTH;
  type mem_t is array (0 to DEPTH - 1) of std_logic_vector(DATA_WIDTH - 1 downto 0);
  signal mem : mem_t := (others => (others => '0'));

  signal wbin       : unsigned(ADDR_WIDTH downto 0) := (others => '0');   -- write pointer, binary (addresses the memory)
  signal wptr       : unsigned(ADDR_WIDTH downto 0) := (others => '0');   -- the same, Gray-coded (crosses to the read clock)
  signal rbin       : unsigned(ADDR_WIDTH downto 0) := (others => '0');
  signal rptr       : unsigned(ADDR_WIDTH downto 0) := (others => '0');
  signal wq_rptr    : std_logic_vector(ADDR_WIDTH downto 0);              -- the read pointer, as seen by the write clock
  signal rq_wptr    : std_logic_vector(ADDR_WIDTH downto 0);              -- the write pointer, as seen by the read clock
  signal wfull_r    : std_logic := '0';
  signal rempty_r   : std_logic := '1';

  signal w_push     : std_logic;
  signal wbin_next  : unsigned(ADDR_WIDTH downto 0);
  signal wgray_next : unsigned(ADDR_WIDTH downto 0);
  signal full_next  : std_logic;
  signal r_pop      : std_logic;
  signal rbin_next  : unsigned(ADDR_WIDTH downto 0);
  signal rgray_next : unsigned(ADDR_WIDTH downto 0);
  signal empty_next : std_logic;
begin
  u_sync_r2w : entity work.sync_2ff
    generic map (WIDTH => ADDR_WIDTH + 1)
    port map (clk => wclk, rst => wrst, d => std_logic_vector(rptr), q => wq_rptr);

  u_sync_w2r : entity work.sync_2ff
    generic map (WIDTH => ADDR_WIDTH + 1)
    port map (clk => rclk, rst => rrst, d => std_logic_vector(wptr), q => rq_wptr);

  w_full  <= wfull_r;
  r_empty <= rempty_r;

  -- write side
  w_push     <= w_en and not wfull_r;
  wbin_next  <= wbin + 1 when w_push = '1' else wbin;
  wgray_next <= (wbin_next srl 1) xor wbin_next;
  full_next  <= '1' when std_logic_vector(wgray_next) = ((not wq_rptr(ADDR_WIDTH downto ADDR_WIDTH - 1)) & wq_rptr(ADDR_WIDTH - 2 downto 0)) else '0';

  process (wclk)
  begin
    if rising_edge(wclk) then
      if wrst = '1' then
        wbin     <= (others => '0');
        wptr     <= (others => '0');
        wfull_r  <= '0';
      else
        if w_push = '1' then
          mem(to_integer(wbin(ADDR_WIDTH - 1 downto 0))) <= w_data;
        end if;
        wbin     <= wbin_next;
        wptr     <= wgray_next;
        wfull_r  <= full_next;
      end if;
    end if;
  end process;

  -- read side
  r_pop      <= r_en and not rempty_r;
  rbin_next  <= rbin + 1 when r_pop = '1' else rbin;
  rgray_next <= (rbin_next srl 1) xor rbin_next;
  empty_next <= '1' when std_logic_vector(rgray_next) = rq_wptr else '0';

  r_data <= mem(to_integer(rbin(ADDR_WIDTH - 1 downto 0)));

  process (rclk)
  begin
    if rising_edge(rclk) then
      if rrst = '1' then
        rbin     <= (others => '0');
        rptr     <= (others => '0');
        rempty_r <= '1';
      else
        rbin     <= rbin_next;
        rptr     <= rgray_next;
        rempty_r <= empty_next;
      end if;
    end if;
  end process;
end architecture rtl;

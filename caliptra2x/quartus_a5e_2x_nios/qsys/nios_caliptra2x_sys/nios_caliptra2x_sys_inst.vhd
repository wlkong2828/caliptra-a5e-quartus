	component nios_caliptra2x_sys is
		port (
			caliptra_axi_waitrequest   : in  std_logic                     := 'X';             -- waitrequest
			caliptra_axi_readdata      : in  std_logic_vector(31 downto 0) := (others => 'X'); -- readdata
			caliptra_axi_readdatavalid : in  std_logic                     := 'X';             -- readdatavalid
			caliptra_axi_burstcount    : out std_logic_vector(0 downto 0);                     -- burstcount
			caliptra_axi_writedata     : out std_logic_vector(31 downto 0);                    -- writedata
			caliptra_axi_address       : out std_logic_vector(19 downto 0);                    -- address
			caliptra_axi_write         : out std_logic;                                        -- write
			caliptra_axi_read          : out std_logic;                                        -- read
			caliptra_axi_byteenable    : out std_logic_vector(3 downto 0);                     -- byteenable
			caliptra_axi_debugaccess   : out std_logic;                                        -- debugaccess
			clk_clk                    : in  std_logic                     := 'X';             -- clk
			reset_reset_n              : in  std_logic                     := 'X';             -- reset_n
			ctrl_pio_export            : out std_logic_vector(31 downto 0);                    -- export
			magic_pio_export           : out std_logic_vector(31 downto 0);                    -- export
			status_pio_export          : in  std_logic_vector(31 downto 0) := (others => 'X')  -- export
		);
	end component nios_caliptra2x_sys;

	u0 : component nios_caliptra2x_sys
		port map (
			caliptra_axi_waitrequest   => CONNECTED_TO_caliptra_axi_waitrequest,   -- caliptra_axi.waitrequest
			caliptra_axi_readdata      => CONNECTED_TO_caliptra_axi_readdata,      --             .readdata
			caliptra_axi_readdatavalid => CONNECTED_TO_caliptra_axi_readdatavalid, --             .readdatavalid
			caliptra_axi_burstcount    => CONNECTED_TO_caliptra_axi_burstcount,    --             .burstcount
			caliptra_axi_writedata     => CONNECTED_TO_caliptra_axi_writedata,     --             .writedata
			caliptra_axi_address       => CONNECTED_TO_caliptra_axi_address,       --             .address
			caliptra_axi_write         => CONNECTED_TO_caliptra_axi_write,         --             .write
			caliptra_axi_read          => CONNECTED_TO_caliptra_axi_read,          --             .read
			caliptra_axi_byteenable    => CONNECTED_TO_caliptra_axi_byteenable,    --             .byteenable
			caliptra_axi_debugaccess   => CONNECTED_TO_caliptra_axi_debugaccess,   --             .debugaccess
			clk_clk                    => CONNECTED_TO_clk_clk,                    --          clk.clk
			reset_reset_n              => CONNECTED_TO_reset_reset_n,              --        reset.reset_n
			ctrl_pio_export            => CONNECTED_TO_ctrl_pio_export,            --     ctrl_pio.export
			magic_pio_export           => CONNECTED_TO_magic_pio_export,           --    magic_pio.export
			status_pio_export          => CONNECTED_TO_status_pio_export           --   status_pio.export
		);


	nios_caliptra2x_sys u0 (
		.caliptra_axi_waitrequest   (_connected_to_caliptra_axi_waitrequest_),   //   input,   width = 1, caliptra_axi.waitrequest
		.caliptra_axi_readdata      (_connected_to_caliptra_axi_readdata_),      //   input,  width = 32,             .readdata
		.caliptra_axi_readdatavalid (_connected_to_caliptra_axi_readdatavalid_), //   input,   width = 1,             .readdatavalid
		.caliptra_axi_burstcount    (_connected_to_caliptra_axi_burstcount_),    //  output,   width = 1,             .burstcount
		.caliptra_axi_writedata     (_connected_to_caliptra_axi_writedata_),     //  output,  width = 32,             .writedata
		.caliptra_axi_address       (_connected_to_caliptra_axi_address_),       //  output,  width = 20,             .address
		.caliptra_axi_write         (_connected_to_caliptra_axi_write_),         //  output,   width = 1,             .write
		.caliptra_axi_read          (_connected_to_caliptra_axi_read_),          //  output,   width = 1,             .read
		.caliptra_axi_byteenable    (_connected_to_caliptra_axi_byteenable_),    //  output,   width = 4,             .byteenable
		.caliptra_axi_debugaccess   (_connected_to_caliptra_axi_debugaccess_),   //  output,   width = 1,             .debugaccess
		.clk_clk                    (_connected_to_clk_clk_),                    //   input,   width = 1,          clk.clk
		.reset_reset_n              (_connected_to_reset_reset_n_),              //   input,   width = 1,        reset.reset_n
		.ctrl_pio_export            (_connected_to_ctrl_pio_export_),            //  output,  width = 32,     ctrl_pio.export
		.magic_pio_export           (_connected_to_magic_pio_export_),           //  output,  width = 32,    magic_pio.export
		.status_pio_export          (_connected_to_status_pio_export_)           //   input,  width = 32,   status_pio.export
	);


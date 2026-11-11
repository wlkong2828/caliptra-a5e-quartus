module nios_caliptra2x_sys (
		input  wire        caliptra_axi_waitrequest,   // caliptra_axi.waitrequest
		input  wire [31:0] caliptra_axi_readdata,      //             .readdata
		input  wire        caliptra_axi_readdatavalid, //             .readdatavalid
		output wire [0:0]  caliptra_axi_burstcount,    //             .burstcount
		output wire [31:0] caliptra_axi_writedata,     //             .writedata
		output wire [19:0] caliptra_axi_address,       //             .address
		output wire        caliptra_axi_write,         //             .write
		output wire        caliptra_axi_read,          //             .read
		output wire [3:0]  caliptra_axi_byteenable,    //             .byteenable
		output wire        caliptra_axi_debugaccess,   //             .debugaccess
		input  wire        clk_clk,                    //          clk.clk
		input  wire        reset_reset_n,              //        reset.reset_n
		output wire [31:0] ctrl_pio_export,            //     ctrl_pio.export
		output wire [31:0] magic_pio_export,           //    magic_pio.export
		input  wire [31:0] status_pio_export           //   status_pio.export
	);
endmodule


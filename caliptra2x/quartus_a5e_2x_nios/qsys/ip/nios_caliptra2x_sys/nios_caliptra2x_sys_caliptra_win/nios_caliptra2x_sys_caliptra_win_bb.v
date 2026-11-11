module nios_caliptra2x_sys_caliptra_win #(
		parameter DATA_WIDTH               = 32,
		parameter SYMBOL_WIDTH             = 8,
		parameter HDL_ADDR_WIDTH           = 20,
		parameter BURSTCOUNT_WIDTH         = 1,
		parameter PIPELINE_COMMAND         = 1,
		parameter PIPELINE_RESPONSE        = 1,
		parameter SYNC_RESET               = 0,
		parameter USE_WRITERESPONSE        = 0,
		parameter S0_WAITREQUEST_ALLOWANCE = 0,
		parameter M0_WAITREQUEST_ALLOWANCE = 0
	) (
		input  wire                        clk,              //   clk.clk
		input  wire                        reset,            // reset.reset
		output wire                        s0_waitrequest,   //    s0.waitrequest,   Wait request to Avalon Memory Mapped Host, indicates agent is not ready
		output wire [DATA_WIDTH-1:0]       s0_readdata,      //      .readdata,      Read Data output from Avalon Memory Mapped Agent
		output wire                        s0_readdatavalid, //      .readdatavalid, Valid read data indication from Avalon Memory Mapped Agent
		input  wire [BURSTCOUNT_WIDTH-1:0] s0_burstcount,    //      .burstcount,    Indicates number of burst transfers in each burst
		input  wire [DATA_WIDTH-1:0]       s0_writedata,     //      .writedata,     Write Data from Avalon Memory Mapped Host
		input  wire [HDL_ADDR_WIDTH-1:0]   s0_address,       //      .address,       Address output from Avalon Memory Mapped Host
		input  wire                        s0_write,         //      .write,         Write command from Avalon Memory Mapped Host
		input  wire                        s0_read,          //      .read,          Read command from Avalon Memory Mapped Host
		input  wire [3:0]                  s0_byteenable,    //      .byteenable,    Indicates valid read/write data location
		input  wire                        s0_debugaccess,   //      .debugaccess
		input  wire                        m0_waitrequest,   //    m0.waitrequest,   Wait request from Avalon Memory Mapped Agent, indicates agent is not ready
		input  wire [DATA_WIDTH-1:0]       m0_readdata,      //      .readdata,      Read Data input to Avalon Memory Mapped Host
		input  wire                        m0_readdatavalid, //      .readdatavalid, Valid read data indication from Avalon Memory Mapped Agent
		output wire [BURSTCOUNT_WIDTH-1:0] m0_burstcount,    //      .burstcount,    Indicates number of burst transfers in each burst
		output wire [DATA_WIDTH-1:0]       m0_writedata,     //      .writedata,     Write Data from Avalon Memory Mapped Host
		output wire [HDL_ADDR_WIDTH-1:0]   m0_address,       //      .address,       Address output from Avalon Memory Mapped Host
		output wire                        m0_write,         //      .write,         Write command from Avalon Memory Mapped Host
		output wire                        m0_read,          //      .read,          Read command from Avalon Memory Mapped Host
		output wire [3:0]                  m0_byteenable,    //      .byteenable,    Indicates valid read/write data location
		output wire                        m0_debugaccess    //      .debugaccess
	);
endmodule


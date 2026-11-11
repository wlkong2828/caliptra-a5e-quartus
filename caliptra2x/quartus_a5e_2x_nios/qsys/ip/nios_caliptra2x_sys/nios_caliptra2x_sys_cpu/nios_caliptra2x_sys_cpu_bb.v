module nios_caliptra2x_sys_cpu (
		input  wire        clk,                          //                 clk.clk,           Clock Input
		input  wire        reset_reset,                  //               reset.reset,         Reset Input
		input  wire [15:0] platform_irq_rx_irq,          //     platform_irq_rx.irq,           Level-sensitive interrupt request lines.
		output wire [31:0] instruction_manager_awaddr,   // instruction_manager.awaddr,        Write Address Channel -- Write Address. This is unused.
		output wire [2:0]  instruction_manager_awprot,   //                    .awprot,        Write Address Channel -- Protection Type. This is unused.
		output wire        instruction_manager_awvalid,  //                    .awvalid,       Write Address Channel -- Write Address Valid. This is unused.
		input  wire        instruction_manager_awready,  //                    .awready,       Write Address Channel -- Write Address Ready. This is unused.
		output wire [31:0] instruction_manager_wdata,    //                    .wdata,         Write Data Channel -- Write Data. This is unused.
		output wire [3:0]  instruction_manager_wstrb,    //                    .wstrb,         Write Data Channel -- Write Strobes. This is unused.
		output wire        instruction_manager_wvalid,   //                    .wvalid,        Write Data Channel -- Write Valid. This is unused.
		input  wire        instruction_manager_wready,   //                    .wready,        Write Data Channel -- Write Ready. This is unused.
		input  wire [1:0]  instruction_manager_bresp,    //                    .bresp,         Write Response Channel -- Write Response. This is unused.
		input  wire        instruction_manager_bvalid,   //                    .bvalid,        Write Response Channel -- Write Response Valid. This is unused.
		output wire        instruction_manager_bready,   //                    .bready,        Write Response Channel -- Write Response Ready. This is unused.
		output wire [31:0] instruction_manager_araddr,   //                    .araddr,        Read Address Channel -- Read Address. Instruction address (program counter).
		output wire [2:0]  instruction_manager_arprot,   //                    .arprot,        Read Address Channel -- Protection Type. This is unused.
		output wire        instruction_manager_arvalid,  //                    .arvalid,       Read Address Channel -- Read Address Valid. Instruction address valid.
		input  wire        instruction_manager_arready,  //                    .arready,       Read Address Channel -- Read Address Ready. Instruction address ready (from memory).
		input  wire [31:0] instruction_manager_rdata,    //                    .rdata,         Read Data Channel -- Read Data. Instruction word.
		input  wire [1:0]  instruction_manager_rresp,    //                    .rresp,         Read Data Channel -- Read Response. Instruction response. A non-zero value indicates an instruction access fault exception.
		input  wire        instruction_manager_rvalid,   //                    .rvalid,        Read Data Channel -- Read Valid. Instruction valid.
		output wire        instruction_manager_rready,   //                    .rready,        Read Data Channel -- Read Ready. This is tied high since the core is always ready to receive an instruction.
		output wire [31:0] data_manager_awaddr,          //        data_manager.awaddr,        Write Address Channel -- Write Address. Store address.
		output wire [2:0]  data_manager_awprot,          //                    .awprot,        Write Address Channel -- Protection Type. This is unused.
		output wire        data_manager_awvalid,         //                    .awvalid,       Write Address Channel -- Write Address Valid. Store address valid.
		input  wire        data_manager_awready,         //                    .awready,       Write Address Channel -- Write Address Ready. Store address ready (from memory).
		output wire [31:0] data_manager_wdata,           //                    .wdata,         Write Data Channel -- Write Data. Store data.
		output wire [3:0]  data_manager_wstrb,           //                    .wstrb,         Write Data Channel -- Write Strobes. Byte position in word.
		output wire        data_manager_wvalid,          //                    .wvalid,        Write Data Channel -- Write Valid. Store data valid.
		input  wire        data_manager_wready,          //                    .wready,        Write Data Channel -- Write Ready. Store data ready (from memory).
		input  wire [1:0]  data_manager_bresp,           //                    .bresp,         Write Response Channel -- Write Response. Store response. A non-zero value indicates a store access fault exception.
		input  wire        data_manager_bvalid,          //                    .bvalid,        Write Response Channel -- Write Response Valid. Store response valid.
		output wire        data_manager_bready,          //                    .bready,        Write Response Channel -- Write Response Ready. This is tied high since the core is always ready to receive a store response.
		output wire [31:0] data_manager_araddr,          //                    .araddr,        Read Address Channel -- Read Address. Load address.
		output wire [2:0]  data_manager_arprot,          //                    .arprot,        Read Address Channel -- Protection Type. This is unused.
		output wire        data_manager_arvalid,         //                    .arvalid,       Read Address Channel -- Read Address Valid. Load address valid.
		input  wire        data_manager_arready,         //                    .arready,       Read Address Channel -- Read Address Ready. Load address ready (from agents).
		input  wire [31:0] data_manager_rdata,           //                    .rdata,         Read Data Channel -- Read Data. Load data.
		input  wire [1:0]  data_manager_rresp,           //                    .rresp,         Read Data Channel -- Read Response. Load response. A non-zero value indicates a load access fault exception.
		input  wire        data_manager_rvalid,          //                    .rvalid,        Read Data Channel -- Read Valid. Load data valid.
		output wire        data_manager_rready,          //                    .rready,        Read Data Channel -- Read Ready. This is tied high since the core is always ready to receive the load data.
		input  wire [5:0]  timer_sw_agent_address,       //      timer_sw_agent.address,       The address in the Timer and Software Interrupt Module that the core wants to write to or read from. This is relative to the Timer and Software Interrupt Module base address.
		input  wire [3:0]  timer_sw_agent_byteenable,    //                    .byteenable,    Store byte enable.
		input  wire        timer_sw_agent_read,          //                    .read,          Indicates if the core wants to load from "timer_sw_agent_address" in the Timer and Software Interrupt Module.
		output wire [31:0] timer_sw_agent_readdata,      //                    .readdata,      Load data from the Timer and Software Interrupt Module sent to the core.
		input  wire        timer_sw_agent_write,         //                    .write,         Indicates if the core wants to store to "timer_sw_agent_address" in the Timer and Software Interrupt Module.
		input  wire [31:0] timer_sw_agent_writedata,     //                    .writedata,     Store data to the Timer and Software Interrupt Module sent from the core.
		output wire        timer_sw_agent_waitrequest,   //                    .waitrequest,   Timer and Software Interrupt Module not ready to receive write or read request from the core.
		output wire        timer_sw_agent_readdatavalid, //                    .readdatavalid, Load data valid.
		input  wire [15:0] dm_agent_address,             //            dm_agent.address,       The address in the Debug Module that the core wants to write to or read from. This is relative to the Debug Module base address.
		input  wire        dm_agent_read,                //                    .read,          Indicates if the core wants to load from "dm_agent_address" in the Debug Module.
		output wire [31:0] dm_agent_readdata,            //                    .readdata,      Load data from the Debug Module sent to the core.
		input  wire        dm_agent_write,               //                    .write,         Indicates if the core wants to store to "dm_agent_address" in the Debug Module.
		input  wire [31:0] dm_agent_writedata,           //                    .writedata,     Store data to the Debug Module sent from the core.
		output wire        dm_agent_waitrequest,         //                    .waitrequest,   Debug Module not ready to receive write or read request from the core.
		output wire        dm_agent_readdatavalid        //                    .readdatavalid, Load data valid.
	);
endmodule


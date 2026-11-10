create_clock -name clk -period 20.000 [get_ports clk]
create_clock -name jtag_tck -period 100.000 [get_ports jtag_tck]
set_clock_groups -asynchronous -group {clk} -group {jtag_tck}

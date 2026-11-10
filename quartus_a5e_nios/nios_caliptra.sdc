create_clock -name clk -period 20.000 [get_ports clk]
create_clock -name altera_reserved_tck -period 40.000 [get_ports -nowarn altera_reserved_tck]
set_clock_groups -asynchronous -group {clk} -group {altera_reserved_tck}

# Board reset_n is asynchronous (push-button / POR). The Caliptra pins
# cptra_pwrgood and cptra_rst_b are 2FF-synchronized in nios_caliptra_top
# (u_sync_pwrgood, u_sync_rst_b): async assert, sync deassert to clk, per
# the Caliptra 1.x Integration Specification. False-path the raw board reset
# into the asynchronous pins of those synchronizers and into the Nios PD.
# The synchronizer *outputs* are registers timed to clk and must not be
# false-pathed onward into Caliptra.
set_false_path -from [get_ports reset_n]

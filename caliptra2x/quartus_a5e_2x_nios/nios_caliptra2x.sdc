# Nios V + Caliptra 2.x (nios_caliptra2x_top). Identical to quartus_a5e_nios/nios_caliptra.sdc (1.x):
# same 50 MHz clk, JTAG TCK, board reset and Reset Release false paths. Caliptra 2.x JTAG is tied off in the top.
create_clock -name clk -period 20.000 [get_ports clk]
create_clock -name altera_reserved_tck -period 40.000 [get_ports -nowarn altera_reserved_tck]
set_clock_groups -asynchronous -group {clk} -group {altera_reserved_tck}

# Board reset_n is asynchronous (push-button / POR). The Caliptra pins
# cptra_pwrgood and cptra_rst_b are 2FF-synchronized in nios_caliptra2x_top
# (u_sync_pwrgood, u_sync_rst_b): async assert, sync deassert to clk, per
# the Caliptra 2.x Integration Specification. False-path the raw board reset
# into the asynchronous pins of those synchronizers and into the Nios PD.
# The synchronizer *outputs* are registers timed to clk and must not be
# false-pathed onward into Caliptra.
set_false_path -from [get_ports reset_n]

# Reset Release IP (u_rst_release, Agilex 5 ninit_done): an SDM-driven, quasi-static
# signal that only falls once after configuration. It is combined with reset_n into
# sys_reset_n, which goes to async-assert / sync-deassert synchronizers (u_sync_glue,
# u_sync_pwrgood, u_sync_rst_b) and to the PD clock_source reset synchronizer.
set_false_path -from [get_keepers -nowarn {*u_rst_release*}]

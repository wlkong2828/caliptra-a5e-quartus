# Nios V/m host system for Caliptra 2.x (caliptra2x/rtl_2x/nios_caliptra2x_top.sv).
# Derived from quartus_a5e_nios/qsys/nios_caliptra_sys.tcl (Caliptra 1.1): identical clock source,
# Nios V/m CPU, 64 KiB on-chip RAM (onchip_mem.hex), JTAG UART, ctrl/status/magic PIOs, addresses and
# IRQ. Only difference: the Caliptra window is a 1 MiB (20-bit) mm_bridge exported as "caliptra_axi"
# (-> rtl_2x/avmm_to_axi.sv -> Caliptra 2.x AXI4 subordinate), instead of the 256 KiB "caliptra_apb".
# Regenerate (inside Quartus Pro 25.3 Docker; delete ip/ and the .qsys first or PD appends _0/_1 suffixes):
#   cd qsys && qsys-script --script=nios_caliptra2x_sys.tcl --quartus-project=none
#   then qsys-generate nios_caliptra2x_sys.qsys --synthesis=VERILOG --output-directory=nios_caliptra2x_sys --family="Agilex 5" --part=A5EC065BB32AE6S
package require -exact qsys 25.3
create_system nios_caliptra2x_sys
set_project_property DEVICE_FAMILY "Agilex 5"
set_project_property DEVICE A5EC065BB32AE6S

add_instance clk clock_source
set_instance_parameter_value clk clockFrequency 50000000.0
set_instance_parameter_value clk resetSynchronousEdges DEASSERT

add_instance cpu intel_niosv_m
set_instance_parameter_value cpu resetSlave "ram.s1"
set_instance_parameter_value cpu resetOffset 0
set_instance_parameter_value cpu enableDebug 1

add_instance ram intel_onchip_memory
set_instance_parameter_value ram memorySize 65536.0
set_instance_parameter_value ram dataWidth 32
set_instance_parameter_value ram initMemContent 1
set_instance_parameter_value ram useNonDefaultInitFile 1
set_instance_parameter_value ram initializationFileName "onchip_mem.hex"

add_instance jtag_uart altera_avalon_jtag_uart

add_instance ctrl_pio altera_avalon_pio
set_instance_parameter_value ctrl_pio direction Output
set_instance_parameter_value ctrl_pio width 32
set_instance_parameter_value ctrl_pio resetValue 0.0

add_instance status_pio altera_avalon_pio
set_instance_parameter_value status_pio direction Input
set_instance_parameter_value status_pio width 32

add_instance magic_pio altera_avalon_pio
set_instance_parameter_value magic_pio direction Output
set_instance_parameter_value magic_pio width 32
set_instance_parameter_value magic_pio resetValue 0.0

# 1 MiB window -> exported Avalon host "caliptra_axi" -> nios_caliptra2x_top window decode:
#   0x00000 soc_fw_store | 0x7F000 soc_fuse_ctrl2x | 0x80000 avmm_to_axi -> Caliptra 2.x AXI
add_instance caliptra_win altera_avalon_mm_bridge
set_instance_parameter_value caliptra_win DATA_WIDTH 32
set_instance_parameter_value caliptra_win ADDRESS_WIDTH 20
set_instance_parameter_value caliptra_win ADDRESS_UNITS SYMBOLS
set_instance_parameter_value caliptra_win MAX_BURST_SIZE 1
set_instance_parameter_value caliptra_win MAX_PENDING_RESPONSES 1
set_instance_parameter_value caliptra_win PIPELINE_COMMAND 1
set_instance_parameter_value caliptra_win PIPELINE_RESPONSE 1

# clocks / resets
foreach i {cpu ram jtag_uart ctrl_pio status_pio magic_pio caliptra_win} {
  foreach c [get_instance_interfaces $i] {
    set cls [get_instance_interface_property $i $c CLASS_NAME]
    if {[string equal $cls clock_sink]} { add_connection clk.clk $i.$c }
    if {[string equal $cls reset_sink]} { add_connection clk.clk_reset $i.$c }
  }
}

# data manager map (same as 1.x except caliptra_win: 1 MiB at 0x0010_0000, 1.x: 256 KiB at 0x0004_0000)
proc dm {slave base} {
  add_connection cpu.data_manager $slave
  set_connection_parameter_value cpu.data_manager/$slave baseAddress $base
}
dm ram.s1                          0x00000000
dm caliptra_win.s0                 0x00100000
dm jtag_uart.avalon_jtag_slave     0x00080000
dm ctrl_pio.s1                     0x00080010
dm status_pio.s1                   0x00080020
dm magic_pio.s1                    0x00080030
dm cpu.timer_sw_agent              0x00080040
dm cpu.dm_agent                    0x00090000
add_connection cpu.instruction_manager ram.s1
set_connection_parameter_value cpu.instruction_manager/ram.s1 baseAddress 0x00000000
add_connection cpu.instruction_manager cpu.dm_agent
set_connection_parameter_value cpu.instruction_manager/cpu.dm_agent baseAddress 0x00090000

add_connection cpu.platform_irq_rx jtag_uart.irq
set_connection_parameter_value cpu.platform_irq_rx/jtag_uart.irq irqNumber 0

# exports (port names match nios_caliptra2x_top.sv u_sys and the sim stand-in in sim_2x/tb_nios2x_top_fw.sv)
set_interface_property clk EXPORT_OF clk.clk_in
set_interface_property reset EXPORT_OF clk.clk_in_reset
set_interface_property caliptra_axi EXPORT_OF caliptra_win.m0
set_interface_property ctrl_pio EXPORT_OF ctrl_pio.external_connection
set_interface_property status_pio EXPORT_OF status_pio.external_connection
set_interface_property magic_pio EXPORT_OF magic_pio.external_connection

save_system nios_caliptra2x_sys.qsys

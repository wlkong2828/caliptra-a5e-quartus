/*
 * system.h - SOPC Builder system and BSP software package information
 *
 * Machine generated for CPU 'cpu' in SOPC Builder design 'nios_caliptra2x_sys'
 *
 * Generated: Wed Nov 11 15:15:25 GMT 2026
 */

/*
 * DO NOT MODIFY THIS FILE
 *
 * Changing this file will have subtle consequences
 * which will almost certainly lead to a nonfunctioning
 * system. If you do modify this file, be aware that your
 * changes will be overwritten and lost when this file
 * is generated again.
 *
 * DO NOT MODIFY THIS FILE
 */

/*
 * License Agreement
 *
 * Copyright (c) 2008
 * Altera Corporation, San Jose, California, USA.
 * All rights reserved.
 *
 * Permission is hereby granted, free of charge, to any person obtaining a
 * copy of this software and associated documentation files (the "Software"),
 * to deal in the Software without restriction, including without limitation
 * the rights to use, copy, modify, merge, publish, distribute, sublicense,
 * and/or sell copies of the Software, and to permit persons to whom the
 * Software is furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
 * FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
 * DEALINGS IN THE SOFTWARE.
 *
 * This agreement shall be governed in all respects by the laws of the State
 * of California and by the laws of the United States of America.
 */

#ifndef __SYSTEM_H_
#define __SYSTEM_H_

/* Include definitions from linker script generator */
#include "linker.h"


/*
 * CPU configuration
 *
 */

#define ALT_CPU_ARCHITECTURE "intel_niosv_m"
#define ALT_CPU_CPU_FREQ 50000000u
#define ALT_CPU_DATA_ADDR_WIDTH 0x20
#define ALT_CPU_DCACHE_LINE_SIZE 0
#define ALT_CPU_DCACHE_LINE_SIZE_LOG2 0
#define ALT_CPU_DCACHE_SIZE 0
#define ALT_CPU_FREQ 50000000
#define ALT_CPU_HAS_CSR_SUPPORT 1
#define ALT_CPU_HAS_DEBUG_STUB
#define ALT_CPU_ICACHE_LINE_SIZE 0
#define ALT_CPU_ICACHE_LINE_SIZE_LOG2 0
#define ALT_CPU_ICACHE_SIZE 0
#define ALT_CPU_INST_ADDR_WIDTH 0x20
#define ALT_CPU_INT_MODE 0
#define ALT_CPU_MTIME_OFFSET 0x00080040
#define ALT_CPU_NAME "cpu"
#define ALT_CPU_NIOSV_CORE_VARIANT 1
#define ALT_CPU_NUM_GPR 32
#define ALT_CPU_RESET_ADDR 0x00000000
#define ALT_CPU_TICKS_PER_SEC NIOSV_INTERNAL_TIMER_TICKS_PER_SECOND
#define ALT_CPU_TIMER_DEVICE_TYPE 2


/*
 * CPU configuration (with legacy prefix - don't use these anymore)
 *
 */

#define ABBOTTSLAKE_CPU_FREQ 50000000u
#define ABBOTTSLAKE_DATA_ADDR_WIDTH 0x20
#define ABBOTTSLAKE_DCACHE_LINE_SIZE 0
#define ABBOTTSLAKE_DCACHE_LINE_SIZE_LOG2 0
#define ABBOTTSLAKE_DCACHE_SIZE 0
#define ABBOTTSLAKE_HAS_CSR_SUPPORT 1
#define ABBOTTSLAKE_HAS_DEBUG_STUB
#define ABBOTTSLAKE_ICACHE_LINE_SIZE 0
#define ABBOTTSLAKE_ICACHE_LINE_SIZE_LOG2 0
#define ABBOTTSLAKE_ICACHE_SIZE 0
#define ABBOTTSLAKE_INST_ADDR_WIDTH 0x20
#define ABBOTTSLAKE_INT_MODE 0
#define ABBOTTSLAKE_MTIME_OFFSET 0x00080040
#define ABBOTTSLAKE_NIOSV_CORE_VARIANT 1
#define ABBOTTSLAKE_NUM_GPR 32
#define ABBOTTSLAKE_RESET_ADDR 0x00000000
#define ABBOTTSLAKE_TICKS_PER_SEC NIOSV_INTERNAL_TIMER_TICKS_PER_SECOND
#define ABBOTTSLAKE_TIMER_DEVICE_TYPE 2


/*
 * Define for each module class mastered by the CPU
 *
 */

#define __ALTERA_AVALON_JTAG_UART
#define __ALTERA_AVALON_MM_BRIDGE
#define __ALTERA_AVALON_PIO
#define __INTEL_NIOSV_M
#define __INTEL_ONCHIP_MEMORY


/*
 * System configuration
 *
 */

#define ALT_DEVICE_FAMILY "AGILEX5"
#define ALT_ENHANCED_INTERRUPT_API_PRESENT
#define ALT_IRQ_BASE NULL
#define ALT_LOG_PORT "/dev/null"
#define ALT_LOG_PORT_BASE 0x0
#define ALT_LOG_PORT_DEV null
#define ALT_LOG_PORT_TYPE ""
#define ALT_NUM_EXTERNAL_INTERRUPT_CONTROLLERS 0
#define ALT_NUM_INTERNAL_INTERRUPT_CONTROLLERS 1
#define ALT_NUM_INTERRUPT_CONTROLLERS 1
#define ALT_STDERR "/dev/jtag_uart"
#define ALT_STDERR_BASE 0x80000
#define ALT_STDERR_DEV jtag_uart
#define ALT_STDERR_IS_JTAG_UART
#define ALT_STDERR_PRESENT
#define ALT_STDERR_TYPE "altera_avalon_jtag_uart"
#define ALT_STDIN "/dev/jtag_uart"
#define ALT_STDIN_BASE 0x80000
#define ALT_STDIN_DEV jtag_uart
#define ALT_STDIN_IS_JTAG_UART
#define ALT_STDIN_PRESENT
#define ALT_STDIN_TYPE "altera_avalon_jtag_uart"
#define ALT_STDOUT "/dev/jtag_uart"
#define ALT_STDOUT_BASE 0x80000
#define ALT_STDOUT_DEV jtag_uart
#define ALT_STDOUT_IS_JTAG_UART
#define ALT_STDOUT_PRESENT
#define ALT_STDOUT_TYPE "altera_avalon_jtag_uart"
#define ALT_SYSTEM_NAME "nios_caliptra2x_sys"
#define ALT_SYS_CLK_TICKS_PER_SEC ALT_CPU_TICKS_PER_SEC
#define ALT_TIMESTAMP_CLK_TIMER_DEVICE_TYPE ALT_CPU_TIMER_DEVICE_TYPE


/*
 * caliptra_win configuration
 *
 */

#define ALT_MODULE_CLASS_caliptra_win altera_avalon_mm_bridge
#define CALIPTRA_WIN_BASE 0x100000
#define CALIPTRA_WIN_IRQ -1
#define CALIPTRA_WIN_IRQ_INTERRUPT_CONTROLLER_ID -1
#define CALIPTRA_WIN_NAME "/dev/caliptra_win"
#define CALIPTRA_WIN_SPAN 1048576
#define CALIPTRA_WIN_TYPE "altera_avalon_mm_bridge"


/*
 * cpu_dm_agent configuration
 *
 */

#define ALT_MODULE_CLASS_cpu_dm_agent intel_niosv_m
#define CPU_DM_AGENT_BASE 0x90000
#define CPU_DM_AGENT_CPU_FREQ 50000000u
#define CPU_DM_AGENT_DATA_ADDR_WIDTH 0x20
#define CPU_DM_AGENT_DCACHE_LINE_SIZE 0
#define CPU_DM_AGENT_DCACHE_LINE_SIZE_LOG2 0
#define CPU_DM_AGENT_DCACHE_SIZE 0
#define CPU_DM_AGENT_HAS_CSR_SUPPORT 1
#define CPU_DM_AGENT_HAS_DEBUG_STUB
#define CPU_DM_AGENT_ICACHE_LINE_SIZE 0
#define CPU_DM_AGENT_ICACHE_LINE_SIZE_LOG2 0
#define CPU_DM_AGENT_ICACHE_SIZE 0
#define CPU_DM_AGENT_INST_ADDR_WIDTH 0x20
#define CPU_DM_AGENT_INT_MODE 0
#define CPU_DM_AGENT_IRQ -1
#define CPU_DM_AGENT_IRQ_INTERRUPT_CONTROLLER_ID -1
#define CPU_DM_AGENT_MTIME_OFFSET 0x00080040
#define CPU_DM_AGENT_NAME "/dev/cpu_dm_agent"
#define CPU_DM_AGENT_NIOSV_CORE_VARIANT 1
#define CPU_DM_AGENT_NUM_GPR 32
#define CPU_DM_AGENT_RESET_ADDR 0x00000000
#define CPU_DM_AGENT_SPAN 65536
#define CPU_DM_AGENT_TICKS_PER_SEC NIOSV_INTERNAL_TIMER_TICKS_PER_SECOND
#define CPU_DM_AGENT_TIMER_DEVICE_TYPE 2
#define CPU_DM_AGENT_TYPE "intel_niosv_m"


/*
 * cpu_timer_sw_agent configuration
 *
 */

#define ALT_MODULE_CLASS_cpu_timer_sw_agent intel_niosv_m
#define CPU_TIMER_SW_AGENT_BASE 0x80040
#define CPU_TIMER_SW_AGENT_CPU_FREQ 50000000u
#define CPU_TIMER_SW_AGENT_DATA_ADDR_WIDTH 0x20
#define CPU_TIMER_SW_AGENT_DCACHE_LINE_SIZE 0
#define CPU_TIMER_SW_AGENT_DCACHE_LINE_SIZE_LOG2 0
#define CPU_TIMER_SW_AGENT_DCACHE_SIZE 0
#define CPU_TIMER_SW_AGENT_HAS_CSR_SUPPORT 1
#define CPU_TIMER_SW_AGENT_HAS_DEBUG_STUB
#define CPU_TIMER_SW_AGENT_ICACHE_LINE_SIZE 0
#define CPU_TIMER_SW_AGENT_ICACHE_LINE_SIZE_LOG2 0
#define CPU_TIMER_SW_AGENT_ICACHE_SIZE 0
#define CPU_TIMER_SW_AGENT_INST_ADDR_WIDTH 0x20
#define CPU_TIMER_SW_AGENT_INT_MODE 0
#define CPU_TIMER_SW_AGENT_IRQ -1
#define CPU_TIMER_SW_AGENT_IRQ_INTERRUPT_CONTROLLER_ID -1
#define CPU_TIMER_SW_AGENT_MTIME_OFFSET 0x00080040
#define CPU_TIMER_SW_AGENT_NAME "/dev/cpu_timer_sw_agent"
#define CPU_TIMER_SW_AGENT_NIOSV_CORE_VARIANT 1
#define CPU_TIMER_SW_AGENT_NUM_GPR 32
#define CPU_TIMER_SW_AGENT_RESET_ADDR 0x00000000
#define CPU_TIMER_SW_AGENT_SPAN 64
#define CPU_TIMER_SW_AGENT_TICKS_PER_SEC NIOSV_INTERNAL_TIMER_TICKS_PER_SECOND
#define CPU_TIMER_SW_AGENT_TIMER_DEVICE_TYPE 2
#define CPU_TIMER_SW_AGENT_TYPE "intel_niosv_m"


/*
 * ctrl_pio configuration
 *
 */

#define ALT_MODULE_CLASS_ctrl_pio altera_avalon_pio
#define CTRL_PIO_BASE 0x80010
#define CTRL_PIO_BIT_CLEARING_EDGE_REGISTER 0
#define CTRL_PIO_BIT_MODIFYING_OUTPUT_REGISTER 0
#define CTRL_PIO_CAPTURE 0
#define CTRL_PIO_DATA_WIDTH 32
#define CTRL_PIO_DO_TEST_BENCH_WIRING 0
#define CTRL_PIO_DRIVEN_SIM_VALUE 0
#define CTRL_PIO_EDGE_TYPE "NONE"
#define CTRL_PIO_FREQ 50000000
#define CTRL_PIO_HAS_IN 0
#define CTRL_PIO_HAS_OUT 1
#define CTRL_PIO_HAS_TRI 0
#define CTRL_PIO_IRQ -1
#define CTRL_PIO_IRQ_INTERRUPT_CONTROLLER_ID -1
#define CTRL_PIO_IRQ_TYPE "NONE"
#define CTRL_PIO_NAME "/dev/ctrl_pio"
#define CTRL_PIO_RESET_VALUE 0
#define CTRL_PIO_SPAN 16
#define CTRL_PIO_TYPE "altera_avalon_pio"


/*
 * hal2 configuration
 *
 */

#define ALT_MAX_FD 32
#define ALT_SYS_CLK CPU
#define ALT_TIMESTAMP_CLK CPU
#define INTEL_FPGA_DFL_START_ADDRESS 0xffffffffffffffff
#define INTEL_FPGA_USE_DFL_WALKER 0


/*
 * intel_niosv_m_hal_driver configuration
 *
 */

#define NIOSV_INTERNAL_TIMER_TICKS_PER_SECOND 1000


/*
 * jtag_uart configuration
 *
 */

#define ALT_MODULE_CLASS_jtag_uart altera_avalon_jtag_uart
#define JTAG_UART_BASE 0x80000
#define JTAG_UART_IRQ 0
#define JTAG_UART_IRQ_INTERRUPT_CONTROLLER_ID 0
#define JTAG_UART_NAME "/dev/jtag_uart"
#define JTAG_UART_READ_DEPTH 64
#define JTAG_UART_READ_THRESHOLD 8
#define JTAG_UART_SPAN 8
#define JTAG_UART_TYPE "altera_avalon_jtag_uart"
#define JTAG_UART_WRITE_DEPTH 64
#define JTAG_UART_WRITE_THRESHOLD 8


/*
 * magic_pio configuration
 *
 */

#define ALT_MODULE_CLASS_magic_pio altera_avalon_pio
#define MAGIC_PIO_BASE 0x80030
#define MAGIC_PIO_BIT_CLEARING_EDGE_REGISTER 0
#define MAGIC_PIO_BIT_MODIFYING_OUTPUT_REGISTER 0
#define MAGIC_PIO_CAPTURE 0
#define MAGIC_PIO_DATA_WIDTH 32
#define MAGIC_PIO_DO_TEST_BENCH_WIRING 0
#define MAGIC_PIO_DRIVEN_SIM_VALUE 0
#define MAGIC_PIO_EDGE_TYPE "NONE"
#define MAGIC_PIO_FREQ 50000000
#define MAGIC_PIO_HAS_IN 0
#define MAGIC_PIO_HAS_OUT 1
#define MAGIC_PIO_HAS_TRI 0
#define MAGIC_PIO_IRQ -1
#define MAGIC_PIO_IRQ_INTERRUPT_CONTROLLER_ID -1
#define MAGIC_PIO_IRQ_TYPE "NONE"
#define MAGIC_PIO_NAME "/dev/magic_pio"
#define MAGIC_PIO_RESET_VALUE 0
#define MAGIC_PIO_SPAN 16
#define MAGIC_PIO_TYPE "altera_avalon_pio"


/*
 * ram configuration
 *
 */

#define ALT_MODULE_CLASS_ram intel_onchip_memory
#define RAM_ALLOW_IN_SYSTEM_MEMORY_CONTENT_EDITOR 0
#define RAM_BASE 0x0
#define RAM_CONTENTS_INFO ""
#define RAM_DUAL_PORT 0
#define RAM_GUI_RAM_BLOCK_TYPE "AUTO"
#define RAM_INIT_CONTENTS_FILE "onchip_mem"
#define RAM_INIT_MEM_CONTENT 1
#define RAM_INSTANCE_ID "NONE"
#define RAM_IRQ -1
#define RAM_IRQ_INTERRUPT_CONTROLLER_ID -1
#define RAM_NAME "/dev/ram"
#define RAM_NON_DEFAULT_INIT_FILE_ENABLED 1
#define RAM_RAM_BLOCK_TYPE "AUTO"
#define RAM_READ_DURING_WRITE_MODE "DONT_CARE"
#define RAM_SINGLE_CLOCK_OP 0
#define RAM_SIZE_MULTIPLE 1
#define RAM_SIZE_VALUE 65536
#define RAM_SPAN 65536
#define RAM_TYPE "intel_onchip_memory"
#define RAM_WRITABLE 1


/*
 * status_pio configuration
 *
 */

#define ALT_MODULE_CLASS_status_pio altera_avalon_pio
#define STATUS_PIO_BASE 0x80020
#define STATUS_PIO_BIT_CLEARING_EDGE_REGISTER 0
#define STATUS_PIO_BIT_MODIFYING_OUTPUT_REGISTER 0
#define STATUS_PIO_CAPTURE 0
#define STATUS_PIO_DATA_WIDTH 32
#define STATUS_PIO_DO_TEST_BENCH_WIRING 0
#define STATUS_PIO_DRIVEN_SIM_VALUE 0
#define STATUS_PIO_EDGE_TYPE "NONE"
#define STATUS_PIO_FREQ 50000000
#define STATUS_PIO_HAS_IN 1
#define STATUS_PIO_HAS_OUT 0
#define STATUS_PIO_HAS_TRI 0
#define STATUS_PIO_IRQ -1
#define STATUS_PIO_IRQ_INTERRUPT_CONTROLLER_ID -1
#define STATUS_PIO_IRQ_TYPE "NONE"
#define STATUS_PIO_NAME "/dev/status_pio"
#define STATUS_PIO_RESET_VALUE 0
#define STATUS_PIO_SPAN 16
#define STATUS_PIO_TYPE "altera_avalon_pio"

#endif /* __SYSTEM_H_ */

cmake_minimum_required(VERSION 3.14)

add_subdirectory(../bsp bsp)

include(../bsp/toolchain.cmake)

project(caliptra_host)

enable_language(ASM)
enable_language(C)
enable_language(CXX)

add_executable(caliptra_host.elf)

target_sources(caliptra_host.elf
    PRIVATE
        main.c
)

target_include_directories(caliptra_host.elf
    PRIVATE
    PUBLIC
)

target_link_libraries(caliptra_host.elf
    PRIVATE
        -T "${BspLinkerScript}" -nostdlib
        "${ExtraArchiveLibraries}"
        -Wl,--start-group "${BspLibraryName}" -lc -lstdc++ -lgcc -lm -Wl,--end-group
)

# Create objdump from ELF.
set(objdump caliptra_host.elf.objdump)
add_custom_command(
    OUTPUT "${objdump}"
    DEPENDS caliptra_host.elf
    COMMAND "${ToolchainObjdump}" "${ToolchainObjdumpFlags}" caliptra_host.elf >
            "${objdump}"
    COMMENT "Creating ${objdump}."
    VERBATIM
)
add_custom_target(create-objdump ALL DEPENDS "${objdump}")

# Report space free for stack + heap. Note that the file below is never created
# so the report is always output on build.
set(stack_report_file caliptra_host.elf.stack_report)
add_custom_command(
    OUTPUT "${stack_report_file}"
    DEPENDS caliptra_host.elf
    COMMAND niosv-stack-report -p "${ToolchainPrefix}" caliptra_host.elf
    COMMENT "Reporting memory available for stack + heap in caliptra_host.elf."
    VERBATIM
)
add_custom_target(niosv-stack-report ALL DEPENDS "${stack_report_file}")

# Generate HEX file(s) from caliptra_host.elf using elf2hex tool.
# Note : If ECC Full is enabled, width of 39 is set for NiosV TCM. Otherwise, 32.
add_custom_command(
    OUTPUT "ram.hex"
    DEPENDS caliptra_host.elf
    COMMAND elf2hex caliptra_host.elf -o ram.hex -b 0x00000000 -w 32 -e 0x0000FFFF -r 4
    COMMENT "Creating ram.hex."
    VERBATIM
)
add_custom_target(create-hex ALL DEPENDS "ram.hex")

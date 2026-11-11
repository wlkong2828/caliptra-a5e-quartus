#!/bin/bash
# Prints extra Verilator C++ flags for the host compiler.
# Verilator --timing (used by the testbenches) needs C++20 coroutines.
# GCC 10-12 only enable them with -fcoroutines; GCC >= 13 and clang do not need it.
# Override with VERILATOR_CFLAGS="..." (set it to empty to pass nothing).
if [ -n "${VERILATOR_CFLAGS+x}" ]; then
  [ -n "$VERILATOR_CFLAGS" ] && printf -- '-CFLAGS %q ' $VERILATOR_CFLAGS
  exit 0
fi
cxx=${CXX:-c++}
defs=$("$cxx" -dM -E -x c++ /dev/null 2>/dev/null) || exit 0
if ! grep -q '__clang__' <<<"$defs"; then
  major=$(sed -n 's/^#define __GNUC__ \([0-9]*\).*/\1/p' <<<"$defs")
  if [ -n "$major" ] && [ "$major" -ge 10 ] && [ "$major" -lt 13 ]; then
    printf -- '-CFLAGS -fcoroutines '
  fi
fi

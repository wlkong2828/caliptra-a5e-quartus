#!/bin/bash
# Prints extra Verilator C++ flags for the host compiler.
# Verilator --timing (used by the testbenches) needs C++20 coroutines.
# GCC 10-12 only enable them with -fcoroutines; GCC >= 13 and clang do not need it.
# Override with VERILATOR_CFLAGS="..." (set it to empty to pass nothing).
#
# It also passes -MAKEFLAGS CFG_CXXFLAGS_PCH_I=-include (GCC only). Some site
# Verilator builds (seen on 5.040) were configured with an empty
# CFG_CXXFLAGS_PCH_I, so every object compile gets the precompiled header
# 'V..__pch.h.fast/.slow' as a bare argument and fails with "linker input file
# not found". Disable with VERILATOR_PCH_FIX=0.
cxx=${CXX:-c++}
defs=$("$cxx" -dM -E -x c++ /dev/null 2>/dev/null) || defs=""
if [ "${VERILATOR_PCH_FIX:-1}" = 1 ] && ! grep -q '__clang__' <<<"$defs"; then
  printf -- '-MAKEFLAGS CFG_CXXFLAGS_PCH_I=-include '
fi
# The same site builds also leave CFG_LDLIBS_THREADS empty, so --threads links
# fail with undefined pthread_create / pthread_setaffinity_np. Always link
# with -pthread (harmless where it is already present). Disable with
# VERILATOR_PTHREAD_FIX=0.
if [ "${VERILATOR_PTHREAD_FIX:-1}" = 1 ]; then
  printf -- '-CFLAGS -pthread -LDFLAGS -pthread -LDFLAGS -lpthread '
fi
if [ -n "${VERILATOR_CFLAGS+x}" ]; then
  [ -n "$VERILATOR_CFLAGS" ] && printf -- '-CFLAGS %q ' $VERILATOR_CFLAGS
  exit 0
fi
[ -n "$defs" ] || exit 0
if ! grep -q '__clang__' <<<"$defs"; then
  major=$(sed -n 's/^#define __GNUC__ \([0-9]*\).*/\1/p' <<<"$defs")
  if [ -n "$major" ] && [ "$major" -ge 10 ] && [ "$major" -lt 13 ]; then
    printf -- '-CFLAGS -fcoroutines '
  fi
fi

# Writes vdl2_version.h with the program version, at every build.
#
# Run with cmake -P, with SRC (the source tree), OUT (the header to write) and
# FALLBACK (the release version, used when there is no git checkout: a release
# tarball). The version is `git describe --tags --always --dirty`: "v1.0" on a
# tagged release, "v1.0-3-g4f31b44" three commits after it, with "-dirty" for
# uncommitted changes. The header is rewritten only when the version changes,
# so an unchanged version rebuilds nothing.

execute_process(
    COMMAND git -C "${SRC}" describe --tags --always --dirty
    OUTPUT_VARIABLE VER
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET
    RESULT_VARIABLE RC)
if(NOT RC EQUAL 0 OR VER STREQUAL "")
    set(VER "v${FALLBACK}")
endif()

set(CONTENT "/* vdl2_version.h -- generated at build time by cmake/version.cmake */\n#define VDL2_SNIFFER_VERSION \"${VER}\"\n")
if(EXISTS "${OUT}")
    file(READ "${OUT}" OLD)
else()
    set(OLD "")
endif()
if(NOT OLD STREQUAL CONTENT)
    file(WRITE "${OUT}" "${CONTENT}")
endif()

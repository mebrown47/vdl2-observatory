cmake_minimum_required(VERSION 3.16)
project(vdl2-sniffer VERSION 0.1 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

include(GNUInstallDirs)
find_package(Threads REQUIRED)
find_package(PkgConfig)

add_executable(vdl2-sniffer
    vdl2_sniffer.cc
    vdl2_xid.cc
    acars_position.c
    waypoint_db.c
    basestation.c
    web.cc
    third_party/vdl2/vdl2_decoder.cc
    third_party/vdl2/vdl2_rs.cc
    third_party/vdl2/vdl2_acars.cc)
target_include_directories(vdl2-sniffer PRIVATE ${CMAKE_CURRENT_SOURCE_DIR} ${CMAKE_CURRENT_BINARY_DIR})
# The live page's background map (data/build_outlines.py), built into the
# binary as a string so the page needs no file beside it.
file(READ ${CMAKE_CURRENT_SOURCE_DIR}/data/outlines.json VDL2_OUTLINES)
file(WRITE ${CMAKE_CURRENT_BINARY_DIR}/outlines.inc.tmp "R\"NEOUT(${VDL2_OUTLINES})NEOUT\"\n")
configure_file(${CMAKE_CURRENT_BINARY_DIR}/outlines.inc.tmp ${CMAKE_CURRENT_BINARY_DIR}/outlines.inc COPYONLY)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/data/outlines.json)
# Its fingerprint goes in the page's request for it (/map.json?v=...), so a
# browser holding an older copy fetches the new one.
file(MD5 ${CMAKE_CURRENT_SOURCE_DIR}/data/outlines.json VDL2_OUTLINES_MD5)
string(SUBSTRING ${VDL2_OUTLINES_MD5} 0 10 VDL2_MAP_VERSION)
# The fix list when vdl2-sniffer runs from the build tree; an installed
# binary finds its own copy in ../share/vdl2-sniffer first.
target_compile_definitions(vdl2-sniffer PRIVATE
    VDL2_DATA_DIR="${CMAKE_CURRENT_SOURCE_DIR}/data"
    VDL2_SNIFFER_VERSION="${PROJECT_VERSION}"
    VDL2_MAP_VERSION="${VDL2_MAP_VERSION}")
target_link_libraries(vdl2-sniffer PRIVATE Threads::Threads)

# libacars-2: multi-block reassembly and FANS-1/A, MIAM decoding (optional)
if(PkgConfig_FOUND)
    pkg_check_modules(LIBACARS IMPORTED_TARGET libacars-2)
endif()
if(LIBACARS_FOUND)
    target_compile_definitions(vdl2-sniffer PRIVATE JETSTREAM_LOADER_LIBACARS_AVAILABLE)
    target_link_libraries(vdl2-sniffer PRIVATE PkgConfig::LIBACARS)
    message(STATUS "libacars-2 ${LIBACARS_VERSION}: ACARS reassembly and decoding on")
else()
    message(STATUS "libacars-2 not found: ACARS blocks only, no reassembly or decoding")
endif()

# librtlsdr: read an RTL-SDR directly with --rtlsdr (optional)
if(PkgConfig_FOUND)
    pkg_check_modules(RTLSDR IMPORTED_TARGET librtlsdr)
endif()
if(RTLSDR_FOUND)
    target_compile_definitions(vdl2-sniffer PRIVATE HAVE_RTLSDR)
    target_link_libraries(vdl2-sniffer PRIVATE PkgConfig::RTLSDR)
    message(STATUS "librtlsdr ${RTLSDR_VERSION}: --rtlsdr on")
else()
    message(STATUS "librtlsdr not found: no --rtlsdr; pipe rtl_sdr into stdin instead")
endif()

# XID parser check against dumpvdl2's decode (tests/xid_check.py)
add_executable(vdl2-xid-test tests/xid_test.cc vdl2_xid.cc)
target_include_directories(vdl2-xid-test PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

# The filters give the same frames however the input is cut up (needs a capture)
add_executable(vdl2-block-test tests/block_test.cc
    third_party/vdl2/vdl2_decoder.cc third_party/vdl2/vdl2_rs.cc)
target_include_directories(vdl2-block-test PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

# Positions from ACARS text (tests/run_tests.sh)
add_executable(test-acars-position tests/test_acars_position.c acars_position.c waypoint_db.c)
target_include_directories(test-acars-position PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(test-acars-position PRIVATE m)

install(TARGETS vdl2-sniffer RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
install(FILES data/waypoints.csv DESTINATION ${CMAKE_INSTALL_DATADIR}/vdl2-sniffer)

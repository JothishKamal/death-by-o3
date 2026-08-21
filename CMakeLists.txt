cmake_minimum_required(VERSION 3.20)
# LANGUAGES C CXX is REQUIRED: LLVM's FindLibEdit.cmake calls check_include_file,
# which fails with "try_compile() works only for enabled languages" without C.
project(autopsy LANGUAGES C CXX)

find_package(LLVM REQUIRED CONFIG)
message(STATUS "Using LLVM ${LLVM_PACKAGE_VERSION} from ${LLVM_DIR}")
list(APPEND CMAKE_MODULE_PATH "${LLVM_CMAKE_DIR}")
include(AddLLVM)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_subdirectory(plugin)

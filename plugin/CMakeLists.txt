add_llvm_pass_plugin(AutopsyPlugin
  src/Plugin.cpp
)
target_include_directories(AutopsyPlugin PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)

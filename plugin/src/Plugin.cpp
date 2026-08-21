//===- Plugin.cpp - Optimization Autopsy capture plugin -------------------===//
// Licensed under the Apache License v2.0 with LLVM Exceptions.
//===----------------------------------------------------------------------===//
#include "llvm/Plugins/PassPlugin.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Support/Compiler.h"
#include "llvm/Support/raw_ostream.h"

using namespace llvm;

static void registerCallbacks(PassBuilder &PB) {
  auto *PIC = PB.getPassInstrumentationCallbacks();
  if (!PIC) {
    errs() << "autopsy-plugin: FATAL: no PassInstrumentationCallbacks\n";
    return;
  }
  errs() << "autopsy-plugin: registered\n";
}

extern "C" LLVM_ATTRIBUTE_WEAK ::llvm::PassPluginLibraryInfo
llvmGetPassPluginInfo() {
  return {LLVM_PLUGIN_API_VERSION, "autopsy-plugin", "0.1", registerCallbacks};
}

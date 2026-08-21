//===- Plugin.cpp - Optimization Autopsy capture plugin -------------------===//
// Licensed under the Apache License v2.0 with LLVM Exceptions.
//===----------------------------------------------------------------------===//
#include "autopsy/Record.h"
#include "autopsy/UnitId.h"
#include "llvm/IR/PassManager.h"
#include "llvm/Plugins/PassPlugin.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Support/Compiler.h"
#include "llvm/Support/raw_ostream.h"

using namespace llvm;

static autopsy::Recorder R;

static void registerCallbacks(PassBuilder &PB) {
  auto *PIC = PB.getPassInstrumentationCallbacks();
  if (!PIC) {
    errs() << "autopsy-plugin: FATAL: no PassInstrumentationCallbacks\n";
    return;
  }
  errs() << "autopsy-plugin: registered\n";

  PIC->registerShouldRunOptionalPassCallback(
      [](StringRef, Any) -> bool {
        R.SawShouldRun = true;
        return true;   // veto logic arrives in Plan 2
      });

  auto onBefore = [PIC](StringRef PassClass, Any IR, bool Skipped) {
    autopsy::UnitId U = autopsy::identify(IR);
    autopsy::Record Rec;
    Rec.seq = ++R.Seq;
    Rec.parent_seq = R.Stack.empty() ? -1 : (int)R.Stack.back().seq;
    Rec.depth = (unsigned)R.Stack.size();
    Rec.pass_class = PassClass.str();
    Rec.pass_name = PIC->getPassNameForClassName(PassClass).str();
    Rec.role = Rec.pass_name.empty() ? "scaffolding" : "transform";
    Rec.required = !R.SawShouldRun;
    R.SawShouldRun = false;
    Rec.kind = U.kind;
    Rec.unit_name = U.name;
    Rec.func = U.func;
    Rec.status = Skipped ? "skipped" : "ran";
    R.Stack.push_back(Rec);
  };

  auto emit = [](const autopsy::Record &Rec) {
    errs() << "REC seq=" << Rec.seq << " parent=" << Rec.parent_seq
           << " depth=" << Rec.depth << " class=" << Rec.pass_class
           << " pass=" << Rec.pass_name << " role=" << Rec.role
           << " kind=" << Rec.kind << " name=" << Rec.unit_name
           << " func=" << Rec.func << " status=" << Rec.status
           << " required=" << (Rec.required ? 1 : 0) << "\n";
  };

  PIC->registerBeforeNonSkippedPassCallback(
      [onBefore](StringRef C, Any IR) { onBefore(C, IR, false); });
  PIC->registerBeforeSkippedPassCallback(
      [onBefore](StringRef C, Any IR) { onBefore(C, IR, true); });

  PIC->registerAfterPassCallback(
      [emit](StringRef, Any, const PreservedAnalyses &) {
        if (R.Stack.empty()) return;
        autopsy::Record Rec = R.Stack.back();
        R.Stack.pop_back();
        emit(Rec);
      });

  PIC->registerAfterPassInvalidatedCallback(
      [emit](StringRef, const PreservedAnalyses &) {
        if (R.Stack.empty()) return;
        autopsy::Record Rec = R.Stack.back();
        R.Stack.pop_back();
        Rec.status = "invalidated";
        emit(Rec);
      });
}

extern "C" LLVM_ATTRIBUTE_WEAK ::llvm::PassPluginLibraryInfo
llvmGetPassPluginInfo() {
  return {LLVM_PLUGIN_API_VERSION, "autopsy-plugin", "0.1", registerCallbacks};
}

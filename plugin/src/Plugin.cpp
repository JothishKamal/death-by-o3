//===- Plugin.cpp - Optimization Autopsy capture plugin -------------------===//
// Licensed under the Apache License v2.0 with LLVM Exceptions.
//===----------------------------------------------------------------------===//
#include "autopsy/Address.h"
#include "autopsy/Cas.h"
#include "autopsy/Hash.h"
#include "autopsy/Json.h"
#include "autopsy/Record.h"
#include "autopsy/UnitId.h"
#include "llvm/IR/PassManager.h"
#include "llvm/Plugins/PassPlugin.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Support/Compiler.h"
#include "llvm/Support/FileSystem.h"
#include "llvm/Support/Format.h"
#include "llvm/Support/raw_ostream.h"

#include <algorithm>
#include <chrono>

using namespace llvm;

static autopsy::Recorder R;

namespace {
struct Flusher {
  ~Flusher() {
    if (!R.Out)
      return;
    // Records complete in pop (post) order; the contract is DFS pre-order,
    // i.e. seq order with parent_seq < seq. Sort before writing.
    std::sort(R.Done.begin(), R.Done.end(),
              [](const autopsy::Record &A, const autopsy::Record &B) {
                return A.seq < B.seq;
              });
    for (const auto &Rec : R.Done)
      autopsy::writeRecord(*R.Out, Rec);
    R.Out->flush();
  }
};
Flusher TheFlusher;
} // namespace

static uint64_t nowNs() {
  return (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>(
             std::chrono::steady_clock::now().time_since_epoch())
      .count();
}

static void registerCallbacks(PassBuilder &PB) {
  auto *PIC = PB.getPassInstrumentationCallbacks();
  if (!PIC) {
    errs() << "autopsy-plugin: FATAL: no PassInstrumentationCallbacks\n";
    return;
  }

  errs() << "autopsy-plugin: registered\n";

  if (const char *Path = getenv("AUTOPSY_OUT")) {
    std::error_code EC;
    R.Out = std::make_unique<raw_fd_ostream>(Path, EC, sys::fs::OF_Text);
    if (EC) {
      errs() << "autopsy-plugin: cannot open " << Path << ": " << EC.message()
             << "\n";
      R.Out.reset();
    }
  }

  if (const char *Dir = getenv("AUTOPSY_CAS"))
    R.CasDir = Dir;

  PIC->registerShouldRunOptionalPassCallback(
      [](StringRef, Any) -> bool {
        R.SawShouldRun = true;
        ++R.BisectCounter;
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
    Rec.occurrence = ++R.Occ[autopsy::occKey(PassClass, U)];
    Rec.bisect_index = Rec.required ? -1 : (int)R.BisectCounter;
    Rec.kind = U.kind;
    Rec.unit_name = U.name;
    Rec.func = U.func;
    Rec.status = Skipped ? "skipped" : "ran";
    if (!Skipped) {
      Rec.hash_before = autopsy::scopeHash(IR);
      Rec.attr_hash_before = autopsy::attrHash(IR);
      if (const Function *F = autopsy::metricTarget(IR)) {
        Rec.metrics_before = autopsy::measure(*F);
        Rec.has_metrics = true;
      }
    }
    Rec.wall_ns = nowNs();   // start stamp; converted to a duration below
    R.Stack.push_back(Rec);
  };

  auto finish = [](autopsy::Record Rec) { R.Done.push_back(std::move(Rec)); };

  PIC->registerBeforeNonSkippedPassCallback(
      [onBefore](StringRef C, Any IR) { onBefore(C, IR, false); });
  PIC->registerBeforeSkippedPassCallback(
      [onBefore](StringRef C, Any IR) { onBefore(C, IR, true); });

  PIC->registerAfterPassCallback(
      [finish](StringRef, Any IR, const PreservedAnalyses &) {
        if (R.Stack.empty()) return;
        autopsy::Record Rec = std::move(R.Stack.back());
        R.Stack.pop_back();
        if (Rec.status == "ran") {
          Rec.hash_after = autopsy::scopeHash(IR);
          Rec.attr_hash_after = autopsy::attrHash(IR);
          Rec.changed = (Rec.hash_before != Rec.hash_after) ||
                        (Rec.attr_hash_before != Rec.attr_hash_after);
          if (const Function *F = autopsy::metricTarget(IR))
            Rec.metrics_after = autopsy::measure(*F);
          if (Rec.changed && !R.CasDir.empty()) {
            if (const Function *F = autopsy::metricTarget(IR)) {
              Rec.blobs_after.push_back(autopsy::casStore(*F, R.CasDir));
            } else if (const auto **M = any_cast<const Module *>(&IR)) {
              for (const Function &Fn : **M)
                if (!Fn.isDeclaration())
                  Rec.blobs_after.push_back(autopsy::casStore(Fn, R.CasDir));
            } else if (const auto **C = any_cast<const LazyCallGraph::SCC *>(&IR)) {
              for (LazyCallGraph::Node &N : **C)
                Rec.blobs_after.push_back(
                    autopsy::casStore(N.getFunction(), R.CasDir));
            }
          }
        }
        Rec.wall_ns = nowNs() - Rec.wall_ns;
        finish(std::move(Rec));
      });

  PIC->registerAfterPassInvalidatedCallback(
      [finish](StringRef, const PreservedAnalyses &) {
        if (R.Stack.empty()) return;
        autopsy::Record Rec = std::move(R.Stack.back());
        R.Stack.pop_back();
        Rec.status = "invalidated";
        Rec.wall_ns = nowNs() - Rec.wall_ns;
        finish(std::move(Rec));
      });
}

extern "C" LLVM_ATTRIBUTE_WEAK ::llvm::PassPluginLibraryInfo
llvmGetPassPluginInfo() {
  return {LLVM_PLUGIN_API_VERSION, "autopsy-plugin", "0.1", registerCallbacks};
}

//===- UnitId.h - Identify the IR unit a pass ran on ----------------------===//
// Licensed under the Apache License v2.0 with LLVM Exceptions.
//
// NOTE: any_cast across the plugin/libLLVM dlopen boundary works because LLVM
// exports Any::TypeId<T>::Id as a GNU unique symbol ("u" in `nm -D`), so the
// plugin's instantiation and libLLVM's resolve to the same object.
//===----------------------------------------------------------------------===//
#ifndef AUTOPSY_UNITID_H
#define AUTOPSY_UNITID_H

#include "llvm/ADT/Any.h"
#include "llvm/Analysis/LazyCallGraph.h"
#include "llvm/Analysis/LoopInfo.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/Module.h"

#include <string>

namespace autopsy {

struct UnitId {
  std::string kind;  // module | function | scc | loop | unresolved
  std::string name;
  std::string func;  // enclosing function; empty for module and scc
};

inline UnitId identify(llvm::Any IR) {
  using namespace llvm;
  if (const auto **M = any_cast<const Module *>(&IR))
    return {"module", (*M)->getName().str(), ""};
  if (const auto **F = any_cast<const Function *>(&IR))
    return {"function", (*F)->getName().str(), (*F)->getName().str()};
  if (const auto **L = any_cast<const Loop *>(&IR)) {
    const Function *PF = (*L)->getHeader()->getParent();
    std::string N = (*L)->getName().str();
    if (N.empty())
      N = "<unnamed loop>";
    return {"loop", N, PF->getName().str()};
  }
  if (const auto **C = any_cast<const LazyCallGraph::SCC *>(&IR))
    return {"scc", (*C)->getName(), ""};
  return {"unresolved", "?", ""};
}

} // namespace autopsy

#endif // AUTOPSY_UNITID_H

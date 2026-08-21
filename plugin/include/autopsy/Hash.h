//===- Hash.h - Change oracle for a pass invocation ----------------------===//
// Licensed under the Apache License v2.0 with LLVM Exceptions.
//
// StructuralHash is the change oracle (PreservedAnalyses is not reliable), but
// it ignores attributes, so attributes are hashed separately.
//===----------------------------------------------------------------------===//
#ifndef AUTOPSY_HASH_H
#define AUTOPSY_HASH_H

#include "autopsy/UnitId.h"
#include "llvm/IR/StructuralHash.h"

#include <cstdint>
#include <string>

namespace autopsy {

inline uint64_t hashFunction(const llvm::Function &F) {
  return (uint64_t)llvm::StructuralHash(F, /*DetailedHash=*/true);
}

inline uint64_t scopeHash(llvm::Any IR) {
  using namespace llvm;
  if (const auto **M = any_cast<const Module *>(&IR))
    return (uint64_t)StructuralHash(**M, /*DetailedHash=*/true);
  if (const auto **F = any_cast<const Function *>(&IR))
    return hashFunction(**F);
  if (const auto **L = any_cast<const Loop *>(&IR))
    return hashFunction(*(*L)->getHeader()->getParent());
  if (const auto **C = any_cast<const LazyCallGraph::SCC *>(&IR)) {
    uint64_t H = 1469598103934665603ULL;   // FNV-1a offset basis
    for (LazyCallGraph::Node &N : **C)
      H = (H ^ hashFunction(N.getFunction())) * 1099511628211ULL;
    return H;
  }
  return 0;
}

/// Hash of attributes and linkage, which StructuralHash does not cover.
inline uint64_t attrHashOfFunction(const llvm::Function &F) {
  std::string S = F.getAttributes().getAsString(~0U);
  S += std::to_string((int)F.getLinkage());
  S += std::to_string((int)F.getVisibility());
  uint64_t H = 1469598103934665603ULL;
  for (unsigned char c : S)
    H = (H ^ c) * 1099511628211ULL;
  return H;
}

inline uint64_t attrHash(llvm::Any IR) {
  using namespace llvm;
  if (const auto **M = any_cast<const Module *>(&IR)) {
    uint64_t H = 1469598103934665603ULL;
    for (const Function &F : **M)
      H = (H ^ attrHashOfFunction(F)) * 1099511628211ULL;
    return H;
  }
  if (const auto **F = any_cast<const Function *>(&IR))
    return attrHashOfFunction(**F);
  if (const auto **L = any_cast<const Loop *>(&IR))
    return attrHashOfFunction(*(*L)->getHeader()->getParent());
  if (const auto **C = any_cast<const LazyCallGraph::SCC *>(&IR)) {
    uint64_t H = 1469598103934665603ULL;
    for (LazyCallGraph::Node &N : **C)
      H = (H ^ attrHashOfFunction(N.getFunction())) * 1099511628211ULL;
    return H;
  }
  return 0;
}

} // namespace autopsy

#endif // AUTOPSY_HASH_H

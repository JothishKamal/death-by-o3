//===- Metrics.h - Quantify an IR unit without touching the AM -----------===//
// Licensed under the Apache License v2.0 with LLVM Exceptions.
//
// DominatorTree and LoopInfo are constructed locally. Requesting analyses from
// the AnalysisManager inside an instrumentation callback can change pass
// behaviour; tests/test_metrics.py asserts the object file stays identical.
//===----------------------------------------------------------------------===//
#ifndef AUTOPSY_METRICS_H
#define AUTOPSY_METRICS_H

#include "llvm/Analysis/LoopInfo.h"
#include "llvm/IR/Dominators.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/Instructions.h"

#include <algorithm>
#include <cstdint>

namespace autopsy {

struct FnMetrics {
  unsigned instructions = 0, blocks = 0, loops = 0, max_loop_depth = 0;
  unsigned calls = 0, allocas = 0, vector_insts = 0;
  uint64_t ir_bytes = 0;
  unsigned c_mem = 0, c_arith = 0, c_float = 0, c_vector = 0;
  unsigned c_control = 0, c_call = 0, c_cast = 0, c_phi = 0, c_other = 0;
};

inline void classify(const llvm::Instruction &I, FnMetrics &M) {
  using namespace llvm;
  switch (I.getOpcode()) {
  case Instruction::Load: case Instruction::Store: case Instruction::Alloca:
  case Instruction::GetElementPtr: case Instruction::Fence:
  case Instruction::AtomicCmpXchg: case Instruction::AtomicRMW:
    ++M.c_mem; break;
  case Instruction::Add: case Instruction::Sub: case Instruction::Mul:
  case Instruction::UDiv: case Instruction::SDiv: case Instruction::URem:
  case Instruction::SRem: case Instruction::Shl: case Instruction::LShr:
  case Instruction::AShr: case Instruction::And: case Instruction::Or:
  case Instruction::Xor: case Instruction::ICmp:
    ++M.c_arith; break;
  case Instruction::FAdd: case Instruction::FSub: case Instruction::FMul:
  case Instruction::FDiv: case Instruction::FRem: case Instruction::FNeg:
  case Instruction::FCmp:
    ++M.c_float; break;
  case Instruction::ExtractElement: case Instruction::InsertElement:
  case Instruction::ShuffleVector:
    ++M.c_vector; break;
  case Instruction::Br: case Instruction::Switch: case Instruction::IndirectBr:
  case Instruction::Ret: case Instruction::Unreachable: case Instruction::Resume:
  case Instruction::Select: case Instruction::Invoke: case Instruction::CallBr:
    ++M.c_control; break;
  case Instruction::Call:
    ++M.c_call; break;
  case Instruction::Trunc: case Instruction::ZExt: case Instruction::SExt:
  case Instruction::FPToUI: case Instruction::FPToSI: case Instruction::UIToFP:
  case Instruction::SIToFP: case Instruction::FPTrunc: case Instruction::FPExt:
  case Instruction::PtrToInt: case Instruction::IntToPtr:
  case Instruction::BitCast: case Instruction::AddrSpaceCast:
    ++M.c_cast; break;
  case Instruction::PHI:
    ++M.c_phi; break;
  default:
    ++M.c_other; break;
  }
}

inline FnMetrics measure(const llvm::Function &F) {
  using namespace llvm;
  FnMetrics M;
  for (const BasicBlock &BB : F) {
    ++M.blocks;
    for (const Instruction &I : BB) {
      ++M.instructions;
      if (I.getType()->isVectorTy())
        ++M.vector_insts;
      if (I.getOpcode() == Instruction::Alloca)
        ++M.allocas;
      if (I.getOpcode() == Instruction::Call ||
          I.getOpcode() == Instruction::Invoke)
        ++M.calls;
      classify(I, M);
    }
  }
  if (!F.isDeclaration()) {
    DominatorTree DT(const_cast<Function &>(F));
    LoopInfo LI(DT);
    for (const Loop *L : LI.getLoopsInPreorder()) {
      ++M.loops;
      M.max_loop_depth = std::max(M.max_loop_depth, L->getLoopDepth());
    }
  }
  return M;
}

/// The function a record's metrics should describe: the unit itself for
/// function scope, the parent for loop scope, nothing for module or scc.
inline const llvm::Function *metricTarget(llvm::Any IR) {
  using namespace llvm;
  if (const auto **F = any_cast<const Function *>(&IR))
    return *F;
  if (const auto **L = any_cast<const Loop *>(&IR))
    return (*L)->getHeader()->getParent();
  return nullptr;
}

} // namespace autopsy

#endif // AUTOPSY_METRICS_H

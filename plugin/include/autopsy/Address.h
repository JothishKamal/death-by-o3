//===- Address.h - Stable, self-verifying decision addresses -------------===//
// Licensed under the Apache License v2.0 with LLVM Exceptions.
//===----------------------------------------------------------------------===//
#ifndef AUTOPSY_ADDRESS_H
#define AUTOPSY_ADDRESS_H

#include "autopsy/UnitId.h"
#include "llvm/ADT/StringRef.h"

#include <string>

namespace autopsy {

/// The occurrence-counter key. Scoped by pass class, unit kind, unit name and
/// enclosing function, so two loops in the same function never share a bucket.
inline std::string occKey(llvm::StringRef PassClass, const UnitId &U) {
  return PassClass.str() + "|" + U.kind + ":" + U.name + "|" + U.func;
}

} // namespace autopsy

#endif // AUTOPSY_ADDRESS_H

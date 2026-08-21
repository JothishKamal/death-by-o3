//===- Veto.h - Suppress exactly one pass invocation ---------------------===//
// Licensed under the Apache License v2.0 with LLVM Exceptions.
//===----------------------------------------------------------------------===//
#ifndef AUTOPSY_VETO_H
#define AUTOPSY_VETO_H

#include "autopsy/UnitId.h"
#include "llvm/ADT/StringRef.h"

#include <cstdint>
#include <cstdlib>
#include <string>
#include <vector>

namespace autopsy {

struct VetoSpec {
  std::string pass_class, kind, unit_name, func;
  unsigned occurrence = 0;
  uint64_t guard = 0;
  bool armed = false;
};

/// Parse "pass_class|kind|unit_name|func|occurrence|guard".
inline VetoSpec parseVeto(const char *S) {
  VetoSpec V;
  if (!S)
    return V;
  std::vector<std::string> Parts;
  std::string Cur;
  for (const char *P = S; *P; ++P) {
    if (*P == '|') { Parts.push_back(Cur); Cur.clear(); }
    else            { Cur += *P; }
  }
  Parts.push_back(Cur);
  if (Parts.size() != 6)
    return V;
  V.pass_class = Parts[0];
  V.kind       = Parts[1];
  V.unit_name  = Parts[2];
  V.func       = Parts[3];
  V.occurrence = (unsigned)strtoul(Parts[4].c_str(), nullptr, 10);
  V.guard      = strtoull(Parts[5].c_str(), nullptr, 16);
  V.armed      = true;
  return V;
}

inline bool matches(const VetoSpec &V, llvm::StringRef PassClass,
                    const UnitId &U, unsigned Occurrence) {
  return V.armed && V.pass_class == PassClass && V.kind == U.kind &&
         V.unit_name == U.name && V.func == U.func &&
         V.occurrence == Occurrence;
}

} // namespace autopsy

#endif // AUTOPSY_VETO_H

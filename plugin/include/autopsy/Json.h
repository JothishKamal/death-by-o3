//===- Json.h - Minimal JSONL serialisation for Records ------------------===//
// Licensed under the Apache License v2.0 with LLVM Exceptions.
//===----------------------------------------------------------------------===//
#ifndef AUTOPSY_JSON_H
#define AUTOPSY_JSON_H

#include "autopsy/Record.h"
#include "llvm/Support/raw_ostream.h"

#include <string>

namespace autopsy {

inline std::string jsonEscape(const std::string &S) {
  std::string O;
  O.reserve(S.size() + 8);
  for (char c : S) {
    switch (c) {
    case '"':  O += "\\\""; break;
    case '\\': O += "\\\\"; break;
    case '\n': O += "\\n";  break;
    case '\r': O += "\\r";  break;
    case '\t': O += "\\t";  break;
    default:
      if ((unsigned char)c < 0x20) {
        char buf[8];
        snprintf(buf, sizeof(buf), "\\u%04x", c);
        O += buf;
      } else {
        O += c;
      }
    }
  }
  return O;
}

inline std::string hex64(uint64_t V) {
  char buf[32];
  snprintf(buf, sizeof(buf), "0x%016llx", (unsigned long long)V);
  return buf;
}

inline void writeRecord(llvm::raw_ostream &OS, const Record &R) {
  OS << "{"
     << "\"seq\":" << R.seq
     << ",\"parent_seq\":" << R.parent_seq
     << ",\"depth\":" << R.depth
     << ",\"pass_class\":\"" << jsonEscape(R.pass_class) << "\""
     << ",\"pass_name\":\"" << jsonEscape(R.pass_name) << "\""
     << ",\"role\":\"" << R.role << "\""
     << ",\"kind\":\"" << R.kind << "\""
     << ",\"unit_name\":\"" << jsonEscape(R.unit_name) << "\""
     << ",\"func\":\"" << jsonEscape(R.func) << "\""
     << ",\"occurrence\":" << R.occurrence
     << ",\"required\":" << (R.required ? "true" : "false")
     << ",\"status\":\"" << R.status << "\""
     << ",\"changed\":" << (R.changed ? "true" : "false")
     << ",\"hash_before\":\"" << hex64(R.hash_before) << "\""
     << ",\"hash_after\":\"" << hex64(R.hash_after) << "\""
     << ",\"attr_hash_before\":\"" << hex64(R.attr_hash_before) << "\""
     << ",\"attr_hash_after\":\"" << hex64(R.attr_hash_after) << "\""
     << ",\"guard\":\"" << hex64(R.hash_before) << "\""
     << ",\"bisect_index\":" << R.bisect_index
     << ",\"wall_ns\":" << R.wall_ns
     << "}\n";
}

} // namespace autopsy

#endif // AUTOPSY_JSON_H

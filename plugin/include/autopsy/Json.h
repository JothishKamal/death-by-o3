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

inline void writeMetrics(llvm::raw_ostream &OS, const FnMetrics &M) {
  OS << "{\"instructions\":" << M.instructions
     << ",\"blocks\":" << M.blocks
     << ",\"loops\":" << M.loops
     << ",\"max_loop_depth\":" << M.max_loop_depth
     << ",\"calls\":" << M.calls
     << ",\"allocas\":" << M.allocas
     << ",\"vector_insts\":" << M.vector_insts
     << ",\"ir_bytes\":" << M.ir_bytes
     << ",\"by_class\":{"
     << "\"mem\":" << M.c_mem << ",\"arith\":" << M.c_arith
     << ",\"float\":" << M.c_float << ",\"vector\":" << M.c_vector
     << ",\"control\":" << M.c_control << ",\"call\":" << M.c_call
     << ",\"cast\":" << M.c_cast << ",\"phi\":" << M.c_phi
     << ",\"other\":" << M.c_other << "}}";
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
     << ",\"wall_ns\":" << R.wall_ns;
  OS << ",\"blobs_after\":[";
  for (size_t i = 0; i < R.blobs_after.size(); ++i) {
    if (i) OS << ",";
    OS << "\"" << R.blobs_after[i] << "\"";
  }
  OS << "]";
  if (R.has_metrics) {
    OS << ",\"metrics_before\":"; writeMetrics(OS, R.metrics_before);
    OS << ",\"metrics_after\":";  writeMetrics(OS, R.metrics_after);
  }
  OS << "}\n";
}

} // namespace autopsy

#endif // AUTOPSY_JSON_H

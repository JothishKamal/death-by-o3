//===- Record.h - One captured pass invocation ---------------------------===//
// Licensed under the Apache License v2.0 with LLVM Exceptions.
//===----------------------------------------------------------------------===//
#ifndef AUTOPSY_RECORD_H
#define AUTOPSY_RECORD_H

#include <cstdint>
#include <map>
#include <string>
#include <vector>

namespace autopsy {

struct Record {
  unsigned seq = 0;
  int parent_seq = -1;
  unsigned depth = 0;
  std::string pass_class;
  std::string pass_name;
  std::string role;       // transform | scaffolding
  std::string kind;
  std::string unit_name;
  std::string func;
  unsigned occurrence = 0;
  bool required = false;
  std::string status;     // ran | skipped | invalidated
  bool changed = false;
  uint64_t hash_before = 0;
  uint64_t hash_after = 0;
  uint64_t attr_hash_before = 0;
  uint64_t attr_hash_after = 0;
  uint64_t wall_ns = 0;
  int bisect_index = -1;   // -1 for Required passes: not gated, not vetoable
  std::vector<std::string> blobs_after;
};

struct Recorder {
  std::vector<Record> Stack;
  unsigned Seq = 0;
  bool SawShouldRun = false;
  std::map<std::string, unsigned> Occ;
  unsigned BisectCounter = 0;
};

} // namespace autopsy

#endif // AUTOPSY_RECORD_H

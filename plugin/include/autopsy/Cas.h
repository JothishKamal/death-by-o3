//===- Cas.h - Function-granular content-addressed IR store --------------===//
// Licensed under the Apache License v2.0 with LLVM Exceptions.
//===----------------------------------------------------------------------===//
#ifndef AUTOPSY_CAS_H
#define AUTOPSY_CAS_H

#include "llvm/IR/Function.h"
#include "llvm/Support/FileSystem.h"
#include "llvm/Support/Path.h"
#include "llvm/Support/SHA256.h"
#include "llvm/Support/raw_ostream.h"

#include <string>

namespace autopsy {

inline std::string sha256Hex(llvm::StringRef Data) {
  llvm::SHA256 H;
  H.update(Data);
  auto D = H.final();
  std::string Out;
  Out.reserve(64);
  static const char *Hex = "0123456789abcdef";
  for (uint8_t B : D) {
    Out += Hex[B >> 4];
    Out += Hex[B & 0xf];
  }
  return Out;
}

/// Serialise one function to text IR and store it under Dir, addressed by the
/// SHA-256 of its content. Returns the blob id. A blob that already exists is
/// not rewritten -- that is where the deduplication comes from.
inline std::string casStore(const llvm::Function &F, llvm::StringRef Dir) {
  std::string Body;
  llvm::raw_string_ostream OS(Body);
  F.print(OS);
  OS.flush();

  std::string Id = sha256Hex(Body);

  llvm::SmallString<256> Path(Dir);
  llvm::sys::path::append(Path, Id.substr(0, 2));
  if (auto EC = llvm::sys::fs::create_directories(Path))
    return Id;
  llvm::sys::path::append(Path, Id.substr(2));

  if (llvm::sys::fs::exists(Path))
    return Id;   // dedup hit

  std::error_code EC;
  llvm::raw_fd_ostream Out(Path, EC, llvm::sys::fs::OF_Text);
  if (!EC)
    Out << Body;
  return Id;
}

} // namespace autopsy

#endif // AUTOPSY_CAS_H

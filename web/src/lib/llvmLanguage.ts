import { StreamLanguage, type StreamParser } from '@codemirror/language'

// Keyword sets extracted from LLVM's own ll.tmLanguage.yaml, the grammar its
// VS Code extension ships. Shiki consumes the same source for its `llvm` lang.
const INSTRUCTIONS = [
  'add', 'addrspacecast', 'alloca', 'and', 'arcp', 'ashr', 'atomicrmw',
  'bitcast', 'br', 'call', 'callbr', 'catchpad', 'catchret', 'catchswitch',
  'cleanuppad', 'cleanupret', 'cmpxchg', 'eq', 'exact', 'extractelement',
  'extractvalue', 'fadd', 'fast', 'fcmp', 'fdiv', 'fence', 'fmul', 'fneg',
  'fpext', 'fptosi', 'fptoui', 'fptrunc', 'free', 'freeze', 'frem', 'fsub',
  'getelementptr', 'icmp', 'inbounds', 'indirectbr', 'insertelement',
  'insertvalue', 'inttoptr', 'invoke', 'landingpad', 'load', 'lshr', 'malloc',
  'max', 'min', 'mul', 'nand', 'ne', 'ninf', 'nnan', 'nsw', 'nsz', 'nuw',
  'oeq', 'oge', 'ogt', 'ole', 'olt', 'one', 'ord', 'phi', 'ptrtoint', 'resume',
  'ret', 'sdiv', 'select', 'sext', 'sge', 'sgt', 'shl', 'shufflevector',
  'sitofp', 'sle', 'slt', 'srem', 'store', 'sub', 'switch', 'trunc', 'udiv',
  'ueq', 'uge', 'ugt', 'uitofp', 'ule', 'ult', 'umax', 'umin', 'une', 'uno',
  'unreachable', 'unwind', 'urem', 'va_arg', 'xchg', 'xor', 'zext',
  'musttail', 'tail', 'define', 'declare', 'attributes',
]

const BASE_TYPES = [
  'void', 'half', 'bfloat', 'float', 'double', 'x86_fp80', 'fp128',
  'ppc_fp128', 'label', 'metadata', 'x86_mmx', 'x86_amx', 'type', 'opaque',
  'token',
]

export const llvmTokens = {
  keyword: new RegExp(`^(?:${INSTRUCTIONS.join('|')})$`),
  type: new RegExp(`^(?:${BASE_TYPES.join('|')}|i\\d+)$`),
  local: /^%[-$.\w]+$/,
  global: /^@[-$.\w]+$/,
  metadata: /^![-$.\w]+$/,
  label: /^[-$.\w]+:$/,
  comment: /^;.*$/,
}

const parser: StreamParser<unknown> = {
  token(stream) {
    if (stream.eatSpace()) return null
    if (stream.peek() === ';') { stream.skipToEnd(); return 'comment' }
    if (stream.peek() === '"') {
      stream.next()
      while (!stream.eol()) { if (stream.next() === '"') break }
      return 'string'
    }
    if (stream.match(/^%[-$.\w]+/)) return 'variableName'
    if (stream.match(/^@[-$.\w]+/)) return 'variableName.special'
    if (stream.match(/^![-$.\w]+/)) return 'meta'
    if (stream.match(/^[-$.\w]+:/)) return 'labelName'
    if (stream.match(/^-?\d+(\.\d+)?([eE][-+]?\d+)?/)) return 'number'
    const word = stream.match(/^[\w.]+/)
    if (word) {
      const text = String(word[0])
      if (llvmTokens.type.test(text)) return 'typeName'
      if (llvmTokens.keyword.test(text)) return 'keyword'
      return null
    }
    stream.next()
    return null
  },
}

export const llvmStreamLanguage = StreamLanguage.define(parser)

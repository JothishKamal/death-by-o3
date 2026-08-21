import { StreamLanguage } from '@codemirror/language'
import { describe, expect, it } from 'vitest'
import { llvmTokens } from './llvmLanguage'

describe('llvm token rules', () => {
  const rules = llvmTokens

  it('recognises instruction keywords', () => {
    expect(rules.keyword.test('getelementptr')).toBe(true)
    expect(rules.keyword.test('shufflevector')).toBe(true)
    expect(rules.keyword.test('notaninstruction')).toBe(false)
  })

  it('recognises base types and arbitrary integer widths', () => {
    expect(rules.type.test('double')).toBe(true)
    expect(rules.type.test('bfloat')).toBe(true)
    expect(rules.type.test('i37')).toBe(true)
  })

  it('recognises locals, globals and metadata', () => {
    expect(rules.local.test('%for.body3')).toBe(true)
    expect(rules.global.test('@kernel_gemm')).toBe(true)
    expect(rules.metadata.test('!dbg')).toBe(true)
  })

  it('recognises comments and labels', () => {
    expect(rules.comment.test('; this is a comment')).toBe(true)
    expect(rules.label.test('for.body:')).toBe(true)
  })

  it('covers modern LLVM keywords', () => {
    for (const kw of ['freeze', 'callbr', 'musttail']) {
      expect(rules.keyword.test(kw)).toBe(true)
    }
  })

  it('builds a StreamLanguage without throwing', () => {
    expect(() => StreamLanguage.define({ token: () => null })).not.toThrow()
  })
})

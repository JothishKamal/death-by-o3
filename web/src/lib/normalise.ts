// Mirrors autopsy.api.diff.normalise_ssa exactly. The backend computes diff
// character offsets against normalised text (%<n> -> %N, !<n> -> !N), so the
// docs handed to CodeMirror MUST be normalised too or offsets overrun the
// document ("Invalid position N in document of length M").
const UNNAMED_VALUE = /%(\d+)\b/g
const METADATA_ID = /!(\d+)\b/g

export function normaliseSsa(text: string): string {
  return text.replace(UNNAMED_VALUE, '%N').replace(METADATA_ID, '!N')
}

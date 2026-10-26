'use strict';
// Output comparison shared by the runner (verdict) and the results view (explaining a mismatch).
const crypto = require('crypto');

// Same leniency as the grader: ignore CRLF, trailing spaces per line, trailing blank lines.
function normLines(s) {
  const lines = s.replace(/\r\n?/g, '\n').split('\n').map((l) => l.replace(/[ \t]+$/, ''));
  while (lines.length && lines[lines.length - 1] === '') lines.pop();
  return lines;
}

const normalize = (s) => normLines(s).join('\n');

// -> null when equal, else { line, kind: 'missing'|'extra'|'differs', expected?, actual?, index?, spacingOnly? }
function firstDifference(expected, actual) {
  const e = normLines(expected);
  const a = normLines(actual);
  for (let i = 0; i < Math.max(e.length, a.length); i++) {
    if (e[i] === a[i]) continue;
    if (e[i] === undefined) return { line: i + 1, kind: 'extra', actual: a[i] };
    if (a[i] === undefined) return { line: i + 1, kind: 'missing', expected: e[i] };
    let index = 0;
    while (index < e[i].length && index < a[i].length && e[i][index] === a[i][index]) index++;
    if (/[\uD800-\uDBFF]/.test(e[i][index - 1])) index--; // the start of an emoji (two UTF-16 units), not its middle
    const collapse = (s) => s.replace(/\s+/g, ' ').trim();
    return {
      line: i + 1, kind: 'differs', expected: e[i], actual: a[i], index,
      spacingOnly: collapse(e[i]) === collapse(a[i]),
    };
  }
  return null;
}

// Make whitespace visible so "Hello  Python." vs "Hello Python." can be seen.
const visible = (s) => s.replace(/ /g, '·').replace(/\t/g, '→').replace(/\r/g, '␍');

// The part of a cut-off expected output that can be checked: its complete lines, and the start of the last line,
// which may be cut mid-way. The 2 KB cut can split a multi-byte character (Thai, ...), leaving one or more "�":
// those are dropped, then one more character, in case the cut left anything else half-written.
function shownPart(output) {
  const shown = normLines(output);
  const cut = (shown[shown.length - 1] || '').replace(/�+$/, '').slice(0, -1);
  return { complete: shown.slice(0, -1), cut };
}

// What of a cut-off expected output is checked, in words: "lines 1-36 and the start of line 37".
function checkedPart(output) {
  const { complete, cut } = shownPart(output);
  const n = complete.length;
  return [n > 1 ? `lines 1-${n}` : n ? 'line 1' : '', cut ? `the start of line ${n + 1}` : ''].filter(Boolean).join(' and ');
}

// What to compare for a test. When only the first part of the expected output is known (partialOutput),
// check the complete lines of that part against the same lines of the program's output, and the last visible
// line (which may be cut mid-way) as the start of the program's next line. -> { expected, actual, unchecked? }
// unchecked: nothing of the expected output is known, so any output would "match".
function comparedOutputs(tc, actual) {
  if (!tc.partialOutput) return { expected: tc.output, actual };
  const { complete, cut } = shownPart(tc.output);
  if (!complete.length && !cut) return { expected: '', actual: '', unchecked: true };
  const mine = normLines(actual);
  const expected = cut ? [...complete, cut] : complete;
  const got = mine.slice(0, complete.length);
  if (cut && mine.length > complete.length) got.push(mine[complete.length].slice(0, cut.length));
  return { expected: expected.join('\n'), actual: got.join('\n') };
}

// A fingerprint of a program's code, to tell whether a submission was this same code. Line endings, trailing
// spaces, blank lines at the end and a byte order mark don't count.
const codeHash = (source) => crypto.createHash('sha256').update(normalize(source.replace(/^﻿/, ''))).digest('hex');

module.exports = { normLines, normalize, firstDifference, visible, comparedOutputs, checkedPart, codeHash };

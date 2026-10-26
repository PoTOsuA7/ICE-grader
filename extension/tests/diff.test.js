'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { normalize, firstDifference, visible, comparedOutputs } = require('../lib/diff');

test('normalize ignores CRLF, trailing spaces and trailing blank lines', () => {
  assert.strictEqual(normalize('a  \r\nb\t\r\n\r\n\r\n'), 'a\nb');
  assert.strictEqual(normalize(''), '');
});

test('equal outputs have no difference', () => {
  assert.strictEqual(firstDifference('1\n2\n', '1\r\n2   \n\n'), null);
});

test('spacing inside a line matters and is flagged as spacing-only', () => {
  const d = firstDifference('Hello  Python.\nBye', 'Hello Python.\nBye');
  assert.strictEqual(d.kind, 'differs');
  assert.strictEqual(d.line, 1);
  assert.strictEqual(d.index, 6); // first char after "Hello "
  assert.strictEqual(d.spacingOnly, true);
});

test('real value difference is not spacing-only', () => {
  const d = firstDifference('12', '13');
  assert.strictEqual(d.index, 1);
  assert.strictEqual(d.spacingOnly, false);
});

test('missing and extra lines', () => {
  assert.deepStrictEqual(firstDifference('a\nb', 'a'), { line: 2, kind: 'missing', expected: 'b' });
  assert.deepStrictEqual(firstDifference('a', 'a\nb'), { line: 2, kind: 'extra', actual: 'b' });
});

test('an emoji is one column, and a cut-off line never keeps half an emoji (same as the Thonny plug-in)', () => {
  assert.strictEqual(firstDifference('\u{1F600}a', '\u{1F600}b').index, 1);
  // only the first emoji of the cut line is known: the program's "😀🤖" matches it
  assert.deepStrictEqual(comparedOutputs({ output: '\u{1F600}\u{1F600}', partialOutput: true }, '\u{1F600}\u{1F916}\n'),
    { expected: '\u{1F600}', actual: '\u{1F600}' });
});

test('visible marks spaces, tabs and carriage returns', () => {
  assert.strictEqual(visible('a b\tc\r'), 'a·b→c␍');
});

test('a form feed (os.system("cls")) or other control character is shown, and is no spacing mistake (same as Thonny)', () => {
  const d = firstDifference('3\n', '\f3\n');
  assert.strictEqual(d.spacingOnly, false);
  assert.strictEqual(visible('\f3\x00\x1b[0m\x07\b\x7f'), '␌3␀␛[0m␇␈␡');
  assert.strictEqual(firstDifference('a \t b', '  a b').spacingOnly, true);
  assert.strictEqual(firstDifference('a b', 'a b').spacingOnly, false);
});

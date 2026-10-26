'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { localResultsHtml, singleResultHtml, submissionHtml, explanationHtml, diffHtml } = require('../lib/resultsHtml');

test('user text is escaped in results', () => {
  const html = localResultsHtml({ code: 'P<1>' }, [{ input: '<script>alert(1)</script>', output: 'a&b' }],
    [{ verdict: 'FAIL', ms: 5, stdout: '<img src=x>', stderr: '<b>err</b>' }]);
  assert.ok(!html.includes('<script>alert') && !html.includes('<img src=x>') && !html.includes('<b>err'));
  assert.ok(html.includes('&lt;script&gt;') && html.includes('P&lt;1&gt;'));
});

test('a spacing mistake shows the marked character and the spacing hint', () => {
  const html = diffHtml('Hello  Python.', 'Hello Python.');
  assert.ok(html.includes('First difference: line 1, column 7'));
  assert.ok(html.includes('<mark>'));
  assert.ok(html.includes('Only the spacing differs'));
  assert.ok(html.includes('Hello·<mark>·</mark>Python.')); // expected line: the extra space is the marked char
  assert.ok(html.includes('Hello·<mark>P</mark>ython.')); // your line: "P" sits where the second space should be
});

test('after an emoji the marked column is still the right character', () => {
  const html = diffHtml('\u{1F600}ab', '\u{1F600}xb');
  assert.ok(html.includes('line 1, column 2'));
  assert.ok(html.includes('\u{1F600}<mark>a</mark>b') && html.includes('\u{1F600}<mark>x</mark>b'));
});

test('a grader tile is green only for a passed test: "Incorrect" is not correct, a missing letter is not a pass', () => {
  const tiles = (tests) => submissionHtml({ code: 'X' }, 5, { tests, status: 'done', done: true, points: 0, max: 100 })
    .match(/tile (ok|bad)/g).map((t) => t.slice(5));
  assert.deepStrictEqual(tiles([
    { n: 1, total: 4, label: 'Correct', letter: 'P' }, { n: 2, total: 4, label: 'Incorrect', letter: '-' },
    { n: 3, total: 4, label: 'Wrong answer', letter: '' }, { n: 4, total: 4, label: 'Correct', letter: '' },
  ]), ['ok', 'bad', 'bad', 'ok']);
});

test('single run reports PASS when output matches, FAIL otherwise', () => {
  assert.ok(singleResultHtml('t', 'in', 'ok', { verdict: 'OK', ms: 1, stdout: 'ok\n', stderr: '' }).includes('v PASS'));
  assert.ok(singleResultHtml('t', 'in', 'ok', { verdict: 'OK', ms: 1, stdout: 'no', stderr: '' }).includes('v FAIL'));
  assert.ok(singleResultHtml('custom', 'in', undefined, { verdict: 'OK', ms: 1, stdout: 'x', stderr: '' }).includes('v OK'));
});

test('submission view handles grading, done and timed-out states', () => {
  const p = { code: '05_List_11' };
  assert.ok(submissionHtml(p, 5, { tests: [], status: 'queued', done: false }).includes('Grading'));
  const done = submissionHtml(p, 5, { tests: [{ n: 1, total: 1, label: 'Correct', letter: 'P' }], status: 'done', done: true, points: 100, max: 100, runtime: '0.01 s' });
  assert.ok(done.includes('100 / 100 points') && done.includes('tile ok'));
  assert.ok(submissionHtml(p, 5, { tests: [], status: 'x', done: false, timedOut: true }).includes('Still grading'));
});

test('explanation view escapes the model text and renders code spans/fences safely', () => {
  const html = explanationHtml('Test 1 explained', null, 'Your `<script>` prints wrong.\n\n```\nx = 1\n```');
  assert.ok(!html.includes('<script>prints') && !html.includes('<script>alert'));
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(html.includes('<code>&lt;script&gt;</code>'));
  assert.ok(html.includes('<pre>x = 1</pre>'));
  assert.ok(html.includes('will not write the fix for you'));
});

test('explanation view shows the stale-file note when given one', () => {
  const html = explanationHtml('t', 'Note: edited since this ran.', 'text');
  assert.ok(html.includes('Note: edited since this ran.'));
});

test('a test the grader calls "Incorrect" gets a red tile, not a green one', () => {
  const tests = [{ n: 1, total: 2, label: 'Correct', letter: 'P' }, { n: 2, total: 2, label: 'Incorrect', letter: '-' }];
  const html = submissionHtml({ code: 'X' }, 5, { tests, done: true, points: 50, max: 100 });
  assert.match(html, /tile ok" title="Test 1: Correct"/);
  assert.match(html, /tile bad" title="Test 2: Incorrect"/);
});

test('a long stderr shows its end, where Python puts the error', () => {
  const stderr = `${Array.from({ length: 1000 }, (_, i) => `debug ${i}`).join('\n')}\nValueError: the real error\n`;
  const r = { verdict: 'RE', ms: 5, stdout: '', stderr };
  for (const html of [localResultsHtml({ code: 'X' }, [{ input: '1\n', output: '3\n' }], [r]), singleResultHtml('t', '1\n', '3\n', r)]) {
    assert.ok(html.includes('ValueError: the real error'));
    assert.ok(html.includes('<pre class="err">(truncated) ... ') && !html.includes('debug 0\n'));
  }
});

test('an invisible character in the output is shown, not called a spacing mistake', () => {
  // os.system("cls") with no console prints a form feed: the two lines looked the same, "only the spacing differs"
  const html = diffHtml('3', '\f3');
  assert.ok(html.includes('Yours <code><mark>␌</mark>3</code>'), html);
  assert.ok(!html.includes('Only the spacing differs'), html);
});

test('one huge line of output is cut to a readable length, with the difference still shown', () => {
  // sys.stdout.write("x" * 5_000_000): the runner keeps 1 MiB, which would make the difference box 260,000 px tall
  const huge = 'x'.repeat(1 << 20);
  const html = diffHtml('3', huge);
  assert.ok(html.length < 2000, `${html.length} characters`);
  assert.ok(html.includes(`<mark>x</mark>${'x'.repeat(299)} ... (${(1 << 20) - 300} more characters)`), html);
  const far = diffHtml(`${'a'.repeat(5000)}b${'z'.repeat(5000)}`, `${'a'.repeat(5000)}c${'z'.repeat(5000)}`);
  assert.ok(far.length < 2000 && far.includes('column 5001'), far);
  assert.ok(far.includes(`(4980 characters) ... ${'a'.repeat(20)}<mark>b</mark>`), far);
  assert.ok(far.includes(`${'a'.repeat(20)}<mark>c</mark>${'z'.repeat(279)} ... (4721 more characters)`), far);
  assert.ok(diffHtml('1', `1\n${'y'.repeat(1 << 20)}`).length < 2000, 'an extra line');
  assert.ok(diffHtml(`1\n${'y'.repeat(1 << 20)}`, '1').length < 2000, 'a missing line');
  const end = diffHtml(`${'q'.repeat(400)}1`, 'q'.repeat(400)); // the line ends where it differs
  assert.ok(end.includes(`(101 characters) ... ${'q'.repeat(299)}<mark>1</mark></code>`), end);
  assert.ok(end.includes(`(100 characters) ... ${'q'.repeat(300)}<mark>⏎</mark></code>`), end);
});

test('a difference inside an emoji marks the whole character, not half of it', () => {
  const html = diffHtml('A😀', 'A😁');
  assert.ok(html.includes('column 2'), html);
  assert.ok(html.includes('A<mark>😀</mark>') && html.includes('A<mark>😁</mark>'), html);
});

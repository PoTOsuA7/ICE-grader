'use strict';
// Reading test cases from the grader's test case page, which only shows the first part of each file.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { parseTestcasePage, GraderClient } = require('../lib/client');
const { comparedOutputs } = require('../lib/diff');
const { runTests, runSingle } = require('../lib/runner');
const { localResultsHtml } = require('../lib/resultsHtml');
const { havePython, tempDir } = require('./helpers');

// Same markup as the real page, with made-up data.
const file = (label, size, text) => `<div class='col-md-6'>
<div class='d-flex align-items-center justify-content-between flex-wrap gap-2 mb-1'>
<h6 class='mb-0'>${label}</h6>
<div class='d-flex align-items-center gap-2'>
<span class='text-secondary small'>${size}</span>
</div>
</div>
<textarea class='form-control font-monospace small' readonly rows='20' spellcheck='false'>${text}</textarea>
</div>`;
const pane = (id, input, output) => `<div class='tab-pane' id='tc${id}' role='tabpanel'>
<div class='row g-3'>
${file('Input', ...input)}
${file('Expected output', ...output)}
</div>
</div>`;
const pageHtml = (...panes) => `<span class='badge'>
<span class='mi md-18'>content_cut</span>
Showing the first 2 KB of each file
</span>
<div class='tab-content'>${panes.join('\n')}</div>`;

const big = 'x'.repeat(2048);

test('reads each test from the page, decoding HTML entities', () => {
  const cases = parseTestcasePage(pageHtml(
    pane(1, ['3 Bytes', 'toy'], ['5 Bytes', 'toys\n']),
    pane(2, ['5 Bytes', 'a &lt; b'], ['4 Bytes', 'yes\n'])));
  assert.deepStrictEqual(cases.map((c) => [c.id, c.input, c.output, c.inputCut, c.outputCut]),
    [['1', 'toy', 'toys\n', false, false], ['2', 'a < b', 'yes\n', false, false]]);
});

test('drops a newline the page adds after <textarea>, but only when the size proves it is extra', () => {
  const [c] = parseTestcasePage(pageHtml(pane(1, ['1 Byte', '\n5'], ['2 Bytes', '\n\n'])));
  assert.strictEqual(c.input, '5');
  assert.strictEqual(c.output, '\n\n');
});

test('flags a file that is bigger than what the page shows', () => {
  const [c] = parseTestcasePage(pageHtml(pane(1, ['50 KB', big], ['3 Bytes', 'ok\n'])));
  assert.strictEqual(c.inputCut, true);
  assert.strictEqual(c.outputCut, false);
});

// Fake grader: the test page, plus download links that either work or bounce to a normal page.
function fakeGrader(html, downloads) {
  const realFetch = globalThis.fetch;
  const asked = [];
  globalThis.fetch = async (url) => {
    const u = new URL(url);
    asked.push(u.pathname);
    if (u.pathname.startsWith('/testcases/show_problem/')) return new Response(html, { headers: { 'content-type': 'text/html' } });
    if (u.pathname === '/main/list') return new Response('<!DOCTYPE html><html>problem list</html>', { headers: { 'content-type': 'text/html' } });
    if (downloads) return new Response('full file\n', { headers: { 'content-type': 'text/plain' } });
    return new Response(null, { status: 302, headers: { location: '/main/list' } });
  };
  return { asked, restore: () => { globalThis.fetch = realFetch; } };
}

test('small tests come from the page without downloading anything', async () => {
  const g = fakeGrader(pageHtml(pane(7, ['3 Bytes', 'toy'], ['5 Bytes', 'toys\n'])), false);
  try {
    const cases = await new GraderClient('https://grader.test/').fetchTestcases(1);
    assert.deepStrictEqual(cases, [{ input: 'toy', output: 'toys\n' }]);
    assert.deepStrictEqual(g.asked, ['/testcases/show_problem/1']);
  } finally { g.restore(); }
});

test('the test download links the instructors turned off are never requested, even if they worked', async () => {
  const g = fakeGrader(pageHtml(pane(7, ['50 KB', big], ['50 KB', big])), true);
  try {
    const [c] = await new GraderClient('https://grader.test/').fetchTestcases(1);
    assert.deepStrictEqual(c, { input: big, output: big, partialInput: true, partialOutput: true });
    assert.deepStrictEqual(g.asked, ['/testcases/show_problem/1']);
  } finally { g.restore(); }
});

test('when downloads are blocked, a web page is never saved as a test; the visible part is kept and flagged', async () => {
  const g = fakeGrader(pageHtml(pane(7, ['3 Bytes', 'abc'], ['50 KB', big])), false);
  try {
    const [c] = await new GraderClient('https://grader.test/').fetchTestcases(1);
    assert.strictEqual(c.input, 'abc');
    assert.strictEqual(c.output, big);
    assert.strictEqual(c.partialOutput, true);
    assert.ok(!/DOCTYPE/.test(c.input + c.output));
  } finally { g.restore(); }
});

test('a partly known expected output is checked on its complete lines and the start of the cut line', () => {
  const tc = { output: 'a\nb\nc-cut-mid', partialOutput: true };
  // the cut line loses its last character (it may be half of a multi-byte character)
  assert.deepStrictEqual(comparedOutputs(tc, 'a\nb\nc-cut-middle\nd\n'), { expected: 'a\nb\nc-cut-mi', actual: 'a\nb\nc-cut-mi' });
  assert.deepStrictEqual(comparedOutputs(tc, 'a\nb\nc-full\nd\n'), { expected: 'a\nb\nc-cut-mi', actual: 'a\nb\nc-full' });
  assert.deepStrictEqual(comparedOutputs({ output: 'x\n' }, 'y\n'), { expected: 'x\n', actual: 'y\n' });
});

test('runner skips a test whose input is only partly known and checks partial outputs by prefix', async (t) => {
  const dir = tempDir('nattee-tc-');
  const f = path.join(dir, 'sol.py');
  fs.writeFileSync(f, 'for i in range(int(input())): print(i)');
  const cfg = { pythonPath: 'python', cppCompiler: 'g++', cCompiler: 'gcc', timeoutMs: 10000 };
  if (!(await havePython(t))) return;
  const cases = [
    { input: '5\n', output: '0\n1\n2\n3', partialOutput: true },
    { input: '5\n', output: '0\n9\n2\n3', partialOutput: true },
    { input: '99999', partialInput: true, output: '' },
  ];
  const results = await runTests(f, cases, cfg);
  assert.deepStrictEqual(results.map((r) => r.verdict), ['PASS', 'FAIL', 'SKIP']);
  const html = localResultsHtml({ code: 'X' }, cases, results);
  assert.match(html, /1\/2 passed/);
  assert.match(html, /1 skipped/);
  assert.match(html, /only shows the start of this test's input/);
});

// ---- data files ("Data files read at run time")
const { parseDataFiles } = require('../lib/client');
const { mapDataPaths } = require('../lib/runner');
const dataSection = (...files) => `<div class='card shadow-sm mb-4' id='data-files'>
<div class='card-body'>
<h5 class='fw-bold mb-1'>Data files read at run time</h5>
<div class='row g-3'>${files.map(([name, size, text]) => file(name, size, text)).join('\n')}</div></div></div>`;

test('data files are read from their own section and not mistaken for a test', () => {
  const html = pageHtml(pane(1, ['19 Bytes', '/data/data.txt 2562'], ['14 Bytes', '50.0 90.0 70.0'])) +
    dataSection(['data.txt', '31 Bytes', '6230012121 90.0\n6230215221 50.0'], ['empty.txt', '0 Bytes', '']);
  assert.deepStrictEqual(parseTestcasePage(html).map((c) => c.input), ['/data/data.txt 2562']);
  assert.deepStrictEqual(parseDataFiles(html).map((f) => [f.name, f.text, f.cut]),
    [['data.txt', '6230012121 90.0\n6230215221 50.0', false], ['empty.txt', '', false]]);
  assert.deepStrictEqual(parseDataFiles(pageHtml(pane(1, ['1 Byte', 'x'], ['1 Byte', 'y']))), []);
});

test('/data/ paths in the input are pointed at the local copies', () => {
  const files = { 'data1.txt': '', 'data2.txt': '' };
  assert.strictEqual(mapDataPaths('/data/data1.txt /data/data2.txt', files), 'data/data1.txt data/data2.txt');
  assert.strictEqual(mapDataPaths('/data/other.txt', files), '/data/other.txt');
  assert.strictEqual(mapDataPaths('/data/x', undefined), '/data/x');
});

test('a program that opens /data/... from its input runs against the data files', async (t) => {
  const dir = tempDir('nattee-df-');
  const f = path.join(dir, 'sol.py');
  fs.writeFileSync(f, 'a, b = input().split()\nprint(open(a).read().strip(), len(open(b).read()))');
  const cfg = { pythonPath: 'python', cppCompiler: 'g++', cCompiler: 'gcc', timeoutMs: 10000 };
  if (!(await havePython(t))) return;
  const files = { 'a.txt': 'hello', 'b.txt': '' };
  const cases = [{ input: '/data/a.txt /data/b.txt\n', output: 'hello 0\n', files }];
  assert.deepStrictEqual((await runTests(f, cases, cfg)).map((r) => r.verdict), ['PASS']);
  assert.strictEqual((await runSingle(f, '/data/a.txt /data/b.txt\n', cfg, files)).stdout.trim(), 'hello 0');
  assert.match(localResultsHtml({ code: 'X' }, cases, [{ verdict: 'PASS', ms: 1, stdout: '', stderr: '' }]), /Data files from the grader: a\.txt, b\.txt/);
});

test('fetchTestcases attaches the data files to every test', async () => {
  const html = pageHtml(pane(1, ['3 Bytes', 'abc'], ['1 Byte', 'x']), pane(2, ['3 Bytes', 'def'], ['1 Byte', 'y'])) +
    dataSection(['d.txt', '2 Bytes', 'hi']);
  const g = fakeGrader(html, false);
  try {
    const cases = await new GraderClient('https://grader.test/').fetchTestcases(1);
    assert.deepStrictEqual(cases.map((c) => c.files), [{ 'd.txt': 'hi' }, { 'd.txt': 'hi' }]);
  } finally { g.restore(); }
});

// ---- review fixes: cut-off single-line outputs, data file named "data", programs that leave a child running
const { comparedOutputs: cmpOut } = require('../lib/diff');

test('a cut-off output that is one long line is still checked (as a prefix), not passed blindly', () => {
  const tc = { output: '1 2 3 4 5 6 7 8 9 '.repeat(120), partialOutput: true };
  assert.notStrictEqual(cmpOut(tc, 'WRONG\n').expected, cmpOut(tc, 'WRONG\n').actual);
  const right = cmpOut(tc, '1 2 3 4 5 6 7 8 9 '.repeat(200) + '\n');
  assert.strictEqual(right.expected, right.actual);
  assert.ok(right.expected.length > 1000);
  assert.strictEqual(cmpOut({ output: 'x', partialOutput: true }, 'anything').unchecked, true);
  // complete lines plus a cut last line
  const two = { output: 'a\nbcd-cut', partialOutput: true };
  assert.strictEqual(cmpOut(two, 'a\nbcd-cut-and-more\n').expected, cmpOut(two, 'a\nbcd-cut-and-more\n').actual);
  assert.notStrictEqual(cmpOut(two, 'a\nzzz\n').expected, cmpOut(two, 'a\nzzz\n').actual);
});

const PY_CFG = { pythonPath: 'python', cppCompiler: 'g++', cCompiler: 'gcc', timeoutMs: 10000 };
async function pyFile(t, src) {
  const dir = tempDir('nattee-rv-');
  const f = path.join(dir, 'sol.py');
  fs.writeFileSync(f, src);
  if (!(await havePython(t))) return null;
  return f;
}
const sandboxes = () => fs.readdirSync(os.tmpdir()).filter((n) => n.startsWith('nattee-data-')).length;

test('runner: a long cut-off line is FAIL for a wrong program, PASS for a right one, SKIP when nothing is known', async (t) => {
  const f = await pyFile(t, 'print(input())');
  if (!f) return;
  const line = '7 '.repeat(1500);
  const cases = [
    { input: 'nope\n', output: line, partialOutput: true },
    { input: line + '\n', output: line, partialOutput: true },
    { input: 'x\n', output: 'q', partialOutput: true },
  ];
  const res = await runTests(f, cases, PY_CFG);
  assert.deepStrictEqual(res.map((r) => r.verdict), ['FAIL', 'PASS', 'SKIP']);
  assert.strictEqual(res[2].skipped, 'output');
  assert.match(localResultsHtml({ code: 'X' }, cases, res), /too little of this test&#39;s expected output|too little of this test's expected output/);
});

test('a data file named "data" works and leaves no temp folder behind', async (t) => {
  const f = await pyFile(t, 'print(open(input().strip()).read().strip())');
  if (!f) return;
  const before = sandboxes();
  const res = await runTests(f, [{ input: '/data/data\n', output: 'x\n', files: { data: 'x\n', '': 'ignored', '..': 'ignored' } }], PY_CFG);
  assert.deepStrictEqual(res.map((r) => r.verdict), ['PASS']);
  assert.strictEqual(sandboxes(), before);
});

test('a program that exits but leaves a child holding its output is not a TLE', async (t) => {
  const f = await pyFile(t, [
    'import subprocess, sys',
    "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(4)'])",
    'print(5)',
  ].join('\n'));
  if (!f) return;
  const started = Date.now();
  const res = await runTests(f, [{ input: '\n', output: '5\n', files: { 'x.txt': '1' } }], { ...PY_CFG, timeoutMs: 3000 });
  assert.deepStrictEqual(res.map((r) => r.verdict), ['PASS']);
  assert.ok(Date.now() - started < 2500, `took ${Date.now() - started} ms`);
});

// ---- cut-off expected outputs: what is checked, and tests that can't be checked here
const { checkedPart, codeHash, normalize } = require('../lib/diff');
const { lastSubmitOn } = require('../lib/runner');

test('a cut-off expected output: a split Thai character, CRLF and trailing spaces never fail a right answer', () => {
  const thai = 'สวัสดีครับ'; // each character is 3 bytes in UTF-8
  for (const rest of ['�', '��', '']) {
    const tc = { output: `1\n${thai.slice(0, 4)}${rest}`, partialOutput: true };
    const cmp = comparedOutputs(tc, `1\n${thai}\n2\n`);
    assert.strictEqual(cmp.expected, cmp.actual, JSON.stringify(rest));
    assert.notStrictEqual(comparedOutputs(tc, `1\n${thai.replace('ว', 'า')}\n`).actual, cmp.expected, 'a wrong character still fails');
  }
  const crlf = { output: 'a  \r\nb\r\ncde', partialOutput: true };
  const right = comparedOutputs(crlf, 'a\nb   \ncdefg\n');
  assert.strictEqual(right.expected, right.actual);
  // the cut fell between \r and \n: line b is not known to be complete, so only its start counts
  assert.strictEqual(checkedPart('a\r\nbc\r'), 'line 1 and the start of line 2');
  // a cut just after a space mid-line: "1 2" (the line ends there) and "1 2 3 4" both fit what is shown
  const space = { output: '0\n1 2 3', partialOutput: true };
  for (const mine of ['0\n1 2\n', '0\n1 2 3 4\n']) {
    const c = comparedOutputs(space, mine);
    assert.strictEqual(normalize(c.expected), normalize(c.actual), mine);
  }
  const wrong = comparedOutputs(space, '0\n1 23\n');
  assert.notStrictEqual(normalize(wrong.expected), normalize(wrong.actual));
});

test('says which lines of a cut-off expected output were checked', () => {
  assert.strictEqual(checkedPart('a\nb\nc\nd-cut'), 'lines 1-3 and the start of line 4');
  assert.strictEqual(checkedPart('a\nb-cut'), 'line 1 and the start of line 2');
  assert.strictEqual(checkedPart('one long line, cut'), 'the start of line 1');
  // even when what is shown ends with a line break, the last line isn't trusted to be complete
  assert.strictEqual(checkedPart('a\nb\nc\n'), 'lines 1-2');
  const cases = [{ input: '1\n', output: 'a\nb\nc-cut', partialOutput: true }, { input: '1\n', output: 'a\n' }];
  const html = localResultsHtml({ code: 'X' }, cases, [
    { verdict: 'PASS', ms: 3, stdout: 'a\nb\nc-cut-more\n', stderr: '' }, { verdict: 'PASS', ms: 3, stdout: 'a\n', stderr: '' }]);
  assert.strictEqual((html.match(/Checked only/g) || []).length, 1, 'only on the cut-off test');
  assert.match(html, /Checked only lines 1-2 and the start of line 3: the grader shows just the start of the expected output\./);
  const crash = localResultsHtml({ code: 'X' }, cases.slice(0, 1), [{ verdict: 'RE', ms: 3, stdout: '', stderr: 'boom' }]);
  assert.doesNotMatch(crash, /Checked only/, 'nothing was compared on a crash');
});

test('a fingerprint of the code that ignores line endings, trailing spaces and a byte order mark', () => {
  const h = codeHash('n = int(input())\nprint(n)\n');
  assert.strictEqual(h, codeHash('﻿n = int(input())  \r\nprint(n)\r\n\r\n'));
  assert.notStrictEqual(h, codeHash('n = int(input())\nprint(n + 1)\n'));
  // the Thonny plug-in computes the same (thonny/tests/test_pages.py)
  assert.strictEqual(codeHash('print(1)\n'), 'd287bb7f9d15abdc5b6e98536263815744b6ef21c8f3c839fc434ca70d8efe99');
});

test('a test that can\'t be checked here gets the verdict of the last submission, by test number', () => {
  const sub = { id: '700', code: codeHash('print(1)'), tests: [
    { n: 1, total: 2, label: 'Correct', letter: 'P' }, { n: 2, total: 2, label: 'Wrong answer', letter: '-' }] };
  assert.deepStrictEqual(lastSubmitOn(sub, 1, 2, codeHash('print(1)\n')), { id: '700', label: 'Wrong answer', same: true });
  assert.deepStrictEqual(lastSubmitOn(sub, 0, 2, codeHash('print(2)')), { id: '700', label: 'Correct', same: false });
  assert.strictEqual(lastSubmitOn({ ...sub, code: null }, 0, 2, codeHash('x')).same, null, 'code not known');
  assert.strictEqual(lastSubmitOn(sub, 0, 3, 'h'), null, 'graded on other tests than shown here: numbers may not match');
  assert.strictEqual(lastSubmitOn(sub, 2, 2, 'h'), null);
  assert.strictEqual(lastSubmitOn(null, 0, 2, 'h'), null);
  assert.strictEqual(lastSubmitOn({ id: '1', tests: [] }, 0, 2, 'h'), null, 'e.g. a compile error');
});

test('a skipped test shows the last submission\'s verdict on it, short, and is never counted as passed', () => {
  const cases = [{ input: '1\n', output: '1\n' }, { input: 'x'.repeat(2048), output: '5\n', partialInput: true }];
  const skip = (lastSubmit) => [{ verdict: 'PASS', ms: 4, stdout: '1\n', stderr: '' },
    { verdict: 'SKIP', skipped: 'input', ms: 0, stdout: '', stderr: '', ...(lastSubmit ? { lastSubmit } : {}) }];
  const same = localResultsHtml({ code: 'X' }, cases, skip({ id: '700', label: 'Correct', same: true }));
  assert.match(same, /1\/1 passed <span class="ms">\(1 skipped\)/);
  assert.match(same, /SKIP<\/span> Test 2 <span class="ms">last submit: Correct<\/span>/);
  assert.match(same, /so it can't be run here\. Last submit #700 \(this same code\): Correct\./);
  const changed = localResultsHtml({ code: 'X' }, cases, skip({ id: '700', label: 'Wrong answer.', same: false }));
  assert.match(changed, /Last submit #700 \(different code\): Wrong answer\. Submit to check this version\./);
  assert.match(localResultsHtml({ code: 'X' }, cases, skip({ id: '7', label: 'Correct', same: null })), /Last submit #7: Correct\./);
  const none = localResultsHtml({ code: 'X' }, cases, skip(null));
  assert.match(none, /so it can't be run here\. Submit to check it\./);
  assert.match(none, /SKIP<\/span> Test 2 <span class="ms"><\/span>/, 'no "0 ms" for a test that never ran');
  assert.doesNotMatch(none, /last submit/i);
  const evil = localResultsHtml({ code: 'X' }, cases, skip({ id: '7', label: '<b>x</b>', same: true }));
  assert.ok(!evil.includes('<b>x</b>') && evil.includes('&lt;b&gt;x&lt;/b&gt;'), 'the grader\'s text is escaped');
});

test('a data file whose name ends in a dot is found by the program on every system (same names as the Thonny plug-in)', async (t) => {
  const { dataName } = require('../lib/runner');
  assert.deepStrictEqual(['trail.', 'a b. ', '...', 'x.txt'].map((n) => dataName(n, 'win32')), ['trail', 'a b', '', 'x.txt']);
  assert.strictEqual(dataName('trail.', 'linux'), 'trail.');
  const f = await pyFile(t, 'print(open(input().split()[0]).read().strip())');
  if (!f) return;
  const res = await runTests(f, [{ input: '/data/trail. 1\n', output: '7\n', files: { 'trail.': '7\n', '...': 'x' } }], PY_CFG);
  assert.deepStrictEqual(res.map((r) => r.verdict), ['PASS'], res[0].stderr);
});

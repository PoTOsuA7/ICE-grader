'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { runTests, runSingle } = require('../lib/runner');
const { havePython, tempDir } = require('./helpers');

// Generous limit so a slow CI machine starting Python doesn't turn a correct run into TLE;
// the timeout tests use `fast` so they don't wait long.
const cfg = { pythonPath: 'python', cppCompiler: 'g++', cCompiler: 'gcc', timeoutMs: 10000 };
const fast = { ...cfg, timeoutMs: 1500 };
const dir = tempDir('nattee-test-');
const write = (name, src) => { const f = path.join(dir, name); fs.writeFileSync(f, src); return f; };
const cases = [{ input: '2 3\n', output: '5\n' }, { input: '10 1\n', output: '11\n' }];
const verdicts = async (f, cs = cases, c = cfg) => (await runTests(f, cs, c)).map((r) => r.verdict);

test('verdicts: PASS, FAIL, RE, TLE, and trailing whitespace is ignored', async (t) => {
  if (!(await havePython(t))) return;
  assert.deepStrictEqual(await verdicts(write('ok.py', 'a,b=map(int,input().split());print(a+b)')), ['PASS', 'PASS']);
  assert.deepStrictEqual(await verdicts(write('bad.py', 'a,b=map(int,input().split());print(a*b)')), ['FAIL', 'FAIL']);
  assert.deepStrictEqual(await verdicts(write('crash.py', 'raise SystemExit(3)')), ['RE', 'RE']);
  assert.deepStrictEqual(await verdicts(write('ws.py', 'a,b=map(int,input().split());print(a+b,end="  \\n\\n")')), ['PASS', 'PASS']);
  assert.deepStrictEqual(await verdicts(write('slow.py', 'while True: pass'), [cases[0]], fast), ['TLE']);
});

test('non-ASCII output survives (UTF-8)', async (t) => {
  if (!(await havePython(t))) return;
  const r = await runSingle(write('uni.py', 'print("★ สวัสดี")'), '', cfg);
  assert.strictEqual(r.verdict, 'OK');
  assert.strictEqual(r.stdout.trim(), '★ สวัสดี');
});

test('runSingle reports OK, RE and TLE', async (t) => {
  if (!(await havePython(t))) return;
  assert.strictEqual((await runSingle(write('echo.py', 'print(input())'), 'hi\n', cfg)).stdout.trim(), 'hi');
  assert.strictEqual((await runSingle(write('boom.py', '1/0'), '', cfg)).verdict, 'RE');
  assert.strictEqual((await runSingle(write('hang.py', 'import time; time.sleep(60)'), '', fast)).verdict, 'TLE');
});

test('a timeout also kills processes the solution started', async (t) => {
  if (!(await havePython(t))) return;
  const beat = path.join(dir, 'beat.txt');
  const child = `import time\nn=0\nwhile True:\n    n+=1\n    open(r'${beat}','w').write(str(n))\n    time.sleep(0.05)`;
  const parent = `import subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', ${JSON.stringify(child)}])\ntime.sleep(60)`;
  const r = await runSingle(write('tree.py', parent), '', { ...cfg, timeoutMs: 1200 });
  assert.strictEqual(r.verdict, 'TLE');
  await new Promise((res) => setTimeout(res, 600)); // let any straggler settle
  const a = fs.readFileSync(beat, 'utf8');
  await new Promise((res) => setTimeout(res, 800));
  assert.strictEqual(fs.readFileSync(beat, 'utf8'), a, 'grandchild process is still running after the timeout');
});

test('a program runs in a new empty folder, not in VS Code\'s working folder (its program folder on Windows)', async (t) => {
  if (!(await havePython(t))) return;
  // a program that writes a file must not write it there, or fail because it can't
  const f = write('where.py', 'import os\nprint(os.getcwd())\nprint(os.listdir("."))\n');
  for (const r of [(await runTests(f, [{ input: '', output: '' }], cfg))[0], await runSingle(f, '', cfg)]) {
    const [cwd, listing] = r.stdout.trim().split(/\r?\n/);
    assert.notStrictEqual(path.resolve(cwd), path.resolve(process.cwd()));
    assert.notStrictEqual(path.resolve(cwd), dir);
    assert.strictEqual(listing, '[]');
    assert.ok(!fs.existsSync(cwd), 'the folder is removed after the run');
  }
});

test('unsupported file type gives a clear error', async () => {
  await assert.rejects(() => runTests(write('x.rs', ''), cases, cfg), /Unsupported file type/);
});

test('a time limit of 0, negative or not a number falls back to the default instead of instant TLE', async (t) => {
  if (!(await havePython(t))) return;
  const f = write('quick.py', 'print(int(input()) + 1)');
  for (const timeoutMs of [0, -1000, NaN, null]) {
    assert.deepStrictEqual(await verdicts(f, [{ input: '1\n', output: '2\n' }], { ...cfg, timeoutMs }), ['PASS'], String(timeoutMs));
  }
});

test('a huge time limit is not an instant TLE (timers stop at about 24.8 days)', async (t) => {
  if (!(await havePython(t))) return;
  const f = write('quick_huge.py', 'print(int(input()) + 1)');
  assert.deepStrictEqual(await verdicts(f, [{ input: '1\n', output: '2\n' }], { ...cfg, timeoutMs: 3e9 }), ['PASS']);
});

test('a run folder still in use (on Windows: locked) is removed once it is free, not left behind', async () => {
  const { removeDir } = require('../lib/runner');
  const { spawn } = require('child_process');
  const busy = fs.mkdtempSync(path.join(os.tmpdir(), 'nattee-test-busy-'));
  fs.writeFileSync(path.join(busy, 'x.txt'), 'x');
  // a program whose working folder it is, still running for a moment (like one killed that hasn't quite ended)
  const child = spawn(process.execPath, ['-e', 'setTimeout(() => {}, 1000)'], { cwd: busy, env: { ...process.env, ELECTRON_RUN_AS_NODE: '1' } });
  await new Promise((r) => setTimeout(r, 300));
  removeDir(busy, 1500);
  await new Promise((r) => child.once('exit', r));
  await new Promise((r) => setTimeout(r, 2500));
  assert.ok(!fs.existsSync(busy), 'the folder is still there');
});

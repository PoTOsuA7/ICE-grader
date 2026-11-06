'use strict';
const test = require('node:test');
const assert = require('node:assert');
const path = require('path');
const { chapterOf, solutionPath, safeName, isExam } = require('../lib/layout');

test('chapterOf takes the first two parts of the code', () => {
  assert.strictEqual(chapterOf('05_List_15'), '05_List');
  assert.strictEqual(chapterOf('03_If_001'), '03_If');
  assert.strictEqual(chapterOf('P1_07_Biorhythm'), 'P1_07');
  assert.strictEqual(chapterOf('solo'), 'solo');
});

test('a name with another chapter number than the code wins, as on the grader page', () => {
  // Real case: the grader gave chapter 10's problems codes 09_MoreDC_*, named 10_TSD_*
  assert.strictEqual(chapterOf('09_MoreDC_12', '10_TSD_★_Union Intersection'), '10_TSD');
  assert.strictEqual(chapterOf('09_MoreDC_11', '09_NestedLoop_★_Dedent'), '09_MoreDC');
  assert.strictEqual(chapterOf('02_StrList_01', '02-StrLst_★_CitizenID'), '02_StrList');
  assert.strictEqual(chapterOf('P1_07_Biorhythm', '03_If_★★★-07-Biorhythm'), 'P1_07');
  assert.strictEqual(chapterOf('2025s1_Exam2_A1-1_Student', '10_TSD_x'), 'Exam2');
  assert.strictEqual(path.relative('r', solutionPath('r', '09_MoreDC_12', 'py', true, '10_TSD_★_Union')),
    path.join('10_TSD', '09_MoreDC_12.py'));
});

test('exam practice problems are grouped by exam number', () => {
  assert.strictEqual(chapterOf('2025s1_Exam2_A1-1_Student'), 'Exam2');
  assert.strictEqual(chapterOf('Exam1-2024_Q1A_student'), 'Exam1');
  assert.strictEqual(chapterOf('Exam_01'), 'Exam1');
  assert.strictEqual(chapterOf('2026s1_Exam3_A1-1_Student'), 'Exam3');
  assert.strictEqual(chapterOf('Final_Exam_Q1'), 'Exam');
  assert.strictEqual(chapterOf('08_Example_01'), '08_Example', '"Example" is not an exam');
  assert.ok(isExam('Exam1-2024_Q1A_student') && isExam('2025s1_Exam2_B4-1_Student') && !isExam('08_Example_01'));
  assert.strictEqual(solutionPath('ws', 'Exam1-2024_Q1A_student', '.py'), path.join('ws', 'Exam1', 'Exam1-2024_Q1A_student.py'));
});

test('solutionPath puts the file in its chapter folder by default', () => {
  const root = path.join('ws');
  assert.strictEqual(solutionPath(root, '05_List_15', '.py'), path.join('ws', '05_List', '05_List_15.py'));
  assert.strictEqual(solutionPath(root, '01_Expr_02', 'cpp'), path.join('ws', '01_Expr', '01_Expr_02.cpp'));
});

test('solutionPath can keep files flat in the workspace root', () => {
  assert.strictEqual(solutionPath('ws', '05_List_15', '.py', false), path.join('ws', '05_List_15.py'));
});

test('odd characters in a code become safe file and folder names', () => {
  assert.strictEqual(safeName('a b/c'), 'a_b_c');
  assert.strictEqual(solutionPath('ws', '06 Func_01', '.py'), path.join('ws', '06_Func_01', '06_Func_01.py'));
});

test('no file or folder name ends in a dot or is a Windows device name (same names as the Thonny plug-in)', () => {
  assert.strictEqual(safeName('trailing.'), 'trailing');
  assert.strictEqual(safeName('a_.'), 'a');
  assert.deepStrictEqual(['NUL', 'con.py', 'COM1', 'lpt9', 'aux'].map(safeName), ['_NUL', '_con.py', '_COM1', '_lpt9', '_aux']);
  assert.deepStrictEqual(['Console_01', 'NULL', 'com10', '05_NUL_01'].map(safeName), ['Console_01', 'NULL', 'com10', '05_NUL_01']);
  assert.strictEqual(solutionPath('ws', 'CON', '.py'), path.join('ws', '_CON', '_CON.py'));
});

test('a problem code made of dots can never point outside the workspace', () => {
  for (const code of ['..', '..__x', '.', '...', '._.']) {
    for (const byChapter of [true, false]) {
      const file = path.resolve(solutionPath('ws', code, '.py', byChapter));
      assert.ok(file.startsWith(path.resolve('ws') + path.sep), `${code} -> ${file}`);
    }
  }
});

test('names stay usable on Windows: no trailing dot, and not too long for a file name', () => {
  assert.strictEqual(safeName('Lab 1.'), 'Lab_1');
  assert.strictEqual(safeName('...x...'), '...x');
  const file = solutionPath('ws', `05_List_${'y'.repeat(300)}`, '.py');
  assert.ok(path.basename(file).length <= 104 && path.basename(path.dirname(file)).length <= 100, file);
});

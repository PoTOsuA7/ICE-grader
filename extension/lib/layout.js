'use strict';
// Where solution files go in the workspace.
const path = require('path');

// Windows device names, which are no files or folders there (CON, NUL.py, ...)
const DEVICE = /^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\.|$)/i;

// A file or folder name made from a problem code. Never "." or ".." (or empty), which would point outside, never a
// Windows device name, no dot at the end (Windows drops it, so Python could not open the file VS Code made) and at
// most 100 characters. Same rule as the Thonny plug-in's safe_name().
const safeName = (s) => {
  const name = s.replace(/[^\w\-.]+/g, '_').replace(/_+/g, '_').slice(0, 100).replace(/^_|[_.]+$/g, '');
  if (!name) return 'problem';
  return DEVICE.test(name) ? `_${name}` : name;
};

// Exam practice problems, e.g. 2025s1_Exam2_A1-1_Student or Exam1-2024_Q1A_student (not "Example").
const isExam = (s) => /(?<![a-z])exam(?![a-z])/i.test(s);
const EXAM_NUMBER = /(?<![a-z])exam[\s_-]*(\d+)/i;

// 05_List_15 -> 05_List; exam problems go together by exam number: Exam1, Exam2, ... Also the sidebar's grouping.
// When the problem's name starts with another chapter number than its code, the name wins, as on the grader's page:
// code 09_MoreDC_12 named "10_TSD_★_Union Intersection" -> 10_TSD.
// The name may be written "10_TSD", "10-TSD", "10 TSD" or "10_★_..."; "3.14 ..." is no chapter number.
// spellings (from chapterSpellings) makes every problem of one chapter number land in one group.
const chapterOf = (code, name = '', spellings) => {
  const exam = EXAM_NUMBER.exec(code);
  if (exam) return `Exam${Number(exam[1])}`;
  if (isExam(code)) return 'Exam';
  const inCode = /^([0-9]+)_/.exec(code);
  const inName = /^([0-9]{1,2})(?![ _.\-]*[0-9])[ _.\-]+([A-Za-z]*)/.exec(name || '');
  if (inCode && inName && Number(inCode[1]) !== Number(inName[1])) {
    return (spellings && spellings.get(Number(inName[1]))) || (inName[2] ? `${inName[1]}_${inName[2]}` : inName[1]);
  }
  return code.split('_').slice(0, 2).join('_') || code;
};

// Chapter number -> the one spelling to show, so "11_TSD", "11_tsd" and "11_★_..." don't become separate groups.
// A chapter that problem codes already use wins, then the spelling most names use.
const spellingsCache = new WeakMap();
function chapterSpellings(problems) {
  if (spellingsCache.has(problems)) return spellingsCache.get(problems);
  const tally = new Map();
  for (const p of problems) {
    const chapter = chapterOf(p.code, p.name);
    const m = /^([0-9]+)_/.exec(chapter);
    if (!m) continue;
    const n = Number(m[1]);
    if (!tally.has(n)) tally.set(n, new Map());
    tally.get(n).set(chapter, (tally.get(n).get(chapter) || 0) + (movedByName(p.code, p.name) ? 1 : 1e6));
  }
  const best = new Map();
  for (const [n, seen] of tally) {
    best.set(n, [...seen].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1))[0][0]);
  }
  spellingsCache.set(problems, best);
  return best;
}

// True when the name puts the problem in another chapter than its code (09_MoreDC_12 named 10_TSD_...): the problem
// list then shows the name, as the grader's page does, with the code (still the file name) beside it.
const movedByName = (code, name) => chapterOf(code, name) !== chapterOf(code);

// New solution file: <root>/<chapter>/<code><ext>, or <root>/<code><ext> when byChapter is off.
function solutionPath(root, code, ext, byChapter = true, name = '', spellings) {
  if (!ext.startsWith('.')) ext = '.' + ext;
  const file = `${safeName(code)}${ext}`;
  return byChapter ? path.join(root, safeName(chapterOf(code, name, spellings)), file) : path.join(root, file);
}

module.exports = { safeName, chapterOf, chapterSpellings, movedByName, solutionPath, isExam };

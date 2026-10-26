'use strict';
// GraderClient against a fake grader: sessions, login, statements and submit. Never touches the network.
const test = require('node:test');
const assert = require('node:assert');
const { GraderClient } = require('../lib/client');

const html = (body) => `<!DOCTYPE html><html><head><meta name="csrf-param" content="authenticity_token" />
<meta name="csrf-token" content="tok" /></head><body>${body}</body></html>`;
const loginForm = (alert = '') => html(`${alert ? `<div class="alert alert-danger">${alert}</div>` : ''}
<form action="/login/login" method="post"><input type="hidden" name="authenticity_token" value="tok" />
<input name="login" /><input type="password" name="password" /></form>`);
const listRow = (id, sub) => `<tr><td><strong>05_List_★_X</strong><div class='text-muted font-monospace'>05_List_11</div></td>
<td><a href="/problems/${id}/download/statement">pdf</a> <a href="/testcases/show_problem/${id}">tests</a>
${sub ? `<a href="/submissions/${sub}">${sub}</a>` : ''}</td><td>inprogress</td></tr>`;
const listPage = (id, sub, alert = '') => html(`<a href="/main/list">Main</a> <a href="/logout">logout</a>
${alert ? `<div class="alert alert-warning">${alert}</div>` : ''}<table>${listRow(id, sub)}</table>`);
const submitForm = (id) => html(`<form action="/main/submit"><input name="authenticity_token" value="tok2" />
<input name="submission[problem_id]" value="${id}" /><select id="language_id" name="language_id">
<option value="3">Python</option></select></form>`);

// routes: { 'METHOD /path': (req) => Response | [status, body, headers] }
function fakeServer(routes) {
  const real = globalThis.fetch;
  const seen = [];
  globalThis.fetch = async (url, opts = {}) => {
    const u = new URL(url);
    const key = `${opts.method || 'GET'} ${u.origin === 'https://grader.test' ? '' : u.origin}${u.pathname}`;
    seen.push({ key, cookie: opts.headers && opts.headers.Cookie });
    const h = routes[key];
    if (!h) throw new Error(`unexpected request ${key}`);
    const [status, body, headers] = h(opts);
    const res = new Response(body, { status, headers: { 'content-type': 'text/html', ...headers } });
    Object.defineProperty(res, 'url', { value: url }); // real fetch reports the URL it answered for
    return res;
  };
  return { seen, restore: () => { globalThis.fetch = real; } };
}
const client = () => new GraderClient('https://grader.test/');

test('a refused submit is reported, not mistaken for the previous submission', async () => {
  let posted = false;
  const srv = fakeServer({
    'GET /main/list': () => [200, listPage('892', '555', posted ? 'Submission rejected: code too long' : '')],
    'GET /submissions/direct_edit_problem/892': () => [200, submitForm('892')],
    // Cafe Grader re-renders the list (200 at /main/submit) when it refuses a submission
    'POST /main/submit': () => { posted = true; return [200, listPage('892', '555', 'Submission rejected: code too long')]; },
  });
  try {
    await assert.rejects(() => client().submit('892', 'print(1)', '.py'), /did not accept the submission: Submission rejected: code too long/);
  } finally { srv.restore(); }
});

test('submit still finds a new submission from the list, or from the redirect', async () => {
  let posted = false;
  const srv = fakeServer({
    'GET /main/list': () => [200, listPage('892', posted ? '556' : '555')],
    'GET /submissions/direct_edit_problem/892': () => [200, submitForm('892')],
    'POST /main/submit': () => { posted = true; return [200, listPage('892', '556')]; },
  });
  try {
    assert.strictEqual((await client().submit('892', 'print(1)', '.py')).id, '556');
  } finally { srv.restore(); }
  const srv2 = fakeServer({
    'GET /main/list': () => [200, listPage('892', '555')],
    'GET /submissions/direct_edit_problem/892': () => [200, submitForm('892')],
    'POST /main/submit': () => [302, '', { location: '/submissions/777/edit' }],
    'GET /submissions/777/edit': () => [200, html('graded soon')],
  });
  try {
    assert.strictEqual((await client().submit('892', 'print(1)', '.py')).id, '777');
  } finally { srv2.restore(); }
});

test('the session cookie only goes to the grader, never to another host or over http', async () => {
  const srv = fakeServer({
    'GET /problems/1/download/statement': () => [302, '', { location: 'http://storage.other.test/blob', 'set-cookie': '_sess=SECRET; path=/' }],
    'GET http://storage.other.test/blob': () => [200, '%PDF', { 'content-type': 'application/pdf', 'set-cookie': '_sess=ATTACKER' }],
    'GET /main/list': () => [200, listPage('1')],
  });
  try {
    const c = client();
    c.cookies.set('_sess', 'SECRET');
    await c.fetchStatement(1);
    await c.listProblems();
    assert.strictEqual(srv.seen[0].cookie, '_sess=SECRET');
    assert.strictEqual(srv.seen[1].cookie, undefined, 'no cookie on the foreign http hop');
    assert.strictEqual(srv.seen[2].cookie, '_sess=SECRET', 'a foreign Set-Cookie does not replace the session');
  } finally { srv.restore(); }
});

test('a login refused for any reason is an error that says why', async () => {
  const srv = fakeServer({
    'GET /': () => [200, loginForm()],
    'POST /login/login': () => [302, '', { location: '/main/login' }],
    'GET /main/login': () => [200, loginForm('Your account is disabled')],
  });
  try {
    await assert.rejects(() => client().login('u', 'p'), /Login refused: Your account is disabled/);
  } finally { srv.restore(); }
  const srv2 = fakeServer({
    'GET /': () => [200, loginForm()],
    'POST /login/login': () => [200, loginForm('Wrong password')],
  });
  try { await assert.rejects(() => client().login('u', 'p'), /Wrong username or password/); } finally { srv2.restore(); }
  const srv3 = fakeServer({
    'GET /': () => [200, loginForm()],
    'POST /login/login': () => [302, '', { location: '/main/list' }],
    'GET /main/list': () => [200, listPage('1')],
  });
  try { await client().login('u', 'p'); } finally { srv3.restore(); }
});

test('a statement link that lands on a normal grader page is not called an expired session', async () => {
  const srv = fakeServer({
    'GET /problems/1/download/statement': () => [302, '', { location: '/main/list' }],
    'GET /main/list': () => [200, listPage('1', null, 'Statement not available')],
    'GET /problems/2/download/statement': () => [302, '', { location: '/main/login' }],
    'GET /main/login': () => [200, loginForm()],
    'GET /problems/3/download/statement': () => [200, '<h1>Sum</h1><p>Add two numbers.</p>'],
  });
  try {
    await assert.rejects(() => client().fetchStatement(1), /did not return a statement for this problem \(Statement not available\)/);
    await assert.rejects(() => client().fetchStatement(2), /Session expired/);
    assert.strictEqual((await client().fetchStatement(3)).ext, '.html');
  } finally { srv.restore(); }
});

test('a statement is only saved as a document or picture type, never as one that runs when opened', async () => {
  const sent = { 1: ['application/octet-stream', 'statement.bat'], 2: ['application/pdf', 'x.EXE'], 3: ['application/pdf', 'a.pdf.lnk'],
    4: ['text/plain', 'x.hta'], 5: ['application/pdf', '05_List_15.PDF'], 6: ['application/pdf', 'notes.Html'] };
  const routes = {};
  for (const [id, [type, name]] of Object.entries(sent)) {
    routes[`GET /problems/${id}/download/statement`] = () => [200, '%PDF', { 'content-type': type, 'content-disposition': `attachment; filename="${name}"` }];
  }
  const srv = fakeServer(routes);
  try {
    const exts = [];
    for (const id of Object.keys(sent)) exts.push((await client().fetchStatement(id)).ext);
    assert.deepStrictEqual(exts, ['.bin', '.pdf', '.pdf', '.txt', '.pdf', '.html']);
  } finally { srv.restore(); }
});

test('a .c file is matched to a language listed as "ANSI C"', async () => {
  const form = html(`<form action="/main/submit"><input name="authenticity_token" value="tok2" />
<input name="submission[problem_id]" value="5" /><select id="language_id" name="language_id">
<option value="1">C++</option><option value="2">GNU ANSI C</option></select></form>`);
  let posted = null;
  const srv = fakeServer({
    'GET /main/list': () => [200, listPage('5')],
    'GET /submissions/direct_edit_problem/5': () => [200, form],
    'POST /main/submit': (opts) => { posted = Object.fromEntries(opts.body.entries()); return [302, '', { location: '/submissions/9' }]; },
    'GET /submissions/9': () => [200, html('queued')],
  });
  try {
    assert.strictEqual((await client().submit('5', 'int main(){}', '.c')).language, 'GNU ANSI C');
    assert.strictEqual(posted.language_id, '2');
  } finally { srv.restore(); }
});

test('a submit form whose languages can\'t be read says the page changed, not that the language is refused', async () => {
  let posted = false;
  const srv = fakeServer({
    'GET /main/list': () => [200, listPage('5')],
    'GET /submissions/direct_edit_problem/5': () => [200, html(`<form action="/main/submit"><input name="authenticity_token" value="tok2" />
<input name="submission[problem_id]" value="5" /><div class="language-picker">Python</div></form>`)],
    'POST /main/submit': () => { posted = true; return [302, '', { location: '/submissions/9' }]; },
  });
  try {
    await assert.rejects(() => client().submit('5', 'print(1)', '.py'), /Could not read the languages on the submit form/);
    assert.strictEqual(posted, false);
  } finally { srv.restore(); }
});

test('no connection, or no answer from the grader, is said plainly (not "fetch failed")', async () => {
  const srv = fakeServer({
    'GET /main/list': () => {
      throw new TypeError('fetch failed', { cause: Object.assign(new Error('getaddrinfo ENOTFOUND grader.test'), { code: 'ENOTFOUND' }) });
    },
    'GET /testcases/show_problem/1': () => { throw new DOMException('The operation was aborted due to timeout', 'TimeoutError'); },
  });
  try {
    await assert.rejects(() => client().listProblems(), /Can't reach grader\.test \(ENOTFOUND\) - check your internet connection/);
    await assert.rejects(() => client().fetchTestcases(1), /grader\.test did not answer within 30 s/);
  } finally { srv.restore(); }
});

// The submission page as the grader shows it (checked against a real one, 2026-10-17).
const row = (label, value) => `<div class='row mb-2'>\n<div class='col-4 text-end text-secondary'>\n${label}\n</div>\n<div class='col'>\n${value}\n</div>\n</div>`;

test('waiting for a grade: a page without the grading status fails at once instead of "still grading"', async () => {
  let polls = 0;
  const srv = fakeServer({
    'GET /submissions/1': () => { polls++; return [200, html(row('Points', '100.0/100') + row('Grading Task Status', 'done'))]; },
    'GET /submissions/2': () => { polls++; return [200, html('<h1>Submission</h1><p>a brand new layout</p>')]; },
    'GET /submissions/3': () => { polls++; return [200, loginForm()]; },
  });
  try {
    const g = await client().waitForGrade('1', { intervalMs: 1 });
    assert.deepStrictEqual([g.done, g.points, g.timedOut], [true, 100, false]);
    polls = 0;
    await assert.rejects(() => client().waitForGrade('2', { intervalMs: 1 }), /Could not read the grading status of submission #2/);
    assert.strictEqual(polls, 1, 'no 90 s of polling');
    await assert.rejects(() => client().waitForGrade('3', { intervalMs: 1 }), /Session expired while waiting for submission #3/);
  } finally { srv.restore(); }
});

test('your submission is read once: its verdict per test and the code it was for', async () => {
  const tile = (n, label, letter) => `<span class="verdict-tile" title="Test ${n} of 2: ${label}">${letter}</span>`;
  const page = row('Points', '50/100') + row('Result', tile(1, 'Correct', 'P') + tile(2, 'Wrong answer', '-')) +
    row('Grading Task Status', 'done') + "<textarea id='text_sourcecode' style='display:none'>print(1 &lt; 2)\n</textarea>";
  const srv = fakeServer({
    'GET /submissions/5': () => [200, html(page)],
    'GET /submissions/6': () => [200, html(row('Grading Task Status', 'done'))],
    'GET /submissions/7': () => [200, loginForm()],
  });
  try {
    const s = await client().fetchSubmission('5');
    assert.deepStrictEqual([s.done, s.source, s.tests.map((t) => t.label)], [true, 'print(1 < 2)\n', ['Correct', 'Wrong answer']]);
    assert.strictEqual((await client().fetchSubmission('6')).source, null, 'a page without the code');
    await assert.rejects(() => client().fetchSubmission('7'), /Session expired while reading submission #7/);
    assert.strictEqual(srv.seen.length, 3, 'one request each, no polling');
  } finally { srv.restore(); }
});

test('a grader that does not answer is given up on after the time asked for', async () => {
  const real = globalThis.fetch;
  globalThis.fetch = (url, opts) => new Promise((_, reject) => opts.signal.addEventListener('abort', () => reject(opts.signal.reason)));
  try {
    const started = Date.now();
    await assert.rejects(() => client().fetchSubmission('5', 50));
    assert.ok(Date.now() - started < 5000, `took ${Date.now() - started} ms`);
  } finally { globalThis.fetch = real; }
});

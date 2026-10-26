"""Everything the plug-in does, without any Tk or Thonny code: sign-in, the saved copies of problems, statements
and tests (so it works while the grader site is down), running tests and submitting. The views call these from a
worker thread."""
import json
import os
import re
import shutil
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from . import runner
from .client import GraderClient, GraderError, SessionExpired
from .diff import code_hash
from .layout import safe_name, chapter_of
from .passwords import KeyringSecrets

DEFAULT_ROOT = "https://2190101.nattee.net/"
TESTS_FILE = "tests.v1.json"
SUBMISSION_FILE = "submission.json"  # your latest submission's verdicts, for tests that can't be checked here


class NotSignedIn(GraderError):
    pass


def language_ext(language):
    """The file extension for a submission's language, as the VS Code version names them."""
    if re.search("python", language, re.I):
        return ".py"
    if re.search(r"c\+\+|cpp", language, re.I):
        return ".cpp"
    return ".c" if re.fullmatch(r"\s*c\s*", language, re.I) else ".txt"


class Core:
    def __init__(self, data_dir, root_url=DEFAULT_ROOT, client_class=GraderClient, secrets=None):
        self.root = root_url
        self.host = urllib.parse.urlsplit(root_url).netloc or "grader"
        self.dir = os.path.join(data_dir, self.host)
        os.makedirs(self.dir, exist_ok=True)
        self._client_class = client_class
        self.secrets = secrets or KeyringSecrets()
        self._lock = threading.RLock()
        self._password = None  # this session's copy; the saved one is in the computer's password store
        self.remembered = False  # whether the password store kept it
        session = self._read_json("session.json") or {}
        self.uid = session.get("uid")
        self.client = client_class(root_url, session.get("cookies")) if self.uid else None
        self.problems = self._read_json("problems.json") or []
        self.links = self._read_json("links.json") or {}  # file -> problem id, for files not named after a problem
        self._lookups = {}  # submission id -> when it was last asked for

    # ---- files

    def _path(self, *parts):
        return os.path.join(self.dir, *parts)

    def _read_json(self, *parts):
        try:
            with open(self._path(*parts), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _write_json(self, value, *parts):
        os.makedirs(os.path.dirname(self._path(*parts)), exist_ok=True)
        tmp = self._path(*parts) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(value, f)
        os.replace(tmp, self._path(*parts))

    def _save_session(self):
        self._write_json({"uid": self.uid, "cookies": self.client.cookies}, "session.json")

    # ---- signing in

    @property
    def signed_in(self):
        return self.client is not None

    def _secret_name(self, uid=None):
        return "grader:%s:%s" % (self.host, uid or self.uid)

    def sign_in(self, uid, password):
        client = self._client_class(self.root)
        client.login(uid, password)
        with self._lock:
            if self.uid and self.uid != uid:
                self.secrets.delete(self._secret_name())
            self.client, self.uid, self._password = client, uid, password
            self._save_session()
            self.remembered = self.secrets.set(self._secret_name(), password)
        return self.refresh_problems()

    def sign_out(self):
        with self._lock:
            if self.uid:
                self.secrets.delete(self._secret_name())
            self.client, self.uid, self._password = None, None, None
            try:
                os.remove(self._path("session.json"))
            except OSError:
                pass

    def _call(self, fn):
        """fn(client), signing in again once with the remembered password if the grader's session ran out."""
        if not self.client:
            raise NotSignedIn("Sign in to the grader first.")
        try:
            result = fn(self.client)
        except SessionExpired:
            password = self._password or self.secrets.get(self._secret_name())
            if not password:
                self.sign_out()
                raise
            try:
                self.client.login(self.uid, password)
            except GraderError:  # the password was changed on the grader
                self.sign_out()
                raise SessionExpired("The grader signed you out and your saved password no longer works - sign in again.")
            self._password = password
            result = fn(self.client)
        with self._lock:
            if self.client:
                self._save_session()  # the grader may have renewed the session cookie
        return result

    # ---- problems, statements, tests

    def refresh_problems(self):
        problems = self._call(lambda c: c.list_problems())
        with self._lock:
            self.problems = problems
            self._write_json(problems, "problems.json")
        return problems

    @staticmethod
    def _link_key(filename):
        return os.path.normcase(os.path.abspath(filename))

    def link(self, filename, p):
        """From now on this file belongs to problem p, whatever its name."""
        with self._lock:
            self.links[self._link_key(filename)] = p["id"]
            self._write_json(self.links, "links.json")

    def problem_for_file(self, filename):
        """The problem a file was linked to, else the one it is named after (05_List_15.py)."""
        if not filename:
            return None
        linked = self.links.get(self._link_key(filename))
        if linked:
            p = next((p for p in self.problems if p["id"] == linked), None)
            if p:
                return p
        stem = os.path.splitext(os.path.basename(filename))[0].lower()
        return next((p for p in self.problems if safe_name(p["code"]).lower() == stem or p["code"].lower() == stem), None)

    def clipboard_copy(self, p):
        """A copy of the statement named after the problem (06_Func_21.pdf), for putting on the clipboard. It stays
        until the next copy, so it can still be pasted later."""
        source = self.statement_path(p)
        folder = self._path("clipboard")
        shutil.rmtree(folder, ignore_errors=True)
        os.makedirs(folder, exist_ok=True)
        target = os.path.join(folder, safe_name(p["code"]) + os.path.splitext(source)[1])
        shutil.copyfile(source, target)
        return target

    def statement_path(self, p):
        """The statement file, downloaded once and then read from the saved copy."""
        folder = self._path(p["id"])
        if os.path.isdir(folder):
            for name in os.listdir(folder):
                if name.startswith("statement."):
                    return os.path.join(folder, name)
        data, ext = self._call(lambda c: c.fetch_statement(p["id"]))
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "statement" + ext)
        with open(path + ".tmp", "wb") as f:
            f.write(data)
        os.replace(path + ".tmp", path)
        return path

    def tests(self, p, refresh=False):
        cached = None if refresh else self._read_json(p["id"], TESTS_FILE)
        if cached is not None:
            return cached
        if not p.get("has_testcases", True):
            return []
        try:
            cases = self._call(lambda c: c.fetch_testcases(p["id"]))
        except (OSError, GraderError):
            stale = self._read_json(p["id"], TESTS_FILE)
            if stale is not None:
                return stale
            raise
        self._write_json(cases, p["id"], TESTS_FILE)
        return cases

    def is_saved(self, p):
        return os.path.exists(self._path(p["id"], TESTS_FILE)) or not p.get("has_testcases", True)

    def last_submission(self, p):
        """Your latest submission's verdicts {id, tests, code} (code: code_hash of what was submitted), for tests that
        can't be checked here. Saved when you submit from here; else read once from its page on the grader (only while
        signed in, at most once a minute) and saved, so later runs need no request and it works offline.
        None: not known."""
        saved = self._read_json(p["id"], SUBMISSION_FILE)
        latest = p.get("last_submission_id")
        if saved and (not latest or int(saved["id"]) >= int(latest)):
            return saved
        if not latest or not self.client or time.time() - self._lookups.get(latest, 0) < 60:
            return None
        self._lookups[latest] = time.time()
        try:
            g = self._call(lambda c: c.fetch_submission(latest, timeout=10))
        except (OSError, GraderError):
            return None  # offline or signed out: the test just says to submit
        if not g["done"]:
            return None
        sub = {"id": latest, "tests": g["tests"], "code": code_hash(g["source"]) if g["source"] is not None else None}
        self._write_json(sub, p["id"], SUBMISSION_FILE)
        return sub

    def run_tests(self, python, file, p, time_limit, on_result=None):
        """-> (cases, results). A test that can't be checked here (SKIP) shows the grader's verdict on it from your
        last submission, if known: result["last_submit"] (see runner.last_submit_on)."""
        cases = self.tests(p)
        try:
            with open(file, encoding="utf-8", errors="replace") as f:
                code = code_hash(f.read())
        except OSError:
            code = None
        found = []  # the last submission, looked up at the first skipped test

        def each(i, r):
            if r["verdict"] == "SKIP":
                if not found:
                    found.append(self.last_submission(p))
                seen = runner.last_submit_on(found[0], i, len(cases), code)
                if seen:
                    r["last_submit"] = seen
            if on_result:
                on_result(i, r)
        return cases, runner.run_tests(python, file, cases, time_limit, each)

    def submit(self, p, source, on_update=None):
        sub = self._call(lambda c: c.submit(p["id"], source))
        result = self._call(lambda c: c.wait_for_grade(sub["id"], on_update=on_update))
        result["id"] = sub["id"]
        if result["done"]:  # for tests skipped here
            self._write_json({"id": sub["id"], "tests": result["tests"], "code": code_hash(source)}, p["id"], SUBMISSION_FILE)
        try:
            self.refresh_problems()  # new score in the list
        except (OSError, GraderError):
            pass
        return result

    # ---- everything at once

    def each_problem(self, fn, on_progress=None, cancelled=lambda: False):
        """fn(p) on every problem, three at a time so the grader isn't flooded. -> (done, [failed codes], stopped)"""
        todo = list(self.problems)
        failed, done = [], [0]

        def one(p):
            if cancelled():
                return
            try:
                fn(p)
            except Exception:  # noqa: BLE001 - one problem failing must not stop the rest
                failed.append(p["code"])
            done[0] += 1
            if on_progress:
                on_progress(done[0], len(todo))

        with ThreadPoolExecutor(3) as pool:
            list(pool.map(one, todo))
        return done[0] - len(failed), failed, cancelled()

    def download_all(self, on_progress=None, cancelled=lambda: False):
        """Saves every statement and test, so everything except Submit works while the grader site is down."""
        self.refresh_problems()
        return self.each_problem(lambda p: (self.statement_path(p), self.tests(p)), on_progress, cancelled)

    def export_all(self, folder, on_progress=None, cancelled=lambda: False):
        """Every statement and the latest submitted code of each problem, by chapter, into folder."""
        self.refresh_problems()
        solutions = [0]

        def one(p):
            into = os.path.join(folder, safe_name(chapter_of(p["code"])))
            os.makedirs(into, exist_ok=True)
            statement = self.statement_path(p)
            with open(statement, "rb") as src, open(os.path.join(into, safe_name(p["code"]) + os.path.splitext(statement)[1]), "wb") as dst:
                dst.write(src.read())
            if p.get("last_submission_id"):
                code = self._call(lambda c: c.fetch_submission_source(p["last_submission_id"]))
                ext = language_ext(code["language"])
                with open(os.path.join(into, safe_name(p["code"]) + ext), "w", encoding="utf-8", newline="") as f:
                    f.write(code["source"])
                solutions[0] += 1

        saved, failed, stopped = self.each_problem(one, on_progress, cancelled)
        return saved, failed, stopped, solutions[0]

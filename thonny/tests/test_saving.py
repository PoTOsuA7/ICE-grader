"""Saving while tests run, and files in another encoding: the commands with a stand-in for Thonny's workbench and Test Results
panel (no display needed) and saved made-up tests (no grader)."""
import os
import shutil
import sys
import tempfile
import time
import types
import unittest

import thonnycontrib.ice_grader as plugin
from thonnycontrib.ice_grader.core import TESTS_FILE, Core, read_source
from thonnycontrib.ice_grader.passwords import MemorySecrets

P = {"id": "10", "code": "05_List_15", "name": "x", "has_testcases": True, "status": "untried", "score": 0}


class ResultsPanel:
    """Records the verdicts of each run shown."""

    def __init__(self):
        self.runs = []

    def start(self, p, filename, take_panel=True):
        self.runs.append([])

    def expect(self, n):
        pass

    def add(self, i, tc, r):
        self.runs[-1].append(r["verdict"])

    def finish(self, cases, results):
        return plugin.summary_text(results)

    def failed(self, text):
        self.runs[-1].append(text)


class Commands(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        core = Core(os.path.join(self.dir, "data"), "https://grader.test/", None, MemorySecrets())
        core.problems = [P]
        core._write_json([{"input": "1 2\n", "output": "3\n"}], P["id"], TESTS_FILE)
        self.panel, self.messages = ResultsPanel(), []
        options = {"ice_grader.time_limit": 10, "ice_grader.run_on_save": True}
        wb = types.SimpleNamespace(get_option=lambda k, d=None: options.get(k, d), show_view=lambda *a, **k: None,
                                   get_view=lambda vid, create=True: self.panel if vid == "GraderResultsView" else None)
        self.saved = plugin._core, plugin._wb, plugin.messagebox, plugin.target_python
        plugin._core, plugin._wb, plugin.target_python = core, lambda: wb, lambda: sys.executable
        plugin.messagebox = types.SimpleNamespace(showinfo=lambda t, m, **k: self.messages.append(m),
                                                  showerror=lambda t, m, **k: self.messages.append(m),
                                                  askyesno=lambda *a, **k: False)

    def tearDown(self):
        plugin._core, plugin._wb, plugin.messagebox, plugin.target_python = self.saved
        shutil.rmtree(self.dir, ignore_errors=True)

    def program(self, code, encoding="utf-8"):
        path = os.path.join(self.dir, "05_List_15.py")
        with open(path, "w", encoding=encoding) as f:
            f.write(code)
        return path

    def idle(self):
        """Tk's side: what the background work hands back, until nothing runs."""
        end = time.time() + 60
        while time.time() < end:
            while not plugin._tasks.empty():
                plugin._tasks.get_nowait()()
            if not plugin._busy and plugin._tasks.empty():
                return
            time.sleep(0.02)
        self.fail("the tests are still running")

    def test_a_save_while_the_tests_run_tests_the_newest_code_once_they_finish(self):
        started = os.path.join(self.dir, "started")
        f = self.program("open(%r, 'w').close()\nimport time\ntime.sleep(0.5)\nprint(3)\n" % started)
        saved = types.SimpleNamespace(filename=f)
        plugin._on_save(saved)
        while not plugin._tasks.empty():  # Thonny writes the file, then the tests start
            plugin._tasks.get_nowait()()
        end = time.time() + 20
        while not os.path.exists(started) and time.time() < end:  # the right version is running
            time.sleep(0.02)
        self.program("print(4)\n")  # a wrong version, saved twice while it runs
        plugin._on_save(saved)
        plugin._on_save(saved)
        self.idle()
        self.assertEqual(self.panel.runs, [["PASS"], ["FAIL"]])

    def test_a_program_with_a_coding_line_for_another_encoding_runs(self):
        # Thonny opens and saves such a file in its own encoding; reading it as UTF-8 failed before the run started
        f = self.program("# -*- coding: cp874 -*-\n# สวัสดี\nprint(3)\n", "cp874")
        plugin.run_tests_for(f, P)
        self.idle()
        self.assertEqual(self.panel.runs, [["PASS"]])
        self.assertIn("สวัสดี", plugin._last_run["code"])
        self.assertIn("สวัสดี", read_source(f))  # what Submit sends
        plugin.run_tests_for(os.path.join(self.dir, "gone.py"), P)  # a file deleted since: says so
        self.idle()
        self.assertEqual(self.panel.runs[-1], ["RE"])


if __name__ == "__main__":
    unittest.main()

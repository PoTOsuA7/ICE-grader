"""The plug-in's commands with a stand-in for Thonny's workbench (no Thonny needed) and the fake grader client."""
import os
import queue
import shutil
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest import mock

import thonnycontrib.ice_grader as ig
from thonnycontrib.ice_grader.core import Core
from thonnycontrib.ice_grader.passwords import MemorySecrets
from test_client import FakeClient


class Event:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeEditor:
    def __init__(self, filename):
        self.filename = filename

    def get_filename(self):
        return self.filename


class FakeNotebook:
    editor = None

    def get_current_editor(self):
        return self.editor


class FakeLabel:
    def __init__(self):
        self.text = ""

    def configure(self, text="", **kw):
        self.text = text


class FakeStatementView:
    def __init__(self):
        self.hidden, self.problem, self.loading = False, None, None
        self.title = FakeLabel()
        self.shown = []

    def show(self, p, path):
        self.problem = p
        self.shown.append(p["code"])


class FakeGraderView:
    status = ""

    def set_status(self, text):
        self.status = text

    def fill(self):
        self.status = "filled in"


class FakeResults:
    def __init__(self):
        self.started = []

    def start(self, p, filename, take_panel=True):
        self.started.append(take_panel)

    def expect(self, n):
        pass

    def add(self, i, tc, r):
        pass

    def finish(self, cases, results):
        return "done", "PASS"


class FakeWorkbench:
    def __init__(self, options):
        self.options = dict(options)
        self.views = {}
        self.notebook = FakeNotebook()
        self.handlers = {}

    def get_option(self, name, default=None):
        return self.options.get(name, default)

    def set_option(self, name, value):
        self.options[name] = value

    def set_default(self, name, value):
        self.options.setdefault(name, value)

    def get_view(self, view_id, create=True):
        if view_id not in self.views:
            raise RuntimeError("View %s not created" % view_id)  # like Thonny with create=False
        return self.views[view_id]

    def show_view(self, view_id, set_focus=True):
        self.views[view_id].hidden = False

    def get_editor_notebook(self):
        return self.notebook

    def bind(self, sequence, func, add=None):
        self.handlers.setdefault(sequence, []).append(func)

    def add_view(self, *args, **kw):
        pass

    def add_command(self, *args, **kw):
        pass

    def after(self, ms, func, *args):
        pass


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class Commands(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        FakeClient.calls, FakeClient.down, FakeClient.expired = [], False, False
        self.core = Core(self.dir, "https://grader.test/", FakeClient, MemorySecrets())
        self.core.sign_in("u", "pw")
        self.p10, self.p11 = self.core.problems
        self.wb = FakeWorkbench({"ice_grader.run_on_save": True})
        self.box = mock.Mock()
        self.box.askyesno.return_value = False
        for patch in (mock.patch.object(ig, "_wb", lambda: self.wb), mock.patch.object(ig, "_core", self.core),
                      mock.patch.object(ig, "messagebox", self.box)):
            patch.start()
            self.addCleanup(patch.stop)
        ig._busy.clear()
        self.settle(lambda: False, 0)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def settle(self, until, seconds=3):
        """Runs what background work hands back to Tk's thread, until until() or the time is up."""
        end = time.time() + seconds
        while True:
            try:
                ig._tasks.get(timeout=0.02)()
            except queue.Empty:
                if until() or time.time() > end:
                    return

    def test_tests_on_save_run_once_thonny_has_written_the_file(self):
        path = os.path.join(self.dir, "05_List_15.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write("print(1)\n")
        seen = []
        with mock.patch.object(ig, "run_tests_for", lambda filename, p, show=True: seen.append(read(filename))):
            ig._on_save(Event(filename=path))  # Thonny tells plug-ins first...
            with open(path, "w", encoding="utf-8") as f:  # ...then writes the file
                f.write("print(2)\n")
            self.settle(lambda: seen)
        self.assertEqual(seen, ["print(2)\n"])  # also the code Explain sends: the saved one

    def test_tests_on_save_leave_the_panel_to_a_submission_being_graded(self):
        results = self.wb.views["GraderResultsView"] = FakeResults()
        path = os.path.join(self.dir, "05_List_15.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write("print(1)\n")
        ig._busy.add("submit")  # Submit saved the file, then submitted it
        ig.run_tests_for(path, self.p10, show=False)
        self.settle(lambda: "tests" not in ig._busy)
        ig._busy.discard("submit")
        ig.run_tests_for(path, self.p10, show=False)  # graded: the next save shows its tests again
        self.settle(lambda: "tests" not in ig._busy)
        self.assertEqual(results.started, [False, True])

    def test_the_first_save_of_a_new_file_runs_the_tests_too(self):
        ig.load_plugin()
        path = os.path.join(self.dir, "05_List_15.py")
        seen = []
        with mock.patch.object(ig, "run_tests_for", lambda filename, p, show=True: seen.append(filename)):
            for handler in self.wb.handlers.get("SaveAs", []):
                handler(Event(filename=path, save_copy=False))
                handler(Event(filename=os.path.join(self.dir, "copy", "05_List_15.py"), save_copy=True))
            self.settle(lambda: len(seen) > 1, 0.5)
        self.assertEqual(seen, [path])

    def test_a_statement_asked_for_earlier_does_not_replace_the_one_asked_for_since(self):
        view = self.wb.views["StatementView"] = FakeStatementView()
        slow, real = threading.Event(), self.core.statement_path

        def statement_path(p):
            if p is self.p10:
                slow.wait(5)  # a download that takes a while
            return real(p)
        with mock.patch.object(self.core, "statement_path", statement_path), mock.patch.object(ig, "can_show_pdfs", lambda: True):
            ig.show_statement(self.p10)
            ig.show_statement(self.p11)  # the student opened another problem meanwhile
            self.settle(lambda: view.shown)
            slow.set()
            self.settle(lambda: len(view.shown) > 1, 0.5)
        self.assertEqual(view.shown, [self.p11["code"]])

    def test_a_statement_asked_for_twice_is_downloaded_once(self):
        # opening a problem's file with the Statement panel open: the tab change and the command both ask
        view = self.wb.views["StatementView"] = FakeStatementView()
        asked, real = [], self.core.statement_path

        def statement_path(p):
            asked.append(p["id"])
            time.sleep(0.2)
            return real(p)
        with mock.patch.object(self.core, "statement_path", statement_path), mock.patch.object(ig, "can_show_pdfs", lambda: True):
            ig.show_statement(self.p10)
            ig.show_statement(self.p10)
            self.settle(lambda: len(view.shown) > 1, 1)
        self.assertEqual((asked, view.shown), (["10"], [self.p10["code"]]))

    def test_switching_files_does_not_open_the_pdf_app_when_the_panel_cannot_show_pdfs(self):
        self.wb.views["StatementView"] = FakeStatementView()
        self.wb.notebook.editor = FakeEditor(os.path.join(self.dir, "05_List_15.py"))
        opened = []
        with mock.patch.object(ig, "can_show_pdfs", lambda: False), mock.patch.object(ig, "open_externally", opened.append):
            ig._on_editor_changed()
            ig._on_editor_changed()
            self.settle(lambda: False, 0.5)
        self.assertEqual(opened, [])

    def test_a_failed_refresh_does_not_leave_the_panel_saying_refreshing(self):
        panel = self.wb.views["GraderView"] = FakeGraderView()
        FakeClient.down = True
        ig.cmd_refresh()
        self.assertEqual(panel.status, "Refreshing...")
        self.settle(lambda: self.box.showerror.called)
        self.assertIn("Couldn't reach the grader site", self.box.showerror.call_args[0][1])
        self.assertEqual(panel.status, "filled in")

    def test_cancelling_change_folder_keeps_the_folder(self):
        self.wb.options["ice_grader.solutions_dir"] = self.dir
        with mock.patch.object(ig.filedialog, "askdirectory", lambda **kw: ""):
            ig.cmd_change_folder()
        self.assertEqual(self.wb.get_option("ice_grader.solutions_dir"), self.dir)


class ResultsPanel(unittest.TestCase):
    """Tests and a submission share the Test Results panel: the one started last has it."""

    def setUp(self):
        try:
            import thonny.tktextext  # noqa: F401 - the panel's text box is Thonny's
        except ImportError:
            self.skipTest("needs Thonny")
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        self.root.withdraw()
        self.view = ig.GraderResultsView(self.root)

    def tearDown(self):
        self.root.destroy()

    def text(self):
        return self.view.text.get("1.0", "end").strip()

    def test_tests_still_running_when_a_submission_is_graded_stay_out_of_its_result(self):
        v, p = self.view, {"code": "05_List_15"}
        v.start(p, "05_List_15.py")  # Submit saved the file, so the tests started...
        v.expect(1)
        v.start_submit(p, "05_List_15.py")  # ...and then it submitted
        v.graded({"id": "7", "points": 50.0, "max": 100.0, "tests": [{"n": 1, "label": "Correct", "letter": "P"}]})
        v.add(0, {"input": "1\n", "output": "1\n"}, {"verdict": "PASS", "ms": 5, "stdout": "1\n", "stderr": ""})
        self.assertEqual(v.finish([{}], [{"verdict": "PASS"}]), ("1 of 1 passed", "PASS"))  # for the Grader panel
        self.assertEqual(self.text(), "Submission #7: 50 / 100 points\nTest 1: Correct")
        self.assertEqual(str(v.explain_button.cget("state")), "disabled")

    def test_a_submission_still_grading_does_not_wipe_tests_started_since(self):
        v, p = self.view, {"code": "05_List_15"}
        v.start_submit(p, "05_List_15.py")
        v.start(p, "05_List_15.py")  # saved again while it was being graded
        v.expect(1)
        v.grading({"status": "grading"})
        v.add(0, {"input": "1\n", "output": "1\n"}, {"verdict": "PASS", "ms": 5, "stdout": "1\n", "stderr": ""})
        v.graded({"id": "7", "points": 50.0, "max": 100.0, "tests": []})
        v.finish([{}], [{"verdict": "PASS"}])
        self.assertEqual(self.text(), "05_List_15 - running 05_List_15.py\n1 of 1 passed\n\nTest 1 of 1  PASS  5 ms")


if __name__ == "__main__":
    unittest.main()

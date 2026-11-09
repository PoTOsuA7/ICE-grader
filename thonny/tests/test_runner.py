"""Really runs Python programs against tests."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from thonnycontrib.ice_grader import runner
from thonnycontrib.ice_grader.runner import data_name, run_tests


class Runner(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def program(self, code):
        path = os.path.join(self.dir, "sol.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        return path

    def run_cases(self, code, cases, limit=10):
        return [r["verdict"] for r in run_tests(sys.executable, self.program(code), cases, limit)]

    def test_verdicts(self):
        cases = [{"input": "2 3\n", "output": "5\n"}, {"input": "1 1\n", "output": "3\n"}]
        self.assertEqual(self.run_cases("a, b = map(int, input().split())\nprint(a + b)\n", cases), ["PASS", "FAIL"])
        self.assertEqual(self.run_cases("print(int(input()))\n", cases[:1]), ["RE"])

    def test_endless_loop_is_stopped_at_the_time_limit(self):
        start = time.time()
        self.assertEqual(self.run_cases("while True: pass\n", [{"input": "", "output": "x"}], limit=1), ["TLE"])
        self.assertLess(time.time() - start, 6)

    def test_waiting_for_input_that_never_comes_is_a_crash_not_a_hang(self):
        self.assertEqual(self.run_cases("input()\ninput()\n", [{"input": "1\n", "output": ""}]), ["RE"])

    def test_non_ascii_output(self):
        self.assertEqual(self.run_cases("print('สวัสดี ★')\n",
                                        [{"input": "", "output": "สวัสดี ★\n"}]), ["PASS"])

    def test_cut_input_is_skipped_and_data_files_are_found(self):
        code = "name = input()\nprint(sum(int(x) for x in open(name)))\n"
        files = {"data.txt": "1\n2\n3\n"}
        cases = [{"input": "/data/data.txt\n", "output": "6\n", "files": files},
                 {"input": "/data/da", "output": "6\n", "files": files, "partial_input": True}]
        self.assertEqual(self.run_cases(code, cases), ["PASS", "SKIP"])

    def test_data_path_typed_into_the_code_is_found(self):
        cases = [{"input": "", "output": "hello\n", "files": {"a.txt": "hello"}}]
        self.assertEqual(self.run_cases("print(open('/data/a.txt').read().strip())\n", cases), ["PASS"])
        self.assertEqual(self.run_cases("print(open('/data/missing.txt').read())\n", cases), ["RE"])

    def test_odd_data_file_names_are_found_and_never_break_the_run(self):
        # the same names as the VS Code version's dataName: "..." would be the sandbox folder itself on Windows
        self.assertEqual([data_name(n, "win32") for n in ("trail.", "a b. ", "...", "x.txt", "dir/", "..\\e.txt")],
                         ["trail", "a b", "", "x.txt", "dir", "e.txt"])
        self.assertEqual(data_name("trail.", "linux"), "trail.")
        code = "print(open(input().split()[0]).read().strip())\n"
        files = {"trail.": "7\n", "...": "x"}
        self.assertEqual(self.run_cases(code, [{"input": "/data/trail. 1\n", "output": "7\n", "files": files}]), ["PASS"])

    def test_a_program_the_solution_leaves_running_does_not_hold_up_the_tests(self):
        code = "import subprocess, sys\nsubprocess.Popen([sys.executable, '-c', 'import time; time.sleep(7)'])\nprint(5)\n"
        start = time.time()
        self.assertEqual(self.run_cases(code, [{"input": "", "output": "5\n"}]), ["PASS"])
        self.assertLess(time.time() - start, 5.5)

    def test_closing_thonny_stops_the_program_being_tested(self):
        beat = os.path.join(self.dir, "beat")
        sol = self.program("import time\nend = time.time() + 15\nwhile time.time() < end:\n"
                           "    open(%r, 'a').write('.')\n    time.sleep(0.1)\n" % beat)
        # "Thonny": runs the tests in a worker thread and quits while the program is still running
        host = "\n".join([
            "import os, sys, threading, time",
            "from thonnycontrib.ice_grader.runner import run_tests",
            "case = {'input': '', 'output': ''}",
            "threading.Thread(target=run_tests, args=(sys.executable, %r, [case], 30), daemon=True).start()" % sol,
            "end = time.time() + 10",
            "while not os.path.exists(%r) and time.time() < end:" % beat,
            "    time.sleep(0.05)",
        ])
        root = os.path.dirname(os.path.dirname(os.path.dirname(runner.__file__)))
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([root, os.environ.get("PYTHONPATH", "")]))
        subprocess.run([sys.executable, "-c", host], env=env, timeout=30)
        time.sleep(0.5)
        size = os.path.getsize(beat)
        time.sleep(1)
        self.assertEqual(os.path.getsize(beat), size, "the tested program is still running")

    def test_a_program_that_leaves_something_running_with_its_output_open_does_not_hang_the_run(self):
        # e.g. os.system("start /b ..."): the program ends, what it started keeps its output pipe open
        stop = os.path.join(self.dir, "stop")
        # (the child leaves the test's folder, so that can be removed)
        child = "import os, tempfile, time\nos.chdir(tempfile.gettempdir())\nfor _ in range(300):\n" \
                "    if os.path.exists(%r): break\n    time.sleep(0.1)\n" % stop
        code = "import subprocess, sys\nprint(3)\nsys.stdout.flush()\n" \
               "subprocess.Popen([sys.executable, '-c', %r], stdout=sys.stdout, stderr=sys.stderr)\n" % child
        start = time.time()
        try:
            results = run_tests(sys.executable, self.program(code), [{"input": "", "output": "3\n"}] * 2, 10)
        finally:
            open(stop, "w").close()  # the left-over children end
            time.sleep(0.5)
        self.assertEqual([r["verdict"] for r in results], ["PASS", "PASS"])
        self.assertLess(time.time() - start, 12)

    def test_a_program_runs_in_a_new_empty_folder_not_in_thonnys_working_folder(self):
        # a program that writes a file must not write it into Thonny's folder, or fail because it can't
        results = run_tests(sys.executable, self.program("import os\nprint(os.getcwd())\nprint(os.listdir('.'))\n"),
                            [{"input": "", "output": ""}], 10)
        cwd, listing = results[0]["stdout"].split("\n")[:2]
        self.assertNotEqual(os.path.normcase(cwd), os.path.normcase(os.getcwd()))
        self.assertNotEqual(os.path.normcase(cwd), os.path.normcase(self.dir))
        self.assertEqual(listing, "[]")
        self.assertFalse(os.path.exists(cwd))

    def test_output_on_stderr_and_a_lot_of_output(self):
        results = run_tests(sys.executable, self.program("import sys\nprint('x' * 3000000)\nprint('oops', file=sys.stderr)\n"),
                            [{"input": "", "output": "x"}], 10)
        self.assertEqual(results[0]["verdict"], "FAIL")
        self.assertIn("oops", results[0]["stderr"])

    def test_a_run_folder_still_in_use_is_removed_once_it_is_free_not_left_behind(self):
        busy = tempfile.mkdtemp(prefix="ice-grader-test-busy-")
        open(os.path.join(busy, "x.txt"), "w").close()
        # a program whose working folder it is, still running for a moment (like one killed that hasn't quite ended)
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1)"], cwd=busy)
        time.sleep(0.3)
        runner._remove_dir(busy, 1.5)
        child.wait()
        time.sleep(2.5)
        self.assertFalse(os.path.exists(busy), "the folder is still there")


if __name__ == "__main__":
    unittest.main()

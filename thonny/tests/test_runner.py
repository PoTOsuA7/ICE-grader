"""Really runs Python programs against tests."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from thonnycontrib.ice_grader import runner
from thonnycontrib.ice_grader.runner import run_tests


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

    def test_output_on_stderr_and_a_lot_of_output(self):
        results = run_tests(sys.executable, self.program("import sys\nprint('x' * 3000000)\nprint('oops', file=sys.stderr)\n"),
                            [{"input": "", "output": "x"}], 10)
        self.assertEqual(results[0]["verdict"], "FAIL")
        self.assertIn("oops", results[0]["stderr"])


if __name__ == "__main__":
    unittest.main()

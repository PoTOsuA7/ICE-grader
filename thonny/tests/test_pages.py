"""Reading the grader's pages and comparing outputs (same cases as the VS Code extension's tests)."""
import types
import unittest

from thonnycontrib.ice_grader.client import (decode_entities, parse_data_files, parse_problem_list, parse_submission_page,
                                             parse_submission_source, parse_submit_form, parse_testcase_page, tile_passed)
from thonnycontrib.ice_grader import MAX_LINE, GraderResultsView, clip_line, last_submit_text, summary_text
from thonnycontrib.ice_grader.diff import checked_part, code_hash, compared_outputs, first_difference, normalize, visible
from thonnycontrib.ice_grader.layout import chapter_of, is_exam, safe_name, solution_path
from thonnycontrib.ice_grader.runner import last_submit_on


def row(pid, code, status, score, sub):
    link = '<a data-turbo="false" href="/submissions/%s">%s</a>' % (sub, sub) if sub else "-"
    return """<tr>
<td class='text-end' data-order='1'><div>1</div></td>
<td><div class='d-flex align-items-center'><strong>
%s_&ZeroWidthSpace;Name &amp; Co
</strong></div>
<div class='text-muted font-monospace'>
%s
</div>
<a href="/problems/%s/download/statement">Read</a> <a class="link-flex" href="/testcases/show_problem/%s">Testcases</a>
</td>
<td data-order='%s' style='width: 12em; vertical-align: middle'><div class='progress'></div></td>
<td>%s</td>
<td>%s</td>
</tr>""" % (code, code, pid, pid, score, link, status)


def field(label, value):
    return "<div class='row mb-2'>\n<div class='col-4 text-end text-secondary'>\n%s\n</div>\n<div class='col'>\n%s\n</div>\n</div>" % (label, value)


def tile(n, total, label, letter):
    return '<span class="verdict-tile" title="Test %d of %d: %s">%s</span>' % (n, total, label, letter)


def tc_file(label, size, text):
    return """<div class='col-md-6'>
<div class='d-flex align-items-center justify-content-between flex-wrap gap-2 mb-1'>
<h6 class='mb-0'>%s</h6>
<div class='d-flex align-items-center gap-2'>
<span class='text-secondary small'>%s</span>
</div>
</div>
<textarea class='form-control font-monospace small' readonly rows='20' spellcheck='false'>%s</textarea>
</div>""" % (label, size, text)


def pane(pid, inp, out):
    return "<div class='tab-pane' id='tc%s' role='tabpanel'>\n<div class='row g-3'>\n%s\n%s\n</div>\n</div>" % (
        pid, tc_file("Input", *inp), tc_file("Expected output", *out))


def page(*panes, data=""):
    return ("<span class='badge'>\n<span class='mi md-18'>content_cut</span>\nShowing the first 2 KB of each file\n</span>\n"
            "<div class='tab-content'>%s</div>%s" % ("\n".join(panes), data))


FORM = """<form action="/main/submit" method="post"><input type="hidden" name="authenticity_token" value="tok&#43;en" autocomplete="off" />
<input type="hidden" name="submission[problem_id]" id="submission_problem_id" value="892" autocomplete="off" />
<select id="language_id" name="language_id"><option value="6">Python</option><option value="2">C++</option></select></form>"""


class Pages(unittest.TestCase):
    def test_problem_list_reads_status_score_submission_and_cleans_names(self):
        html = "<table><tbody><!-- x -->%s%s%s</tbody></table>" % (
            row(10, "05_List_11", "solved", "100.0", "555"), row(11, "05_List_12", "inprogress", "40.0", "556"),
            row(12, "05_List_13", "untried", "0", None))
        problems = parse_problem_list(html)
        self.assertEqual([p["status"] for p in problems], ["solved", "inprogress", "untried"])
        self.assertEqual([p["score"] for p in problems], [100, 40, 0])
        self.assertEqual([p["last_submission_id"] for p in problems], ["555", "556", None])
        self.assertEqual(problems[0]["id"], "10")
        self.assertEqual(problems[0]["code"], "05_List_11")
        self.assertIn("Name & Co", problems[0]["name"])
        self.assertTrue(all(p["has_testcases"] for p in problems))

    def test_submission_page(self):
        html = (field("Points", "60.0/100") + field("Result", tile(1, 2, "Correct", "P") + tile(2, 2, "Wrong answer", "-"))
                + field("Runtime", "<span>0.014</span>\n<span class='x'>s</span>") + field("Grading Task Status", "done"))
        g = parse_submission_page(html)
        self.assertEqual((g["points"], g["max"], g["done"], g["readable"], g["runtime"]), (60, 100, True, True, "0.014 s"))
        self.assertEqual([(t["n"], t["label"]) for t in g["tests"]], [(1, "Correct"), (2, "Wrong answer")])
        still = parse_submission_page(field("Grading Task Status", "processing"))
        self.assertEqual((still["done"], still["status"]), (False, "processing"))
        self.assertFalse(parse_submission_page("<html>login</html>")["readable"])

    def test_submitted_code_is_read_exactly_with_its_language(self):
        html = ("<textarea data-editor-target='source' id='text_sourcecode' style='display:none'>if a &lt; b and s == &quot;x&quot;:\n"
                "    print(&#39;&amp;&#39;)\n</textarea>\n" + field("Language", "Python"))
        self.assertEqual(parse_submission_source(html), {"source": "if a < b and s == \"x\":\n    print('&')\n", "language": "Python"})
        self.assertTrue(parse_submission_source(html.replace("none'>", "none'>\n"))["source"].startswith("if a"))
        self.assertIsNone(parse_submission_source('<form action="/login/login"><input name="password"></form>'))

    def test_submit_form(self):
        f = parse_submit_form(FORM)
        self.assertEqual(f, {"token": "tok+en", "problem_id": "892",
                             "languages": [{"id": "6", "name": "Python"}, {"id": "2", "name": "C++"}]})

    def test_tests_from_the_page_decoding_entities(self):
        cases = parse_testcase_page(page(pane(1, ("3 Bytes", "toy"), ("5 Bytes", "toys\n")),
                                         pane(2, ("5 Bytes", "a &lt; b"), ("4 Bytes", "yes\n"))))
        self.assertEqual([(c["id"], c["input"], c["output"], c["input_cut"], c["output_cut"]) for c in cases],
                         [("1", "toy", "toys\n", False, False), ("2", "a < b", "yes\n", False, False)])

    def test_newline_after_textarea_dropped_only_when_the_size_proves_it_is_extra(self):
        [c] = parse_testcase_page(page(pane(1, ("1 Byte", "\n5"), ("2 Bytes", "\n\n"))))
        self.assertEqual((c["input"], c["output"]), ("5", "\n\n"))

    def test_a_file_bigger_than_shown_is_cut(self):
        [c] = parse_testcase_page(page(pane(1, ("50 KB", "x" * 2048), ("3 Bytes", "ok\n"))))
        self.assertEqual((c["input_cut"], c["output_cut"]), (True, False))

    def test_a_character_number_that_is_no_character_becomes_u_fffd_like_in_a_browser(self):
        self.assertEqual(decode_entities("&#x110000;&#xD800;&#0;&#99999999999;&#65;&#x42;&#๑;"),
                         "����AB&#๑;")
        [c] = parse_testcase_page(page(pane(1, ("3 Bytes", "&#xD800;"), ("2 Bytes", "ok"))))  # no UnicodeEncodeError
        self.assertEqual(c["input"], "�")
        self.assertEqual(len(parse_problem_list("<table>%s</table>" % row(10, "x", "solved", "1", None).replace("Name", "&#x110000;"))), 1)

    def test_only_ascii_digits_and_a_malformed_number_does_not_stop_the_page_being_read(self):
        # the same as the VS Code version: Thai digits are no id, and "5.5.5" reads as 5.5 (JavaScript's parseFloat)
        self.assertEqual(parse_problem_list("<table>%s</table>" % row("๑๒", "x", "solved", "1", None)), [])
        [p] = parse_problem_list("<table>%s</table>" % row(10, "x", "inprogress", "5.5.5", "๑"))
        self.assertEqual((p["score"], p["last_submission_id"]), (5.5, None))
        g = parse_submission_page(field("Points", "1.2.3/10") + '<span title="Test ๑ of 2: x">P</span>')
        self.assertEqual((g["points"], g["max"], g["tests"]), (1.2, 10, []))

    def test_a_tile_is_a_pass_only_for_a_passed_test(self):
        tiles = [("Correct", "P"), ("Incorrect", "-"), ("Wrong answer", ""), ("Correct", ""), ("Time limit", "T")]
        self.assertEqual([tile_passed({"label": label, "letter": letter}) for label, letter in tiles],
                         [True, False, False, True, False])

    def test_data_files_are_read_but_not_taken_as_a_test(self):
        data = "<div id='data-files'>%s</div>" % tc_file("data.txt", "6 Bytes", "1\n2\n3\n")
        html = page(pane(1, ("15 Bytes", "/data/data.txt\n"), ("2 Bytes", "6\n")), data=data)
        self.assertEqual(len(parse_testcase_page(html)), 1)
        self.assertEqual(parse_data_files(html), [{"name": "data.txt", "text": "1\n2\n3\n", "cut": False}])


class Compare(unittest.TestCase):
    def test_lenient_like_the_grader(self):
        self.assertEqual(normalize("a  \r\nb\t\n\n\n"), "a\nb")
        self.assertNotEqual(normalize("Hello  Python."), normalize("Hello Python."))

    def test_first_difference(self):
        d = first_difference("Hello  Python.\n", "Hello Python.\n")
        self.assertEqual((d["line"], d["kind"], d["index"], d["spacing_only"]), (1, "differs", 6, True))
        self.assertEqual(first_difference("1\n2\n", "1\n")["kind"], "missing")
        self.assertEqual(first_difference("1\n", "1\n2\n")["kind"], "extra")
        self.assertIsNone(first_difference("1\n", "1  \n\n"))
        self.assertEqual(visible("a b\t"), "a·b→")

    def test_a_form_feed_or_other_control_character_is_shown_and_is_no_spacing_mistake(self):
        # os.system("cls") with no console prints a form feed: "differs only in spaces: expected 3, you printed 3"
        self.assertFalse(first_difference("3\n", "\f3\n")["spacing_only"])
        self.assertEqual(visible("\f3\x00\x1b[0m\x07\b\x7f\r"), "␌3␀␛[0m␇␈␡␍")  # the same as the VS Code version
        self.assertTrue(first_difference("a \t b", "  a b")["spacing_only"])
        self.assertFalse(first_difference("a b", "a b")["spacing_only"])
        text = panel_text("FAIL", "\f3\n", output="3\n")
        self.assertIn("differs at column 1: expected '3', you printed '\\x0c3'", text)

    def test_cut_expected_output_checks_the_part_that_is_shown(self):
        tc = {"output": "1\n2\n34", "partial_output": True}
        self.assertEqual(compared_outputs(tc, "1\n2\n345\n6\n"), {"expected": "1\n2\n3", "actual": "1\n2\n3"})
        self.assertTrue(compared_outputs({"output": "x", "partial_output": True}, "y")["unchecked"])

    def test_a_split_thai_character_crlf_and_trailing_spaces_never_fail_a_right_answer(self):
        thai = "สวัสดีครับ"  # each character is 3 bytes in UTF-8
        for rest in ("�", "��", ""):
            tc = {"output": "1\n" + thai[:4] + rest, "partial_output": True}
            cmp = compared_outputs(tc, "1\n%s\n2\n" % thai)
            self.assertEqual(cmp["expected"], cmp["actual"], repr(rest))
            self.assertNotEqual(compared_outputs(tc, "1\n%s\n" % thai.replace("ว", "า"))["actual"], cmp["expected"])
        right = compared_outputs({"output": "a  \r\nb\r\ncde", "partial_output": True}, "a\nb   \ncdefg\n")
        self.assertEqual(right["expected"], right["actual"])
        self.assertEqual(checked_part("a\r\nbc\r"), "line 1 and the start of line 2")
        space = {"output": "0\n1 2 3", "partial_output": True}  # cut just after a space mid-line
        for mine in ("0\n1 2\n", "0\n1 2 3 4\n"):
            c = compared_outputs(space, mine)
            self.assertEqual(normalize(c["expected"]), normalize(c["actual"]), mine)
        wrong = compared_outputs(space, "0\n1 23\n")
        self.assertNotEqual(normalize(wrong["expected"]), normalize(wrong["actual"]))

    def test_says_which_lines_of_a_cut_off_expected_output_were_checked(self):
        self.assertEqual(checked_part("a\nb\nc\nd-cut"), "lines 1-3 and the start of line 4")
        self.assertEqual(checked_part("a\nb-cut"), "line 1 and the start of line 2")
        self.assertEqual(checked_part("one long line, cut"), "the start of line 1")
        self.assertEqual(checked_part("a\nb\nc\n"), "lines 1-2")  # the last line isn't trusted to be complete

    def test_a_fingerprint_of_the_code_that_ignores_line_endings_trailing_spaces_and_a_byte_order_mark(self):
        h = code_hash("n = int(input())\nprint(n)\n")
        self.assertEqual(h, code_hash("﻿n = int(input())  \r\nprint(n)\r\n\r\n"))
        self.assertNotEqual(h, code_hash("n = int(input())\nprint(n + 1)\n"))
        # the VS Code extension computes the same (extension/tests/testcases.test.js)
        self.assertEqual(code_hash("print(1)\n"), "d287bb7f9d15abdc5b6e98536263815744b6ef21c8f3c839fc434ca70d8efe99")


class Skipped(unittest.TestCase):
    """A test the grader shows too little of to check here: the verdict from your last submission instead."""
    SUB = {"id": "700", "code": code_hash("print(1)"),
           "tests": [{"n": 1, "total": 2, "label": "Correct", "letter": "P"},
                     {"n": 2, "total": 2, "label": "Wrong answer", "letter": "-"}]}

    def test_the_verdict_of_the_last_submission_by_test_number(self):
        self.assertEqual(last_submit_on(self.SUB, 1, 2, code_hash("print(1)\n")),
                         {"id": "700", "label": "Wrong answer", "same": True})
        self.assertEqual(last_submit_on(self.SUB, 0, 2, code_hash("print(2)")), {"id": "700", "label": "Correct", "same": False})
        self.assertIsNone(last_submit_on(dict(self.SUB, code=None), 0, 2, "h")["same"])  # code not known
        self.assertIsNone(last_submit_on(self.SUB, 0, 3, "h"))  # graded on other tests than shown here
        self.assertIsNone(last_submit_on(self.SUB, 2, 2, "h"))
        self.assertIsNone(last_submit_on(None, 0, 2, "h"))
        self.assertIsNone(last_submit_on({"id": "1", "tests": []}, 0, 2, "h"))  # e.g. a compile error

    def test_short_text_and_never_counted_as_passed(self):
        self.assertEqual(last_submit_text({"id": "700", "label": "Correct", "same": True}),
                         "Last submit #700 (this same code): Correct.")
        self.assertEqual(last_submit_text({"id": "700", "label": "Wrong answer.", "same": False}),
                         "Last submit #700 (different code): Wrong answer. Submit to check this version.")
        self.assertEqual(last_submit_text({"id": "7", "label": "Correct", "same": None}), "Last submit #7: Correct.")
        self.assertEqual(last_submit_text(None), "Submit to check it.")
        skip = {"verdict": "SKIP", "last_submit": {"id": "7", "label": "Correct", "same": True}}
        self.assertEqual(summary_text([{"verdict": "PASS"}, skip]), ("1 of 1 passed (1 skipped)", "PASS"))
        self.assertEqual(summary_text([{"verdict": "FAIL"}, {"verdict": "PASS"}]), ("1 of 2 passed", "FAIL"))
        self.assertEqual(summary_text([skip]), ("0 of 0 passed (1 skipped)", "FAIL"))


def panel_text(verdict, stdout="", stderr="", output="ok\n"):
    """What the Test Results panel shows for a test, without a display."""
    out = []
    view = types.SimpleNamespace(total=1, write=lambda s, *tags: out.append(s))
    GraderResultsView.add(view, 0, {"input": "1\n", "output": output}, {"verdict": verdict, "ms": 5, "stdout": stdout, "stderr": stderr})
    return "".join(out)


class ResultsText(unittest.TestCase):
    def test_one_huge_line_is_cut_to_a_readable_length(self):
        # print("x" * 50_000_000, end=""): the runner keeps 1 MiB of it, and Tk takes hours to lay out such a line
        text = panel_text("FAIL", "x" * (1 << 20))
        self.assertLess(max(map(len, text.split("\n"))), 2 * MAX_LINE)
        self.assertIn("x" * MAX_LINE + " ... (%d more characters)" % ((1 << 20) - MAX_LINE), text)
        text = panel_text("RE", stderr="Traceback:\nValueError: " + "y" * 500000)
        self.assertLess(max(map(len, text.split("\n"))), 2 * MAX_LINE)
        self.assertIn("ValueError: yyy", text)
        self.assertIn("more characters)", text)

    def test_a_long_line_shows_where_it_differs(self):
        text = panel_text("FAIL", "a" * 5000 + "c" + "z" * 5000, output="a" * 5000 + "b" + "z" * 5000)
        self.assertLess(max(map(len, text.split("\n"))), 3 * MAX_LINE)
        self.assertIn("differs at column 5001: expected (4980 characters) ... '%s" % ("a" * 20 + "b"), text)
        self.assertIn("you printed (4980 characters) ... '%s" % ("a" * 20 + "c"), text)
        self.assertIn("z' ... (4721 more characters)", text)
        self.assertEqual(clip_line("short", 40, repr), "'short'")
        self.assertEqual(clip_line("z" * (MAX_LINE + 5), 9999), "(5 characters) ... " + "z" * MAX_LINE)


class Layout(unittest.TestCase):
    def test_chapters_and_files(self):
        self.assertEqual(chapter_of("05_List_15"), "05_List")
        self.assertEqual(chapter_of("2025s1_Exam2_A1-1_Student"), "Exam2")
        self.assertEqual(chapter_of("Exam1-2024_Q1A_student"), "Exam1")
        self.assertEqual(chapter_of("Example_1"), "Example_1")
        self.assertEqual(safe_name(".."), "problem")
        self.assertEqual(safe_name("a/b c"), "a_b_c")
        self.assertTrue(solution_path("root", "05_List_15").replace("\\", "/").endswith("root/05_List/05_List_15.py"))

    def test_no_name_ends_in_a_dot_or_is_a_windows_device_name(self):
        # the same names as the VS Code version's safeName
        self.assertEqual(safe_name("trailing."), "trailing")
        self.assertEqual(safe_name("a_."), "a")
        self.assertEqual([safe_name(c) for c in ("NUL", "con.py", "COM1", "lpt9", "aux")], ["_NUL", "_con.py", "_COM1", "_lpt9", "_aux"])
        self.assertEqual([safe_name(c) for c in ("Console_01", "NULL", "com10", "05_NUL_01")], ["Console_01", "NULL", "com10", "05_NUL_01"])
        self.assertTrue(solution_path("root", "CON").replace("\\", "/").endswith("root/_CON/_CON.py"))

    def test_exams_by_ascii_letters_and_digits_only(self):
        # like the VS Code version: a Thai digit is no exam number, the Kelvin sign is no "k"
        self.assertEqual(chapter_of("Exam_๒"), "Exam")
        self.assertTrue(is_exam("Kexam"))
        self.assertEqual(chapter_of("Kexam_1"), "Exam1")


if __name__ == "__main__":
    unittest.main()

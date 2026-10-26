"""Output comparison shared by the runner (verdict) and the results view (explaining a mismatch)."""
import hashlib
import re


def norm_lines(s):
    """Same leniency as the grader: ignore CRLF, trailing spaces per line, trailing blank lines."""
    lines = [re.sub(r"[ \t]+$", "", line) for line in re.sub(r"\r\n?", "\n", s).split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def normalize(s):
    return "\n".join(norm_lines(s))


def first_difference(expected, actual):
    """None when equal, else {line, kind: 'missing'|'extra'|'differs', expected?, actual?, index?, spacing_only?}"""
    e = norm_lines(expected)
    a = norm_lines(actual)
    for i in range(max(len(e), len(a))):
        ei = e[i] if i < len(e) else None
        ai = a[i] if i < len(a) else None
        if ei == ai:
            continue
        if ei is None:
            return {"line": i + 1, "kind": "extra", "actual": ai}
        if ai is None:
            return {"line": i + 1, "kind": "missing", "expected": ei}
        index = 0
        while index < len(ei) and index < len(ai) and ei[index] == ai[index]:
            index += 1

        def collapse(s):
            return re.sub(r"\s+", " ", s).strip()

        return {"line": i + 1, "kind": "differs", "expected": ei, "actual": ai, "index": index,
                "spacing_only": collapse(ei) == collapse(ai)}
    return None


def visible(s):
    """Make whitespace visible so "Hello  Python." vs "Hello Python." can be seen."""
    return s.replace(" ", "·").replace("\t", "→").replace("\r", "␍")


def _shown_part(output):
    """The part of a cut-off expected output that can be checked: its complete lines, and the start of the last line,
    which may be cut mid-way. The 2 KB cut can split a multi-byte character (Thai, ...), leaving one or more "�":
    those are dropped, then one more character, in case the cut left anything else half-written."""
    shown = norm_lines(output)
    cut = (shown[-1] if shown else "").rstrip("�")[:-1]
    return shown[:-1], cut


def checked_part(output):
    """What of a cut-off expected output is checked, in words: "lines 1-36 and the start of line 37"."""
    complete, cut = _shown_part(output)
    n = len(complete)
    parts = ["lines 1-%d" % n if n > 1 else "line 1" if n else "", "the start of line %d" % (n + 1) if cut else ""]
    return " and ".join(p for p in parts if p)


def compared_outputs(tc, actual):
    """What to compare for a test. When only the first part of the expected output is known (partial_output),
    check the complete lines of that part against the same lines of the program's output, and the last visible
    line (which may be cut mid-way) as the start of the program's next line. -> {expected, actual, unchecked?}
    unchecked: nothing of the expected output is known, so any output would "match"."""
    if not tc.get("partial_output"):
        return {"expected": tc["output"], "actual": actual}
    complete, cut = _shown_part(tc["output"])
    if not complete and not cut:
        return {"expected": "", "actual": "", "unchecked": True}
    mine = norm_lines(actual)
    expected = complete + [cut] if cut else complete
    got = mine[:len(complete)]
    if cut and len(mine) > len(complete):
        got.append(mine[len(complete)][:len(cut)])
    return {"expected": "\n".join(expected), "actual": "\n".join(got)}


def code_hash(source):
    """A fingerprint of a program's code, to tell whether a submission was this same code. Line endings, trailing
    spaces, blank lines at the end and a byte order mark don't count."""
    if source.startswith("﻿"):
        source = source[1:]
    return hashlib.sha256(normalize(source).encode("utf-8")).hexdigest()

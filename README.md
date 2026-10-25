# ICE Grader

The NatteeGrader website (Chula 2190101) inside your editor: read the problems, run the grader's tests and submit
without leaving it. There are two versions:

| | Install | Details |
|---|---|---|
| **VS Code** (and Cursor, Windsurf, VSCodium) | [VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=potosua7.nattee-grader), [Open VSX](https://open-vsx.org/extension/potosua7/nattee-grader) | [extension/](extension/README.md) |
| **Thonny** | Tools > Manage plug-ins, search `thonny-ice-grader` ([PyPI](https://pypi.org/project/thonny-ice-grader/)) | [thonny/](thonny/README.md) |

Both have the problem list with your progress, statements beside your code, tests when you save (PASS / FAIL / TLE /
RE and the first difference), submit, AI explain (Google's Gemini, with your own key), offline use and download all.
The VS Code version also has C/C++, run one test or your own input, and a mock exam.

## Development
- `extension/`: the VS Code extension. Test with `node --test` in `extension/`; build the `.vsix` with
  `python tools/build_vsix.py`. Each release's `.vsix` is on [Releases](https://github.com/PoTOsuA7/ICE-grader/releases).
- `thonny/`: the Thonny plug-in (`thonny-ice-grader`). Test with `python -m unittest discover -s tests` in `thonny/`
  (needs `pypdfium2`); publish with `python tools/publish_pypi.py`.

## License
MIT. The VS Code extension bundles pdf.js (Apache-2.0), see `THIRD_PARTY_NOTICES.md`. The Thonny plug-in uses
pypdfium2 (Apache-2.0 / BSD-3-Clause) and keyring (MIT).

Unofficial student tool. It only reads what your own grader account can see and keeps it on your computer.
Check your course's rules before using it.

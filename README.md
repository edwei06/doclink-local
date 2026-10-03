# doclink-local

Catch broken file and image paths in Markdown before publishing a repository.

A renamed screenshot or moved guide can break a README even when every external
website is reachable. This small CLI parses CommonMark, checks local destinations
inside a chosen repository boundary, and makes no network requests. Installation
requires Python 3.10+ and the `markdown-it-py` parser; execution is offline.

## Quick start

~~~sh
python -m pip install .
doclink-local --root . README.md docs
doclink-local --root . --exclude "examples/broken/*" --format json
~~~

Paths passed on the command line are relative to `--root`, not the current
directory. Omit paths to scan all `.md` and `.markdown` files under the root.

Try the bundled passing and failing examples:

~~~sh
doclink-local --root examples good/README.md
doclink-local --root examples broken/README.md
~~~

The second command reports two missing destinations and exits with status 1.

## What it checks

- Inline links, images, resolved reference links, and links in Markdown tables.
- Raw HTML `href`, `src`, and `poster` attributes.
- Percent-encoded paths, spaces, Unicode filenames, and relative parent paths.
- File or directory existence; queries and fragments are removed before lookup.
- Paths escaping the root, including symlinks targeting outside it.
- Absolute `file:` URLs as portability issues.

Inline code, fenced/indented code, HTML comments, and remote URLs are skipped.
The report shows the containing Markdown block's starting line, which may precede
the link on a later line of the same paragraph.

Root-relative links such as `/guide.md` are counted as skipped by default because
many sites treat them as routes. Use `--root-relative` to interpret them as files
relative to the declared root.

## Options and exit status

| Option | Purpose |
| --- | --- |
| `--root PATH` | Set the scan boundary (default: current directory) |
| `--exclude GLOB` | Exclude a project-relative file/directory glob; repeatable |
| `--root-relative` | Check destinations starting with / against the root |
| `--max-issues N` | Cap reported samples (default: 100); totals remain complete |
| `--max-bytes N` | Limit each input document (default: 4 MiB) |
| `--format text\|json` | Select human-readable or structured output |

Exit 0 means all checked local paths exist; 1 means findings; 2 means an input,
encoding, size-limit, or filesystem error prevented a complete check. Empty
selections are errors. Default scanning prunes `.git`, virtual environments,
`node_modules`, `__pycache__`, `build`, and `dist`. Symlink directories are
not traversed, and symlink Markdown sources are rejected.

## Scope

This is a repository file-path check, not a web crawler. It does not validate
heading anchors, external HTTP status, undefined reference labels, static-site
extension rewrites, JavaScript-generated links, HTML `srcset`, template syntax,
or GitHub's exact case/Unicode behavior. Directory targets are accepted.
Case-sensitive deployment issues may therefore need additional CI on Linux.
The root boundary is a correctness check, not a filesystem security sandbox.

The parser dependency avoids a custom regular-expression Markdown grammar.
There are no API keys, telemetry, browser sessions, or HTTP clients.

## Development

~~~sh
python -m pip install -e .
python -m unittest discover -s tests -v
~~~

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and [LICENSE](LICENSE).
The GitHub Actions matrix targets Windows and Ubuntu with Python 3.10 and 3.13.

Related work includes [link-verifier](https://github.com/bmuschko/link-verifier)
and [linkchecker-markdown](https://github.com/scivision/linkchecker-markdown).
This project narrows the task to local repository paths and uses an independently
written implementation.

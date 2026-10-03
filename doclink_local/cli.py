"""Command-line interface for offline documentation checks."""
import argparse
import json
import sys

from . import __version__
from .core import DoclinkError, check_documents


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Expected a positive integer")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check local Markdown links and assets without network requests.")
    parser.add_argument("paths", nargs="*", help="Files/directories relative to --root; defaults to the root")
    parser.add_argument("--root", default=".", help="Repository boundary")
    parser.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                        help="Exclude project-relative paths with a glob (repeatable)")
    parser.add_argument("--root-relative", action="store_true",
                        help="Interpret /path links relative to --root; otherwise skip them")
    parser.add_argument("--max-issues", type=positive, default=100)
    parser.add_argument("--max-bytes", type=positive, default=4 * 1024 * 1024,
                        help="Maximum size of each Markdown document")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    try:
        report = check_documents(args.root, args.paths, excludes=args.exclude,
                                 root_relative=args.root_relative, max_issues=args.max_issues,
                                 max_bytes=args.max_bytes)
    except (DoclinkError, OSError, RuntimeError) as error:
        print(f"doclink-local: {error}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        for issue in report["issues"]:
            print(f"{issue['source']}: block at line {issue['block_line']}: "
                  f"{issue['code']}: {issue['url']}")
        print(f"{report['files_scanned']} file(s), {report['local_links_checked']} local link(s), "
              f"{report['issues_total']} issue(s); "
              f"{report['external_links_skipped']} external and "
              f"{report['root_relative_skipped']} root-relative link(s) skipped")
        if report["issues_truncated"]:
            print("Issue list capped; totals cover all selected documents")
    return 0 if report["ok"] else 1

"""Check parsed local Markdown destinations without requesting any URL."""
import fnmatch
from html.parser import HTMLParser
import os
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

EXCLUDED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist"}
MARKDOWN_SUFFIXES = {".md", ".markdown"}


class DoclinkError(ValueError):
    """An input or filesystem failure prevents a complete check."""


class AssetLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in {"href", "src", "poster"} and value is not None:
                self.links.append(value)

    handle_startendtag = handle_starttag


def destinations(text):
    """Yield (URL, containing block's starting line), including HTML attributes."""
    parser = MarkdownIt("commonmark").enable("table")
    # We only parse, never render: recognize file: destinations for diagnostics.
    parser.validateLink = lambda value: True
    for token in parser.parse(text):
        line = token.map[0] + 1 if token.map else 1
        candidates = token.children or [token]
        for item in candidates:
            if item.type == "link_open":
                yield item.attrGet("href") or "", line
            elif item.type == "image":
                yield item.attrGet("src") or "", line
            elif item.type in {"html_inline", "html_block"}:
                html = AssetLinks()
                html.feed(item.content)
                for url in html.links:
                    yield url, line


def _inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def discover(root, paths=(), excludes=()):
    """Return deterministic sources; never descend into symlink directories."""
    sources = set()

    def excluded(path):
        relative = path.relative_to(root).as_posix()
        return any(fnmatch.fnmatchcase(relative, pattern) for pattern in excludes)

    def add(path):
        if path.suffix.lower() not in MARKDOWN_SUFFIXES or excluded(path):
            return
        if path.is_symlink():
            raise DoclinkError(f"Markdown source is a symlink: {path.relative_to(root)}")
        if not _inside(path.resolve(), root):
            raise DoclinkError("Markdown source resolves outside the root")
        sources.add(path)

    def walk_error(error):
        raise DoclinkError("Unable to scan a Markdown directory") from error

    for item in paths or [root]:
        candidate = Path(item)
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate = Path(os.path.abspath(candidate))
        if not _inside(candidate, root) or not _inside(candidate.resolve(), root):
            raise DoclinkError("Selected source must remain inside the root")
        if candidate.is_symlink():
            raise DoclinkError("Selected source must not be a symlink")
        if candidate.is_file():
            if candidate.suffix.lower() not in MARKDOWN_SUFFIXES:
                raise DoclinkError("Selected file must have a .md or .markdown extension")
            add(candidate)
        elif candidate.is_dir():
            for directory, dirs, names in os.walk(candidate, onerror=walk_error, followlinks=False):
                parent = Path(directory)
                dirs[:] = sorted(name for name in dirs
                                 if name not in EXCLUDED_DIRS
                                 and not (parent / name).is_symlink()
                                 and not excluded(parent / name))
                for name in sorted(names):
                    add(parent / name)
        else:
            raise DoclinkError("Selected source does not exist")
    if not sources:
        raise DoclinkError("No Markdown files selected")
    return sorted(sources)


def _target(url, source, root, root_relative):
    """Return a check category and optional resolved path."""
    if not url or url.startswith("#"):
        return "fragment", None
    if re.match(r"^[a-zA-Z]:[\\/]", url) or url.startswith("\\"):
        return "absolute_local", None
    try:
        parts = urlsplit(url)
        if parts.scheme.lower() == "file":
            return "absolute_local", None
        if parts.scheme or parts.netloc or url.startswith("//"):
            return "external", None
        decoded = unquote(parts.path, errors="strict")
    except (ValueError, UnicodeError):
        return "invalid_url", None
    if not decoded:
        return "fragment", None
    if "\x00" in decoded or "\\" in decoded:
        return "invalid_path", None
    if re.match(r"^[a-zA-Z]:", decoded):
        return "absolute_local", None
    if decoded.startswith("/"):
        if not root_relative:
            return "root_relative_skipped", None
        candidate = root / decoded.lstrip("/")
    else:
        candidate = source.parent / decoded
    try:
        resolved = candidate.resolve()
        if not _inside(resolved, root):
            return "outside_root", None
        return ("local" if resolved.exists() else "missing"), resolved
    except (OSError, ValueError, RuntimeError):
        return "unreadable_target", None


def check_documents(root, paths=(), *, excludes=(), root_relative=False,
                    max_issues=100, max_bytes=4 * 1024 * 1024):
    root = Path(root).resolve()
    if not root.is_dir():
        raise DoclinkError("Root must be an existing directory")
    if max_issues < 1 or max_bytes < 1:
        raise DoclinkError("Limits must be positive")
    try:
        sources = discover(root, paths, excludes)
        report = {"ok": True, "files_scanned": 0, "local_links_checked": 0,
                  "external_links_skipped": 0, "fragments_skipped": 0,
                  "root_relative_skipped": 0, "issues_total": 0,
                  "issues_truncated": False, "issues": []}
        for source in sources:
            with source.open("rb") as stream:
                content = stream.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise DoclinkError(f"Markdown exceeds byte limit: {source.relative_to(root)}")
            try:
                text = content.decode("utf-8-sig")
            except UnicodeError as error:
                raise DoclinkError(f"Markdown must be UTF-8: {source.relative_to(root)}") from error
            report["files_scanned"] += 1
            for url, line in destinations(text):
                category, target = _target(url, source, root, root_relative)
                if category in {"external", "fragment", "root_relative_skipped"}:
                    key = {"external": "external_links_skipped", "fragment": "fragments_skipped",
                           "root_relative_skipped": "root_relative_skipped"}[category]
                    report[key] += 1
                    continue
                report["local_links_checked"] += 1
                if category == "local":
                    continue
                report["issues_total"] += 1
                if len(report["issues"]) < max_issues:
                    report["issues"].append({"source": source.relative_to(root).as_posix(),
                                             "block_line": line, "url": url, "code": category})
        report["ok"] = report["issues_total"] == 0
        report["issues_truncated"] = report["issues_total"] > len(report["issues"])
        return report
    except OSError as error:
        raise DoclinkError("Unable to read Markdown inputs") from error

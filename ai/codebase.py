"""Linked code folders: what may be read, the file tree, languages, and which files go with a question.

Rules (from the design):
- Only folders the student linked are read, and nothing outside them (no "..", absolute paths, or links out).
- Never read or sent: secrets (.env, *.pem, *.key, id_rsa*, secrets.*), anything in .gitignore, build and
  dependency folders, binary files, and files over 200 KB. They show in the tree greyed out as "(hidden)".
- Each question sends only the files it needs (the open file, files named in an error, and files the open
  file imports), within a size budget. The student sees the list and can change it.
"""
import os
import re
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

MAX_FILE = 200 * 1024              # bytes: bigger files are skipped
MAX_ENTRIES = 3000                 # tree entries shown, so a huge folder can't stall the app
SEND_BUDGET = 60_000               # characters of code sent with one question
MAX_SEND_FILES = 8

SECRET_PATTERNS = (".env", "*.env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*",
                   "secrets.*", "*.keystore", "credentials.json")
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "env", "__pycache__", "build", "dist", "target", "bin",
             "obj", ".idea", ".vs", ".vscode", ".gradle", ".mypy_cache", ".pytest_cache", ".next", "out",
             ".tox", ".cache"}

# extension -> (language name, tier, highlight.js id). Tier 1: full, 2: run, 3: explain only (section 6.6)
LANGUAGES = {
    ".py": ("Python", 1, "python"), ".pyw": ("Python", 1, "python"), ".java": ("Java", 1, "java"),
    ".c": ("C", 1, "c"), ".h": ("C", 1, "c"), ".cpp": ("C++", 1, "cpp"), ".cc": ("C++", 1, "cpp"),
    ".cxx": ("C++", 1, "cpp"), ".hpp": ("C++", 1, "cpp"), ".hh": ("C++", 1, "cpp"), ".cs": ("C#", 1, "csharp"),
    ".js": ("JavaScript", 1, "javascript"), ".mjs": ("JavaScript", 1, "javascript"),
    ".cjs": ("JavaScript", 1, "javascript"), ".jsx": ("JavaScript", 1, "javascript"),
    ".ts": ("TypeScript", 1, "typescript"), ".tsx": ("TypeScript", 1, "typescript"),
    ".go": ("Go", 2, "go"), ".rs": ("Rust", 2, "rust"), ".kt": ("Kotlin", 2, "kotlin"),
    ".kts": ("Kotlin", 2, "kotlin"), ".scala": ("Scala", 2, "scala"), ".php": ("PHP", 2, "php"),
    ".rb": ("Ruby", 2, "ruby"), ".dart": ("Dart", 2, "dart"), ".lua": ("Lua", 2, "lua"), ".r": ("R", 2, "r"),
    ".hs": ("Haskell", 2, "haskell"), ".pl": ("Prolog", 2, "prolog"), ".pro": ("Prolog", 2, "prolog"),
    ".m": ("Octave", 2, "matlab"), ".sh": ("Bash", 2, "bash"), ".bash": ("Bash", 2, "bash"),
    ".ps1": ("PowerShell", 2, "powershell"),
    ".sql": ("SQL", 3, "sql"), ".html": ("HTML", 3, "xml"), ".htm": ("HTML", 3, "xml"), ".css": ("CSS", 3, "css"),
    ".scss": ("SCSS", 3, "scss"), ".asm": ("Assembly", 3, "x86asm"), ".s": ("Assembly", 3, "x86asm"),
    ".swift": ("Swift", 3, "swift"), ".json": ("JSON", 3, "json"), ".xml": ("XML", 3, "xml"),
    ".yml": ("YAML", 3, "yaml"), ".yaml": ("YAML", 3, "yaml"), ".toml": ("TOML", 3, "ini"),
    ".ini": ("INI", 3, "ini"), ".md": ("Markdown", 3, "markdown"), ".txt": ("Text", 3, ""),
    ".csv": ("CSV", 3, ""), ".ipynb": ("Jupyter notebook", 3, "json"), ".gradle": ("Gradle", 3, "kotlin"),
    ".vue": ("Vue", 3, "xml"), ".svelte": ("Svelte", 3, "xml"), ".tex": ("LaTeX", 3, "latex"),
    ".f90": ("Fortran", 3, "fortran"), ".jl": ("Julia", 3, "julia"), ".ml": ("OCaml", 3, "ocaml"),
    ".ex": ("Elixir", 3, "elixir"), ".erl": ("Erlang", 3, "erlang"), ".v": ("Verilog", 3, "verilog"),
    ".vhd": ("VHDL", 3, "vhdl"), ".lisp": ("Lisp", 3, "lisp"), ".scm": ("Scheme", 3, "scheme"),
}
NAMED = {"makefile": ("Makefile", 3, "makefile"), "dockerfile": ("Dockerfile", 3, "dockerfile"),
         "cmakelists.txt": ("CMake", 3, "cmake")}


class CodeError(Exception):
    """A problem to show the student in plain words."""


def language(name: str) -> dict:
    lang, tier, hl = NAMED.get(name.lower()) or LANGUAGES.get(Path(name).suffix.lower(), ("Text", 3, ""))
    return {"language": lang, "tier": tier, "highlight": hl}


# ── .gitignore ──
def _glob_regex(pattern: str) -> str:
    """One gitignore glob as a regex for a path relative to the .gitignore's folder."""
    out, i = "", 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("/**", i) and i + 3 == len(pattern):
            out += "/.*"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif c == "*":
            out += "[^/]*"
            i += 1
        elif c == "?":
            out += "[^/]"
            i += 1
        elif c == "[":
            j = pattern.find("]", i + 1)
            if j < 0:
                out += re.escape(c)
                i += 1
            else:
                body = pattern[i + 1:j].replace("\\", "\\\\")
                out += "[" + ("^" + body[1:] if body.startswith("!") else body) + "]"
                i = j + 1
        else:
            out += re.escape(c)
            i += 1
    return out


class GitIgnore:
    """The rules from .gitignore files, each relative to its own folder. Later rules win, '!' re-includes."""

    def __init__(self):
        self.rules = []                                   # (base, regex, negate, dir_only)

    def add_file(self, base: str, text: str):
        for raw in text.splitlines():
            line = raw.rstrip()
            if not line or line.startswith("#"):
                continue
            negate = line.startswith("!")
            if negate:
                line = line[1:]
            line = line.replace("\\ ", " ").replace("\\#", "#").replace("\\!", "!")
            dir_only = line.endswith("/")
            line = line.rstrip("/")
            anchored = "/" in line                         # a slash at the start or in the middle anchors it
            line = line.lstrip("/")
            if not line:
                continue
            body = _glob_regex(line)
            regex = re.compile(("^" if anchored else "^(?:.*/)?") + body + "$")
            self.rules.append((base, regex, negate, dir_only))

    def ignored(self, rel: str, is_dir: bool) -> bool:
        result = False
        for base, regex, negate, dir_only in self.rules:
            if base:
                if not rel.startswith(base + "/"):
                    continue
                sub = rel[len(base) + 1:]
            else:
                sub = rel
            if dir_only and not is_dir:
                continue
            if regex.match(sub):
                result = not negate
        return result


# ── the folder ──
class Folder:
    def __init__(self, path: str):
        self.root = Path(path).resolve()
        if not self.root.is_dir():
            raise CodeError("This folder can't be found. It may have been moved or renamed. Link it again.")
        self.ignore = GitIgnore()
        self._loaded = set()
        self._load_dir("")

    def _load_dir(self, base: str):
        """Read base/.gitignore once (rules in a subfolder's .gitignore apply inside that subfolder)."""
        if base in self._loaded:
            return
        self._loaded.add(base)
        gi = self.root.joinpath(*base.split("/"), ".gitignore") if base else self.root / ".gitignore"
        try:
            if gi.is_file():
                self.ignore.add_file(base, gi.read_text(encoding="utf-8", errors="replace")[:100_000])
        except OSError:
            pass

    def skip_reason(self, rel: str, is_dir: bool, size: int = 0) -> str:
        """Why this entry is never read or sent ("" if it can be)."""
        name = rel.rsplit("/", 1)[-1]
        low = name.lower()
        if is_dir:
            if low in SKIP_DIRS:
                return "build or dependency folder"
        else:
            if any(fnmatchcase(low, p) for p in SECRET_PATTERNS):
                return "may contain secrets"
            if size > MAX_FILE:
                return "over 200 KB"
        if self.ignore.ignored(rel, is_dir):
            return "in .gitignore"
        return ""

    def resolve(self, rel: str) -> Path:
        """A path inside the folder, refusing anything that leaves it (.., absolute paths, links out)."""
        rel = (rel or "").replace("\\", "/")
        p = PurePosixPath(rel)
        if not rel or p.is_absolute() or re.match(r"^[A-Za-z]:", rel) or ".." in p.parts:
            raise CodeError("That file is outside the linked folder.")
        full = (self.root / Path(*p.parts)).resolve()
        if full != self.root and self.root not in full.parents:
            raise CodeError("That file is outside the linked folder.")
        return full

    def check_readable(self, rel: str) -> Path:
        """The file, if it may be read and sent; otherwise a CodeError saying why not."""
        full = self.resolve(rel)
        if not full.is_file():
            raise CodeError(f"{rel} isn't in this folder any more.")
        parts = PurePosixPath(rel.replace("\\", "/")).parts
        for i in range(1, len(parts)):                    # a skipped folder hides everything in it
            self._load_dir("/".join(parts[:i - 1]))
            reason = self.skip_reason("/".join(parts[:i]), True)
            if reason:
                raise CodeError(f"{rel} is hidden ({reason}), so it isn't read or sent.")
        self._load_dir("/".join(parts[:-1]))
        reason = self.skip_reason("/".join(parts), False, full.stat().st_size)
        if reason:
            raise CodeError(f"{rel} is hidden ({reason}), so it isn't read or sent.")
        return full

    def read(self, rel: str) -> str:
        full = self.check_readable(rel)
        data = full.read_bytes()
        if b"\x00" in data[:8192]:
            raise CodeError(f"{rel} is a binary file, so it isn't read or sent.")
        return data.decode("utf-8", errors="replace").replace("\r\n", "\n")

    def tree(self) -> dict:
        """Every entry, folders first, with skipped ones marked. Skipped folders aren't opened."""
        count = 0

        def walk(directory: Path, rel: str) -> list:
            nonlocal count
            self._load_dir(rel)
            try:
                entries = sorted(os.scandir(directory), key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
            except OSError:
                return []
            out = []
            for e in entries:
                if count >= MAX_ENTRIES:
                    break
                count += 1
                path = f"{rel}/{e.name}" if rel else e.name
                if e.is_symlink():
                    try:
                        target = Path(e.path).resolve()
                    except OSError:
                        continue
                    if target != self.root and self.root not in target.parents:
                        out.append({"name": e.name, "path": path, "type": "file", "hidden": "links outside the folder"})
                        continue
                is_dir = e.is_dir()
                if is_dir:
                    reason = self.skip_reason(path, True)
                    node = {"name": e.name, "path": path, "type": "dir", "hidden": reason}
                    node["children"] = [] if reason else walk(Path(e.path), path)
                else:
                    try:
                        size = e.stat().st_size
                    except OSError:
                        continue
                    reason = self.skip_reason(path, False, size)
                    node = {"name": e.name, "path": path, "type": "file", "size": size, "hidden": reason,
                            **language(e.name)}
                out.append(node)
            return out

        children = walk(self.root, "")
        return {"name": self.root.name, "children": children, "truncated": count >= MAX_ENTRIES}

    # ── choosing what to send ──
    def referenced(self, text: str) -> list:
        """Files named in an error or question (tracebacks, compiler and runtime errors), that exist here."""
        found = []
        pats = (r'File "([^"]+)", line \d+',                          # Python
                r"\(([\w$.-]+\.(?:java|kt|scala)):\d+\)",               # Java / Kotlin stack traces
                r"([\w./\\-]+\.[A-Za-z0-9]+)[:(]\d+",                   # gcc, clang, node, C#, Go, Rust
                r"`?([\w./\\-]+\.(?:py|java|c|cpp|h|hpp|cs|js|ts|go|rs|rb|php|kt))`?")   # a file mentioned by name
        for pat in pats:
            for m in re.finditer(pat, text):
                name = m.group(1).replace("\\", "/")
                match = self._find(name)
                if match and match not in found:
                    found.append(match)
        return found

    def _find(self, name: str):
        """A relative path in this folder for a name or path from an error (absolute paths are matched by
        their end)."""
        name = name.strip().strip("'\"`")
        if not name:
            return None
        try:
            p = Path(name)
            if p.is_absolute():
                full = p.resolve()
                if self.root in full.parents:
                    return full.relative_to(self.root).as_posix()
                name = p.name
        except (OSError, ValueError):
            return None
        try:
            if self.resolve(name).is_file():
                return PurePosixPath(name).as_posix()
        except CodeError:
            pass
        base = PurePosixPath(name).name
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS]
            if base in filenames:
                rel = Path(dirpath, base).relative_to(self.root).as_posix()
                if rel.endswith(name) or "/" not in name:
                    return rel
        return None

    def imports(self, rel: str, text: str) -> list:
        """Local files the open file imports (Python, JavaScript/TypeScript, C/C++ includes, Java same folder)."""
        here = PurePosixPath(rel).parent
        found = []

        def add(candidate):
            c = PurePosixPath(candidate)
            try:
                parts = []
                for part in c.parts:
                    if part == "..":
                        if not parts:
                            return
                        parts.pop()
                    elif part != ".":
                        parts.append(part)
                path = "/".join(parts)
                if path and path != rel and self.resolve(path).is_file() and path not in found:
                    found.append(path)
            except CodeError:
                pass

        ext = PurePosixPath(rel).suffix.lower()
        if ext in (".py", ".pyw"):
            for m in re.finditer(r"^\s*(?:from\s+(\.*[\w.]*)\s+import\s+([\w, ]+)|import\s+([\w., ]+))", text, re.M):
                mods = [m.group(1)] if m.group(1) is not None else [x.strip().split(" ")[0] for x in m.group(3).split(",")]
                for mod in mods:
                    dots = len(mod) - len(mod.lstrip("."))
                    base = here
                    for _ in range(max(dots - 1, 0)):
                        base = base.parent
                    path = mod.lstrip(".").replace(".", "/")
                    if path:
                        for root in ((base,) if dots else (here, PurePosixPath("."))):
                            add(str(root / (path + ".py")))
                            add(str(root / path / "__init__.py"))
                    if m.group(1) is not None:                       # from pkg import module
                        for name in m.group(2).split(","):
                            add(str((base if dots else here) / path / (name.strip() + ".py")))
        elif ext in (".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"):
            js_import = r"""(?:import\s[^'"]*?from\s*|import\s*\(\s*|require\(\s*|import\s+)['"](\.{1,2}/[^'"]+)['"]"""
            for m in re.finditer(js_import, text):
                spec = str(here / m.group(1))
                for suffix in ("", ".js", ".ts", ".jsx", ".tsx", ".mjs", "/index.js", "/index.ts"):
                    add(spec + suffix)
        elif ext in (".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh"):
            for m in re.finditer(r'^\s*#\s*include\s+"([^"]+)"', text, re.M):
                add(str(here / m.group(1)))
        elif ext == ".java":
            for m in re.finditer(r"\b(?:new\s+|extends\s+|implements\s+|)([A-Z]\w+)\s*[.(<{ ]", text):
                add(str(here / (m.group(1) + ".java")))
        return found[:MAX_SEND_FILES]

    def choose(self, question: str, open_file: str = "", pinned: list = (), removed: list = ()) -> dict:
        """The files to send with a question: pinned first, then the open file, files named in the question,
        then the open file's imports, within the budget. Returns {files: [{path, size, why}], left_out: [...]}"""
        wanted = []                                       # (path, why)
        for p in pinned:
            wanted.append((p, "added by you"))
        if open_file:
            wanted.append((open_file, "open"))
        for p in self.referenced(question):
            wanted.append((p, "named in your message"))
        if open_file:
            try:
                for p in self.imports(open_file, self.read(open_file)):
                    wanted.append((p, f"used by {PurePosixPath(open_file).name}"))
            except CodeError:
                pass
        files, left_out, used, seen = [], [], 0, set(removed)
        for path, why in wanted:
            if path in seen:
                continue
            seen.add(path)
            try:
                text = self.read(path)
            except CodeError as e:
                left_out.append({"path": path, "why": str(e)})
                continue
            if len(files) >= MAX_SEND_FILES or used + len(text) > SEND_BUDGET:
                left_out.append({"path": path, "why": "over the size limit for one message"})
                continue
            used += len(text)
            files.append({"path": path, "size": len(text), "why": why})
        return {"files": files, "left_out": left_out, "budget": SEND_BUDGET, "used": used}

    def context(self, paths: list) -> tuple:
        """The text sent to the model for these files (with line numbers), and the paths actually sent."""
        blocks, sent, used = [], [], 0
        for path in paths[:MAX_SEND_FILES]:
            text = self.read(path)
            if used + len(text) > SEND_BUDGET:
                continue
            used += len(text)
            info = language(path)
            numbered = "\n".join(f"{n:>4}| {line}" for n, line in enumerate(text.split("\n"), 1))
            blocks.append(f"--- {path} ({info['language']}) ---\n{numbered}")
            sent.append(path)
        return "\n\n".join(blocks), sent


def link_problem(path: str, data_dir: Path) -> str:
    """Why a folder can't be linked ("" if it can): it must exist, and not be a whole drive, the home folder
    itself or EasyUniTrack's own data."""
    try:
        p = Path(path).expanduser()
        if not p.is_absolute():
            return "Choose a full folder path, like C:\\Users\\you\\Documents\\project."
        p = p.resolve()
    except (OSError, ValueError):
        return "That isn't a folder path."
    if not p.is_dir():
        return "That folder can't be found."
    if p == Path(p.anchor):
        return "Link a project folder, not a whole drive."
    if p == Path.home().resolve():
        return "Link a project folder, not your whole user folder."
    data = data_dir.resolve()
    if p == data or data in p.parents or p in data.parents:
        return "That folder holds EasyUniTrack's own data. Choose a project folder."
    return ""

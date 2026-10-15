"""Running the student's code (design section 6.4).

- Runs only on the student's click, with a command they can see and edit, in the linked folder.
- No console window pops up. On Windows each run is in a job object, so Stop ends the whole process tree,
  and closing EasyUniTrack ends anything still running. Elsewhere each run gets its own process group.
- A time limit (30 s by default), off in Keep running mode for servers and apps. Output capped at 200 KB.
- Keyboard input goes to the program's stdin.
- A cleaned copy of the environment: nothing of EasyUniTrack's (settings, tokens, its packaging paths).
- Programs started this way run outside the Store package (proved in stage 0.5), so pip and npm write to the
  student's real folders.
- Toolchains are found on the PATH; nothing is downloaded or bundled.
"""
import codecs
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

MAX_OUTPUT = 200 * 1024            # characters kept per run
DEFAULT_TIMEOUT = 30
MAX_RUNNING = 4
LOCALHOST = re.compile(r"https?://(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(?::\d{2,5})?(?:/[^\s'\"<>)]*)?")

# ── Windows: no console, and a job object so Stop ends every process the run started ──
if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")
    CREATE_NO_WINDOW = 0x08000000
    CREATE_SUSPENDED = 0x00000004
    CREATE_NEW_PROCESS_GROUP = 0x00000200

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount",
                    "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _BASIC_LIMIT(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _BASIC_LIMIT), ("IoInfo", _IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]

    def _new_job():
        job = _k32.CreateJobObjectW(None, None)
        if not job:
            raise OSError(ctypes.get_last_error(), "CreateJobObject failed")
        info = _EXTENDED_LIMIT()
        info.BasicLimitInformation.LimitFlags = 0x2000              # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            err = ctypes.get_last_error()
            _k32.CloseHandle(job)
            raise OSError(err, "SetInformationJobObject failed")
        return job


def clean_env() -> dict:
    """The student's environment without anything of EasyUniTrack's: its own settings, and the paths its
    packaging adds (which could make the student's Python or Tk load EasyUniTrack's copies)."""
    bundle = getattr(sys, "_MEIPASS", None)
    env = {}
    for k, v in os.environ.items():
        up = k.upper()
        if up.startswith(("TRACKADEMIC_", "EASYUNITRACK_", "_PYI_", "_MEIPASS")):
            continue
        if bundle and bundle in v:
            if up in ("PATH", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
                v = os.pathsep.join(p for p in v.split(os.pathsep) if bundle not in p)
            else:
                continue                                  # TCL_LIBRARY, SSL_CERT_FILE and the like
        env[k] = v
    env["PYTHONUNBUFFERED"] = "1"                         # print() shows straight away
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("FORCE_COLOR", None)                          # any value turns colour on (Python 3.13+, Node)
    env["NO_COLOR"] = "1"                                 # the output panel isn't a terminal: plain text
    return env


# ── toolchains ──
TOOLS = {   # name: (commands to look for, how to check the version)
    "python": (["python", "python3", "py"], ["--version"]),
    "java": (["java"], ["-version"]), "javac": (["javac"], ["-version"]),
    "gcc": (["gcc"], ["--version"]), "g++": (["g++"], ["--version"]), "clang": (["clang"], ["--version"]),
    "dotnet": (["dotnet"], ["--version"]), "node": (["node"], ["--version"]), "npm": (["npm"], ["--version"]),
    "tsx": (["tsx"], ["--version"]), "ts-node": (["ts-node"], ["--version"]), "tsc": (["tsc"], ["--version"]),
    "go": (["go"], ["version"]), "cargo": (["cargo"], ["--version"]), "rustc": (["rustc"], ["--version"]),
    "kotlinc": (["kotlinc"], ["-version"]), "scala": (["scala"], ["-version"]), "php": (["php"], ["--version"]),
    "ruby": (["ruby"], ["--version"]), "dart": (["dart"], ["--version"]), "lua": (["lua"], ["-v"]),
    "Rscript": (["Rscript"], ["--version"]), "runghc": (["runghc"], ["--version"]),
    "swipl": (["swipl"], ["--version"]), "octave": (["octave-cli", "octave"], ["--version"]),
    "bash": (["bash"], ["--version"]),
    "powershell": (["pwsh", "powershell"], ["-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"]),
    "mvn": (["mvn"], ["--version"]), "gradle": (["gradle"], ["--version"]), "cmake": (["cmake"], ["--version"]),
    "make": (["make", "mingw32-make"], ["--version"]), "ctest": (["ctest"], ["--version"]),
}
_tool_cache = {"at": 0.0, "tools": None}


def _probe(path: str, args: list) -> str:
    """The first line of `tool --version`, or "" if it doesn't really run (Windows' python.exe stand-in
    that only opens the Microsoft Store answers with an error instead)."""
    try:
        r = subprocess.run([path, *args], capture_output=True, text=True, timeout=8, env=clean_env(),
                           creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    out = (r.stdout or r.stderr or "").strip()
    if r.returncode != 0 and not out.lower().startswith(("java", "javac", "openjdk")):
        return ""
    if "microsoft store" in out.lower() or "was not found" in out.lower():
        return ""
    return out.splitlines()[0][:120] if out else "installed"


_found_cache = {"at": 0.0, "tools": None}


def _stand_in(path: str) -> bool:
    """Windows' app-execution aliases (python.exe in WindowsApps) may just open the Microsoft Store."""
    return os.name == "nt" and "windowsapps" in path.lower()


def available(refresh: bool = False) -> dict:
    """{name: {"path", "command"}} for the tools on the PATH. Quick: only a Store stand-in is actually run, to
    check it's real (used for suggesting commands, so the workspace opens without waiting)."""
    if not refresh and _found_cache["tools"] is not None and time.time() - _found_cache["at"] < 600:
        return _found_cache["tools"]
    env_path = clean_env().get("PATH", "")
    found = {}
    for name, (names, args) in TOOLS.items():
        for exe in names:
            path = shutil.which(exe, path=env_path)
            if path and (not _stand_in(path) or _probe(path, args)):
                found[name] = {"path": path, "command": exe}
                break
    _found_cache.update(at=time.time(), tools=found)
    return found


def toolchains(refresh: bool = False) -> dict:
    """{name: {"path", "command", "version"}} for the tools found on this PC, with their versions (checked
    all at once, and again every 10 minutes)."""
    if not refresh and _tool_cache["tools"] is not None and time.time() - _tool_cache["at"] < 600:
        return _tool_cache["tools"]
    from concurrent.futures import ThreadPoolExecutor
    tools = available(refresh)
    with ThreadPoolExecutor(max_workers=8) as pool:
        versions = dict(zip(tools, pool.map(lambda n: _probe(tools[n]["path"], TOOLS[n][1]), tools), strict=True))
    found = {n: {**t, "version": versions[n]} for n, t in tools.items() if versions[n]}
    _tool_cache.update(at=time.time(), tools=found)
    return found


# ── what can be run here ──
def _q(path: str) -> str:
    return f'"{path}"' if re.search(r"[\s&()^|<>]", path) else path


def _exe(stem: str) -> tuple:
    """The program a compiler should write, and how to run it from the folder. On Windows the name has .exe:
    MinGW's gcc adds it by itself, but rustc writes exactly the name it's given (found by the Real runs CI job)."""
    if os.name == "nt":
        return _q(f"{stem}.exe"), _q(f"{stem}.exe")
    return _q(stem), _q(f"./{stem}")


EXPLAIN_ONLY_PROJECTS = [   # (marker, what it is)
    ("AndroidManifest.xml", "an Android app"), ("app/src/main/AndroidManifest.xml", "an Android app"),
    ("ProjectSettings/ProjectVersion.txt", "a Unity project"), ("*.uproject", "an Unreal project"),
    ("*.xcodeproj", "an Xcode (iOS or Mac) project"), ("docker-compose.yml", "a Docker project"),
    ("compose.yaml", "a Docker project"),
]


def _has(root: Path, pattern: str) -> bool:
    return any(root.glob(pattern)) if "*" in pattern else (root / pattern).exists()


def suggestions(root: Path, open_file: str = "", tools: dict = None) -> dict:
    """Commands that make sense for this folder and the open file: [{label, command, keep_running, needs,
    missing}], or why it can only be explained."""
    tools = available() if tools is None else tools
    py = (tools.get("python") or {}).get("command", "python")
    out = []

    def add(label, command, needs=(), keep=False, why=""):
        if any(s["command"] == command for s in out):
            return
        out.append({"label": label, "command": command, "keep_running": keep, "why": why,
                    "needs": list(needs), "missing": [n for n in needs if n not in tools]})

    for marker, what in EXPLAIN_ONLY_PROJECTS:
        if _has(root, marker):
            return {"commands": [], "kind": "project",
                    "explain_only": f"This looks like {what}, which EasyUniTrack can't run. "
                                    "It can still explain and debug the code by reading it."}

    # Projects
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
        frame = next((n for k, n in (("next", "Next.js"), ("react", "React"), ("vue", "Vue"), ("express", "Express"),
                                     ("vite", "Vite")) if k in deps), "")
        for name in (data.get("scripts") or {}):
            keep = name in ("dev", "start", "serve", "preview", "watch")
            add(f"npm run {name}" + (f" ({frame})" if frame and keep else ""), f"npm run {name}", ["npm"], keep)
        if not data.get("scripts"):
            main = data.get("main") or "index.js"
            if (root / main).is_file():
                add(f"node {main}", f"node {_q(main)}", ["node"])
    if (root / "manage.py").is_file():
        add("Django server", f"{py} manage.py runserver", ["python"], keep=True)
        add("Django tests", f"{py} manage.py test", ["python"])
    reqs = ""
    for f in ("requirements.txt", "pyproject.toml", "Pipfile"):
        try:
            reqs += (root / f).read_text(encoding="utf-8", errors="replace").lower() if (root / f).is_file() else ""
        except OSError:
            pass
    for main in ("main.py", "app.py", "run.py"):
        if (root / main).is_file():
            keep = main == "app.py" and ("flask" in reqs or "fastapi" in reqs)
            add(f"python {main}", f"{py} {main}", ["python"], keep=keep,
                why="Opens its own window" if "pygame" in reqs else "")
    if "flask" in reqs and not any(s["keep_running"] for s in out):
        add("Flask server", f"{py} -m flask run", ["python"], keep=True)
    if "pytest" in reqs or (root / "tests").is_dir() or any(root.glob("test_*.py")):
        if any(root.rglob("*.py")):
            add("pytest", f"{py} -m pytest", ["python"])
    if (root / "pom.xml").is_file():
        pom = (root / "pom.xml").read_text(encoding="utf-8", errors="replace")
        if "spring-boot" in pom:
            add("Spring Boot", "mvn -q spring-boot:run", ["mvn"], keep=True)
        if "javafx" in pom:
            add("JavaFX", "mvn -q javafx:run", ["mvn"], why="Opens its own window")
        add("mvn test", "mvn -q test", ["mvn"])
    if (root / "build.gradle").is_file() or (root / "build.gradle.kts").is_file():
        has_wrapper = (root / "gradlew").exists() or (root / "gradlew.bat").exists()
        wrapper = ("gradlew.bat" if os.name == "nt" else "./gradlew") if has_wrapper else ""
        g = wrapper or "gradle"
        needs = [] if wrapper else ["gradle"]
        add("gradle run", f"{g} run", needs)
        add("gradle test", f"{g} test", needs)
    projects = list(root.glob("*.csproj")) + list(root.glob("*.sln"))
    if projects:
        text = " ".join(p.read_text(encoding="utf-8", errors="replace") for p in projects if p.suffix == ".csproj")
        add("dotnet run", "dotnet run", ["dotnet"], keep="Microsoft.NET.Sdk.Web" in text)
        add("dotnet test", "dotnet test", ["dotnet"])
    if (root / "CMakeLists.txt").is_file():
        add("CMake build", "cmake -S . -B build && cmake --build build", ["cmake"])
        add("ctest", "ctest --test-dir build", ["ctest"])
    elif (root / "Makefile").is_file() or (root / "makefile").is_file():
        add("make", "make", ["make"])
    if (root / "Cargo.toml").is_file():
        add("cargo run", "cargo run", ["cargo"])
        add("cargo test", "cargo test", ["cargo"])
    if (root / "go.mod").is_file():
        add("go run", "go run .", ["go"])
        add("go test", "go test ./...", ["go"])

    # The open file on its own
    if open_file:
        f = Path(open_file)
        rel, stem, ext = _q(open_file), f.stem, f.suffix.lower()
        binary, exe = _exe(stem)
        jar = _q(f"{stem}.jar")
        single = {
            ".py": (f"{py} {rel}", ["python"]), ".pyw": (f"{py} {rel}", ["python"]),
            ".java": (f"java {rel}", ["java"]),
            ".c": (f"gcc {rel} -o {binary} && {exe}", ["gcc"]),
            ".cpp": (f"g++ {rel} -o {binary} && {exe}", ["g++"]), ".cc": (f"g++ {rel} -o {binary} && {exe}", ["g++"]),
            ".cxx": (f"g++ {rel} -o {binary} && {exe}", ["g++"]),
            ".js": (f"node {rel}", ["node"]), ".mjs": (f"node {rel}", ["node"]), ".cjs": (f"node {rel}", ["node"]),
            ".ts": (f"tsx {rel}", ["tsx"]) if "tsx" in tools else (f"ts-node {rel}", ["ts-node"]),
            ".go": (f"go run {rel}", ["go"]), ".rs": (f"rustc {rel} -o {binary} && {exe}", ["rustc"]),
            ".kt": (f"kotlinc {rel} -include-runtime -d {jar} && java -jar {jar}", ["kotlinc", "java"]),
            ".scala": (f"scala {rel}", ["scala"]), ".php": (f"php {rel}", ["php"]), ".rb": (f"ruby {rel}", ["ruby"]),
            ".dart": (f"dart run {rel}", ["dart"]), ".lua": (f"lua {rel}", ["lua"]), ".r": (f"Rscript {rel}", ["Rscript"]),
            ".hs": (f"runghc {rel}", ["runghc"]), ".pl": (f"swipl {rel}", ["swipl"]),
            ".m": (f"octave-cli {rel}", ["octave"]), ".sh": (f"bash {rel}", ["bash"]),
            ".ps1": (f"powershell -NoProfile -ExecutionPolicy Bypass -File {rel}", ["powershell"]),
        }.get(ext)
        if single:
            text = ""
            try:
                text = (root / open_file).read_text(encoding="utf-8", errors="replace")[:20000]
            except OSError:
                pass
            window = bool(re.search(r"\b(import|from)\s+(pygame|tkinter|turtle|PyQt\w*|PySide\w*|kivy)\b|"
                                    r"javax\.swing|javafx\.", text))
            server = bool(re.search(r"\b(app\.run\(|uvicorn\.run|HTTPServer|serve_forever|\.listen\()", text))
            add(f"Run {f.name}", single[0], single[1], keep=server, why="Opens its own window" if window else "")
        elif ext == ".cs" and not projects:
            pass                                          # C# needs a project: explained below
    if not out:
        why = "There's nothing EasyUniTrack knows how to run here."
        if open_file:
            ext = Path(open_file).suffix.lower()
            why = {".cs": "C# needs a project (.csproj) to run. Create one with `dotnet new console`.",
                   ".ipynb": "Jupyter notebooks can be read and explained, but not run here yet."}.get(
                ext, "This kind of file can be explained and debugged by reading it, but not run here.")
        # kind: "file" (this kind of file can't be run), or "none" (no project here and no file open yet)
        return {"commands": [], "explain_only": why, "kind": "file" if open_file else "none"}
    return {"commands": out, "explain_only": "", "kind": "run"}


# ── a run ──
class Run:
    _ids = itertools.count(1)

    def __init__(self, folder_id: int, command: str, cwd: str, timeout: int, keep_running: bool):
        self.id = next(self._ids)
        self.folder_id, self.command, self.cwd = folder_id, command, cwd
        self.timeout = None if keep_running else timeout
        self.keep_running = keep_running
        self.output, self.truncated = "", False
        self.status, self.exit_code, self.reason = "running", None, ""
        self.started, self.ended = time.time(), None
        self.lock = threading.Lock()
        self.links, self._scanned = [], 0               # localhost addresses, found as output arrives
        self.proc = None
        self._job = None

    # The output, capped
    def _add(self, text: str):
        with self.lock:
            room = MAX_OUTPUT - len(self.output)
            if room <= 0:
                self.truncated = True
                return
            if len(text) > room:
                text, self.truncated = text[:room], True
            self.output += text
            if len(self.links) < 5:                       # only the new part (and a little before, for a split URL)
                for url in LOCALHOST.findall(self.output, max(0, self._scanned - 100)):
                    if url not in self.links and len(self.links) < 5:
                        self.links.append(url)
            self._scanned = len(self.output)

    def start(self, env: dict):
        kwargs = dict(cwd=self.cwd, env=env, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                      stderr=subprocess.STDOUT, bufsize=0)
        if os.name == "nt":
            # Started suspended, put in its job, then resumed: nothing it starts can slip out of the job
            self.proc = subprocess.Popen(self.command, creationflags=CREATE_NO_WINDOW | CREATE_SUSPENDED |
                                         CREATE_NEW_PROCESS_GROUP, **kwargs)
            try:
                self._job = _new_job()
                if not _k32.AssignProcessToJobObject(self._job, int(self.proc._handle)):
                    raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
            except OSError:
                self._job = None                          # still runs; Stop falls back to taskkill /T
            status = _ntdll.NtResumeProcess(int(self.proc._handle))
            if status != 0:                               # still suspended: it would never run or print anything
                self._kill()
                self.proc.kill()
                raise OSError(status, "The program couldn't be started")
        else:
            self.proc = subprocess.Popen(self.command, start_new_session=True, **kwargs)
        self._reader = threading.Thread(target=self._read, daemon=True)
        try:
            self._reader.start()
            threading.Thread(target=self._wait, daemon=True).start()
        except RuntimeError as e:                         # no thread to watch it: don't leave it running untracked
            self._kill()
            self.proc.kill()
            self.proc.wait()
            if os.name == "nt" and self._job:
                _k32.CloseHandle(self._job)
                self._job = None
            raise OSError(0, "The program couldn't be watched, so it was stopped") from e

    def _read(self):
        dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
        out = self.proc.stdout
        while True:
            try:
                chunk = out.read(4096) if not hasattr(out, "read1") else out.read1(4096)
            except (OSError, ValueError):
                break
            if not chunk:
                break
            self._add(dec.decode(chunk).replace("\r\n", "\n"))
        self._add(dec.decode(b"", final=True))

    def _wait(self):
        try:
            code = self.proc.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            self.reason = f"Stopped after the {self.timeout} s time limit."
            self._kill()
            code = self.proc.wait()
            self.status = "timed_out"
        self._kill()                                      # anything it left running (a background server, say)
        self._reader.join(timeout=5)                      # the last of the output (a traceback) before "finished"
        if self.status == "running":
            self.status = "stopped" if self.reason else "finished"
        self.exit_code, self.ended = code, time.time()
        if self._job and os.name == "nt":
            _k32.CloseHandle(self._job)
            self._job = None

    def _kill(self):
        if self.proc is None:
            return
        if os.name == "nt":
            if self._job:
                _k32.TerminateJobObject(self._job, 1)
            elif self.proc.poll() is None:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)], capture_output=True,
                               creationflags=CREATE_NO_WINDOW)
        else:
            import signal
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    def stop(self):
        if self.status == "running":
            self.reason = "Stopped."
            self._kill()

    def send(self, text: str):
        if self.status != "running" or not self.proc.stdin:
            raise RuntimeError("The program isn't running.")
        try:
            self.proc.stdin.write(text.encode("utf-8"))
            self.proc.stdin.flush()
        except (OSError, ValueError):
            raise RuntimeError("The program isn't reading input any more.") from None

    def view(self, since: int = 0) -> dict:
        with self.lock:
            text = self.output[since:]
            size = len(self.output)
            links = list(self.links)
        return {"id": self.id, "folder_id": self.folder_id, "command": self.command, "status": self.status,
                "exit_code": self.exit_code, "reason": self.reason, "keep_running": self.keep_running,
                "timeout": self.timeout, "elapsed": round((self.ended or time.time()) - self.started, 1),
                "output": text, "next": size, "truncated": self.truncated,
                "links": links}


class Runner:
    """The runs of this session, kept in memory (run output isn't stored or backed up)."""

    def __init__(self):
        self.runs = {}
        self._lock = threading.Lock()                     # requests come in on several threads at once

    def start(self, folder_id: int, cwd: str, command: str, timeout: int = DEFAULT_TIMEOUT,
              keep_running: bool = False) -> Run:
        with self._lock:                                  # the limit check and the start as one step
            running = [r for r in self.runs.values() if r.status == "running"]
            if len(running) >= MAX_RUNNING:
                raise RuntimeError(f"{MAX_RUNNING} programs are already running. Stop one first.")
            run = Run(folder_id, command, cwd, timeout, keep_running)
            run.start(clean_env())
            self.runs[run.id] = run
            for old in sorted((r for r in self.runs.values() if r.status != "running"), key=lambda r: r.id)[:-20]:
                self.runs.pop(old.id, None)               # keep the last few finished runs
        return run

    def get(self, run_id: int) -> Run:
        with self._lock:
            run = self.runs.get(run_id)
        if not run:
            raise KeyError(run_id)
        return run

    def stop_all(self):
        with self._lock:
            runs = list(self.runs.values())
        for r in runs:
            r.stop()

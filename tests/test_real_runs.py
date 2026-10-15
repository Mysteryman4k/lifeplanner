"""Real runs in many languages: the code workspace's suggested command for a small program is run with the real
compiler or runtime, and must build, run and print what it should. Each case is skipped when its tools aren't
installed here. The Real runs CI job (.github/workflows/ci.yml) runs them on Windows and Linux runners, where
EUT_REQUIRE_TOOLS names the cases that must run, so a missing tool fails instead of skipping."""
import os
import re
import subprocess
import time

import pytest

from ai import runner as R

pytestmark = pytest.mark.toolchains
REQUIRED = {x.strip() for x in os.environ.get("EUT_REQUIRE_TOOLS", "").split(",") if x.strip()}
TIME_LIMIT = 300                       # a first `dotnet run` or `cargo run` can take a minute or two on a runner


def dotnet_target() -> str:
    """net8.0, net9.0 ...: the newest SDK installed, so the project builds without downloading a targeting pack."""
    try:
        out = subprocess.run(["dotnet", "--version"], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return "net8.0"
    m = re.match(r"(\d+)\.", out.strip())
    return f"net{m.group(1)}.0" if m else "net8.0"


def hello(lang: str) -> str:
    return f"hello from {lang}"


CASES = {   # case: (files, the open file or "", the suggestion's label, what the output must include)
    "python": ({"hello.py": f'print("{hello("python")}")\n'}, "hello.py", "Run hello.py", hello("python")),
    "node": ({"hello.js": f'console.log("{hello("node")}");\n'}, "hello.js", "Run hello.js", hello("node")),
    "java": ({"Hello.java": 'public class Hello {\n    public static void main(String[] args) {\n'
                            f'        System.out.println("{hello("java")}");\n    }}\n}}\n'},
             "Hello.java", "Run Hello.java", hello("java")),
    "c": ({"hello.c": f'#include <stdio.h>\nint main(void) {{ printf("{hello("c")}\\n"); return 0; }}\n'},
          "hello.c", "Run hello.c", hello("c")),
    "c, a name with a space": ({"my prog.c": f'#include <stdio.h>\nint main(void) {{ printf("{hello("my prog")}\\n"); }}\n'},
                               "my prog.c", "Run my prog.c", hello("my prog")),
    "cpp": ({"hello.cpp": f'#include <iostream>\nint main() {{ std::cout << "{hello("cpp")}" << std::endl; }}\n'},
            "hello.cpp", "Run hello.cpp", hello("cpp")),
    "go": ({"hello.go": f'package main\n\nimport "fmt"\n\nfunc main() {{ fmt.Println("{hello("go")}") }}\n'},
           "hello.go", "Run hello.go", hello("go")),
    "go module": ({"go.mod": "module hello\n\ngo 1.21\n",
                   "main.go": f'package main\n\nimport "fmt"\n\nfunc main() {{ fmt.Println("{hello("go module")}") }}\n'},
                  "", "go run", hello("go module")),
    "rust": ({"hello.rs": f'fn main() {{ println!("{hello("rust")}"); }}\n'}, "hello.rs", "Run hello.rs", hello("rust")),
    "cargo": ({"Cargo.toml": '[package]\nname = "hello"\nversion = "0.1.0"\nedition = "2021"\n',
               "src/main.rs": f'fn main() {{ println!("{hello("cargo")}"); }}\n'}, "", "cargo run", hello("cargo")),
    "dotnet": ({"hello.csproj": None, "Program.cs": f'System.Console.WriteLine("{hello("dotnet")}");\n'},
               "", "dotnet run", hello("dotnet")),
    "cmake": ({"CMakeLists.txt": "cmake_minimum_required(VERSION 3.10)\nproject(hello C)\nadd_executable(hello hello.c)\n",
               "hello.c": "int main(void) { return 0; }\n"}, "", "CMake build", ""),
}


@pytest.fixture(scope="module")
def tools():
    return R.available(refresh=True)


def wait(run, seconds):
    end = time.time() + seconds
    while time.time() < end and run.status == "running":
        time.sleep(0.2)
    return run.view()


@pytest.mark.parametrize("case", CASES)
def test_the_suggested_command_really_runs(case, tools, tmp_path):
    files, open_file, label, expect = CASES[case]
    for rel, text in files.items():
        if rel == "hello.csproj":
            text = ('<Project Sdk="Microsoft.NET.Sdk">\n  <PropertyGroup>\n    <OutputType>Exe</OutputType>\n'
                    f'    <TargetFramework>{dotnet_target()}</TargetFramework>\n  </PropertyGroup>\n</Project>\n')
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    found = R.suggestions(tmp_path, open_file, tools)
    command = next((s for s in found["commands"] if s["label"] == label), None)
    assert command, f"No {label!r} suggestion: {found}"
    if command["missing"]:
        if case in REQUIRED or "all" in REQUIRED:
            pytest.fail(f"{case} must run here, but these aren't installed: {command['missing']}")
        pytest.skip(f"Not installed here: {', '.join(command['missing'])}")
    run = R.Runner().start(1, str(tmp_path), command["command"], timeout=TIME_LIMIT)
    view = wait(run, TIME_LIMIT + 30)
    assert view["status"] == "finished", f"{command['command']}: {view['status']} {view['reason']}\n{view['output'][-3000:]}"
    assert view["exit_code"] == 0, f"{command['command']} exited with {view['exit_code']}:\n{view['output'][-3000:]}"
    assert expect in view["output"], view["output"][-3000:]

"""Eval commands stay independent: none imports another, shared code lives in lib."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EVALS = ROOT / "scripts" / "evals"
LIB = EVALS / "lib"
COMMANDS = sorted(path.stem for path in EVALS.glob("*.py") if path.name != "__init__.py")
PREFIX = "scripts.evals"


def imported_modules(source: str) -> set[str]:
    """Return the absolute dotted names a module imports, at any nesting depth.

    ``from scripts.evals import x`` counts as ``scripts.evals.x`` (``x`` may be a module),
    so a command imported by name is seen. String arguments of ``import_module`` and
    ``__import__`` count too.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = f"{PREFIX}.{module}".rstrip(".") if node.level == 1 else module
            found.add(module)
            found.update(f"{module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if name in {"import_module", "__import__"} and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.add(arg.value)
    return found


def command_imports(source: str, own: str) -> set[str]:
    """Names of other eval commands that ``source`` imports."""
    names = {f"{PREFIX}.{name}" for name in COMMANDS if name != own}
    return {
        module
        for module in imported_modules(source)
        if any(module == name or module.startswith(name + ".") for name in names)
    }


def test_the_walk_sees_every_import_form() -> None:
    own = "evaluate_combined_gate"
    forms = [
        "from scripts.evals import evaluate_retrieval",
        "from scripts.evals.evaluate_retrieval import gate_decision",
        "import scripts.evals.compare_turn_routes",
        "def f():\n    from scripts.evals import evaluate_passage_support as p",
        "import importlib\nimportlib.import_module('scripts.evals.benchmark_course_intent')",
    ]
    for form in forms:
        assert command_imports(form, own), form
    assert not command_imports("from scripts.evals.lib.gate import gate_decision", own)
    assert not command_imports("from scripts.evals import evaluate_combined_gate", own)


@pytest.mark.parametrize("name", COMMANDS)
def test_no_command_imports_another_command(name: str) -> None:
    source = (EVALS / f"{name}.py").read_text(encoding="utf-8")
    assert command_imports(source, name) == set()


@pytest.mark.parametrize("path", sorted(LIB.glob("*.py")), ids=lambda path: path.stem)
def test_lib_imports_no_command_and_defines_no_entry_point(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    assert command_imports(source, "") == set()
    tree = ast.parse(source)
    defined = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert not defined & {"main", "build_parser"}
    assert "__main__" not in source


def test_commands_list_is_not_empty() -> None:
    assert {"evaluate_retrieval", "compare_turn_routes", "evaluate_passage_support"} <= set(COMMANDS)


def test_lib_loads_no_model_package() -> None:
    code = (
        "import sys\n"
        "import scripts.evals.lib.route_scoring, scripts.evals.lib.passage_scoring\n"
        "import scripts.evals.lib.prepared_rows, scripts.evals.lib.live\n"
        "heavy = {'laya', 'vegaml', 'setfit', 'torch', 'onnxruntime', 'boto3'}\n"
        "print(sorted(heavy & set(sys.modules)))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True
    )
    assert done.stdout.strip() == "[]"


def test_route_report_builds_from_a_stub_predictor() -> None:
    from scripts.evals.lib import route_scoring

    def predict(_text: str) -> dict[str, dict[str, float]]:
        return {
            "scope": {"none": 1.0, "course": 0.0, "both": 0.0, "student_upload": 0.0},
            "mode": {"lecture_help": 1.0, "project_coaching": 0.0},
        }

    splits = route_scoring.inputs()
    small = {name: rows[:6] for name, rows in splits.items() if name != "historical"}
    small["historical"] = splits["historical"][:6]
    report = route_scoring.evaluate(predict, small)
    assert set(report["rows"]) == {"calibration", "fresh", "historical"}
    assert {"cutoffs", "metrics", "latency", "qualifies", "protected_checks"} <= set(report)

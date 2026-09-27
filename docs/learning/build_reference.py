"""Build the learning appendix from static source without importing the app.

Run from any directory. Reads tracked-style Python source, SQL literals, and
dependency manifests; writes only the adjacent REFERENCE.md. No application
initialization, credentials, database connection, or network call occurs.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).with_name("REFERENCE.md")


def clean(value: str) -> str:
    """Collapse whitespace and escape Markdown table delimiters."""
    return " ".join(value.split()).replace("|", "\\|")


def link(path: Path) -> str:
    """Return a repository-relative source link for the appendix."""
    relative = path.relative_to(ROOT).as_posix()
    return f"[{relative}](../../{relative})"


def tree(path: Path) -> ast.Module:
    """Parse a Python file as text, raising on invalid source syntax."""
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def build() -> str:
    """Return API, DDL, module, and dependency inventories as Markdown."""
    revision = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
    ).strip()
    lines = [
        "# Code-derived project reference", "",
        f"Generated from source at Git HEAD `{revision}`; uncommitted source, if any, is included.",
        "", "Companion: [learning handbook](README.md). This is a static inventory, not a live OpenAPI or AWS inspection.",
        "", "## HTTP routes", "",
        "Decorators are extracted from application and auth source, including routes that may be conditional. Internal FastAPI routes are not necessarily publicly reachable through Caddy. A function's docstring is a navigation aid and can itself become stale; chapters explain verified behavior.",
        "", "| Method | Path | Handler / line | Declared response | Dependency defaults | Purpose |",
        "|---|---|---|---|---|---|",
    ]
    routes = []
    for path in (ROOT / "backend/http/app.py", ROOT / "backend/auth_routes.py"):
        for node in ast.walk(tree(path)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            doc = (ast.get_docstring(node) or "No handler docstring.").split("\n\n")[0]
            defaults = [*node.args.defaults, *node.args.kw_defaults]
            dependencies = ", ".join(
                ast.unparse(item) for item in defaults
                if isinstance(item, ast.Call) and ast.unparse(item.func) == "Depends"
            ) or "Inspect handler/auth logic"
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                    continue
                method = decorator.func.attr
                if method not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                    continue
                if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
                    continue
                route = decorator.args[0].value
                if not isinstance(route, str):
                    continue
                response = next(
                    (ast.unparse(k.value) for k in decorator.keywords if k.arg == "response_model"),
                    ast.unparse(node.returns) if node.returns else "Not annotated",
                )
                routes.append((route, method.upper(), path, node.name, node.lineno, response, dependencies, doc))
    for route, method, path, name, number, response, deps, doc in sorted(routes):
        lines.append(f"| {method} | `{route}` | {link(path)} `{name}` L{number} | {clean(response)} | {clean(deps)} | {clean(doc)} |")
    lines += ["", f"Static route registrations: **{len(routes)}**.", "", "## Main API input models", "",
              "Fields below come from class annotations. Defaults and Field expressions are shown as source, not evaluated settings. Inherited fields and custom validators require reading the linked source. Accepted input is also subject to server ownership and authoritative-state validation."]
    input_names = {
        "CoachRequest", "DeepReviewRequest", "NotebookCreateRequest",
        "NotebookUpdateRequest", "NotebookMetadataPatch", "MessageCreateRequest",
        "SourceUpdateRequest", "SourceSelectAllRequest", "PreferencePatch",
        "TransitionResolution", "StageSelectionRequest", "MessageReviseRequest",
    }
    for relative in ("backend/domain.py", "backend/http/app.py"):
        path = ROOT / relative
        for node in tree(path).body:
            if not isinstance(node, ast.ClassDef) or node.name not in input_names:
                continue
            lines += ["", f"### {node.name}", "", f"Source: {link(path)}, line {node.lineno}.", "",
                      "| Field | Type | Default / constraint expression |", "|---|---|---|"]
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    default = ast.unparse(item.value) if item.value is not None else "Required"
                    lines.append(f"| `{item.target.id}` | {clean(ast.unparse(item.annotation))} | {clean(default)} |")
    lines += ["", "## Exact schema declarations", "",
              "SQL below is extracted verbatim from schema constants. It is reference material, not an instruction to apply DDL to an existing database. Use the documented initialization/migration tools and review their plans."]
    for relative, constant in (
        ("backend/persistence/store/sqlite_schema.py", "SQLITE_SCHEMA"),
        ("backend/persistence/dsql_schema.py", "DSQL_SCHEMA"),
    ):
        path = ROOT / relative
        sql = None
        for node in tree(path).body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == constant for t in node.targets):
                sql = ast.literal_eval(node.value)
        if not isinstance(sql, str):
            raise ValueError(f"Missing literal schema: {constant}")
        tables = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", sql)
        lines += ["", f"### {constant}", "", f"Source: {link(path)}. Tables: **{len(tables)}**.", "",
                  ", ".join(f"`{name}`" for name in tables), "", "```sql", sql.strip(), "```"]
    lines += ["", "## Python module map", "",
              "The first paragraph of each module docstring is extracted below. Compatibility aliases and historical modules remain visible; presence in this list does not imply execution on the active production chat path.", "",
              "| File | Responsibility from module docstring | Top-level classes |", "|---|---|---|"]
    for directory in ("backend", "ui", "agentcore_runtime"):
        for path in sorted((ROOT / directory).rglob("*.py")):
            parsed = tree(path)
            doc = (ast.get_docstring(parsed) or "No module docstring; inspect source.").split("\n\n")[0]
            classes = ", ".join(node.name for node in parsed.body if isinstance(node, ast.ClassDef)) or "—"
            lines.append(f"| {link(path)} | {clean(doc)} | {clean(classes)} |")
    lines += ["", "## Pinned dependency manifests", "",
              "These are repository pins, not claims about the newest package versions or the packages installed on AWS."]
    for relative in ("requirements.txt", "requirements-dev.txt", "agentcore_runtime/requirements.txt"):
        path = ROOT / relative
        lines += ["", f"### {relative}", "", f"Source: {link(path)}", "", "```text", path.read_text(encoding="utf-8").strip(), "```"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    OUTPUT.write_text(build(), encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")

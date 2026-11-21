"""Static safety checks for infra/aws templates and scripts/aws/deploy_stack.sh.

No test here talks to AWS: templates are parsed as text, and the deploy script
runs with a stub ``aws`` that fails the test if it is ever called.
"""

from __future__ import annotations

import ast
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra" / "aws"
SCRIPT = ROOT / "scripts" / "aws" / "deploy_stack.sh"
TEMPLATES = sorted(INFRA.glob("*.yaml"))
SECRET_NAME = re.compile(r"secret|password|token|credential", re.IGNORECASE)


class _CfnLoader(yaml.SafeLoader):
    """SafeLoader that keeps CloudFormation short-form tags as plain data."""


def _construct_tag(loader: _CfnLoader, suffix: str, node: yaml.Node) -> Any:
    """Return ``{"Fn::<tag>": value}`` for any ``!Tag`` node."""
    if isinstance(node, yaml.ScalarNode):
        value: Any = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    name = "Ref" if suffix == "Ref" else f"Fn::{suffix}"
    return {name: value}


_CfnLoader.add_multi_constructor("!", _construct_tag)


def _load(path: Path) -> dict[str, Any]:
    """Parse one template with the CloudFormation-aware loader."""
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_CfnLoader)  # noqa: S506


def _statements(template: dict[str, Any]) -> list[dict[str, Any]]:
    """Return every IAM policy statement in a template's roles."""
    found: list[dict[str, Any]] = []
    for resource in template["Resources"].values():
        if resource["Type"] != "AWS::IAM::Role":
            continue
        for policy in resource["Properties"].get("Policies", []):
            found.extend(policy["PolicyDocument"]["Statement"])
    return found


def _as_list(value: Any) -> list[Any]:
    """Wrap a scalar in a list."""
    return value if isinstance(value, list) else [value]


def test_templates_exist_and_parse() -> None:
    names = {path.name for path in TEMPLATES}
    assert {"app-tier.yaml", "edge-monitoring.yaml"} <= names
    for path in TEMPLATES:
        template = _load(path)
        assert template["AWSTemplateFormatVersion"] == "2010-09-09"
        assert template["Resources"]


def test_no_literal_keys_account_ids_or_bucket_names() -> None:
    files = [*TEMPLATES, *INFRA.glob("*.txt"), SCRIPT]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}", text), path
        assert not re.search(r"(?<![0-9])[0-9]{12}(?![0-9])", text), path
        assert not re.search(r"aws_secret_access_key|aws_access_key_id", text, re.I), path
        assert "cde2300-course-content" not in text, path
        assert "cloudfront.net" not in text, path


def test_secret_parameters_have_no_default() -> None:
    for path in TEMPLATES:
        for name, spec in _load(path).get("Parameters", {}).items():
            if SECRET_NAME.search(name):
                assert "Default" not in spec, f"{path.name}:{name}"
    app = _load(INFRA / "app-tier.yaml")["Parameters"]
    assert "EnvSecretArn" in app and "Default" not in app["EnvSecretArn"]


def test_iam_has_no_wildcard_on_bedrock_or_s3_write() -> None:
    statements = _statements(_load(INFRA / "app-tier.yaml"))
    assert statements
    for statement in statements:
        actions = _as_list(statement["Action"])
        resources = _as_list(statement["Resource"])
        if any(a.startswith(("bedrock:", "bedrock-agentcore:")) for a in actions):
            assert "*" not in resources, statement["Sid"]
        if any(a.startswith("s3:") and a != "s3:GetObject" for a in actions):
            assert "*" not in resources, statement["Sid"]
        assert not any(a in {"*", "s3:*", "bedrock:*"} or a.endswith(":*") for a in actions)
        assert statement["Effect"] == "Allow"
    bedrock = {a for s in statements for a in _as_list(s["Action"]) if a.startswith("bedrock:")}
    assert bedrock == {"bedrock:Retrieve"}


def test_group_stays_single_instance() -> None:
    group = next(
        r for r in _load(INFRA / "app-tier.yaml")["Resources"].values()
        if r["Type"] == "AWS::AutoScaling::AutoScalingGroup"
    )["Properties"]
    assert (group["MinSize"], group["MaxSize"], group["DesiredCapacity"]) == ("1", "1", "1")


def _run_script(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the deploy script with a stub PATH whose ``aws`` fails the test."""
    stub = tmp_path / "bin"
    stub.mkdir(exist_ok=True)
    marker = tmp_path / "aws-called"
    aws = stub / "aws"
    aws.write_text(f"#!/bin/sh\necho called > '{marker}'\nexit 97\n", encoding="utf-8")
    aws.chmod(aws.stat().st_mode | stat.S_IXUSR)
    env = {"PATH": f"{stub}:/usr/bin:/bin", "HOME": str(tmp_path)}
    result = subprocess.run(
        ["sh", str(SCRIPT), *args], capture_output=True, text=True, env=env, check=False
    )
    assert not marker.exists(), "deploy_stack.sh called aws without --apply"
    return result


def test_script_help_and_dry_run_default(tmp_path: Path) -> None:
    helped = _run_script(tmp_path, "--help")
    assert helped.returncode == 0 and "--confirm-account" in helped.stdout
    dry = _run_script(tmp_path)
    assert dry.returncode == 0
    assert "DRY RUN" in dry.stdout and "Nothing was changed" in dry.stdout
    assert "co-design-app" in dry.stdout and "co-design-edge" in dry.stdout


def test_script_refuses_without_both_flags(tmp_path: Path) -> None:
    only_apply = _run_script(tmp_path, "--apply")
    assert only_apply.returncode != 0 and "--confirm-account" in only_apply.stderr
    only_id = _run_script(tmp_path, "--confirm-account", "123456789012")
    assert only_id.returncode != 0 and "--apply" in only_id.stderr
    bad_id = _run_script(tmp_path, "--apply", "--confirm-account", "12345")
    assert bad_id.returncode != 0 and "12 digits" in bad_id.stderr


def test_script_refuses_placeholder_parameters_and_unknown_options(tmp_path: Path) -> None:
    placeholders = _run_script(
        tmp_path, "--app-params", str(INFRA / "parameters.app.example.txt")
    )
    assert placeholders.returncode != 0 and "REPLACE_ME" in placeholders.stderr
    assert _run_script(tmp_path, "--bogus").returncode == 2


def test_this_module_imports_no_aws_sdk() -> None:
    """No client can be created here because no AWS SDK is imported."""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not imported & {"boto3", "botocore"}

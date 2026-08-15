"""Gated Bedrock Knowledge Base Retrieve diagnostic (never used by pytest).

Refuses live AWS by default. One approved run calls ``Retrieve`` only through
the same :class:`BedrockKnowledgeBaseRetriever` the app uses. It never calls
RetrieveAndGenerate, AgentCore, or any generation model.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

_MAX_ALLOWED_REQUESTS = 2
_DEFAULT_QUERY = "week 1 introduction innovation"
_DEFAULT_SOURCE = "Week 1 Introduction to innovation v3.pdf"


class RetrieveBudgetExceeded(RuntimeError):
    """Raised when the diagnostic would exceed ``--max-requests``."""


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the Knowledge Base Retrieve diagnostic CLI."""
    parser = argparse.ArgumentParser(
        description=(
            "One Knowledge Base Retrieve diagnostic using the production "
            "adapter. Never used by pytest. No generation call."
        )
    )
    parser.add_argument(
        "--query",
        default=_DEFAULT_QUERY,
        help="Student-style question used as the Retrieve text.",
    )
    parser.add_argument(
        "--source",
        default=_DEFAULT_SOURCE,
        help="Course filename or canonical course/ object key.",
    )
    parser.add_argument(
        "--i-approve-live-bedrock",
        action="store_true",
        help="Required acknowledgement that this calls live Bedrock Retrieve.",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=1,
        help=(
            "Maximum Retrieve API calls (default 1, maximum 2). Use 2 to "
            "allow the production metadata-filter fallback."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print resolved config without calling AWS.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def refuse_reason(args: argparse.Namespace) -> str | None:
    """Return a refusal message when the live Retrieve diagnostic must not run."""
    max_requests = int(getattr(args, "max_requests", 1) or 0)
    if max_requests < 1 or max_requests > _MAX_ALLOWED_REQUESTS:
        return "max-requests must be 1 or 2"
    if args.dry_run:
        return None
    if not args.i_approve_live_bedrock:
        return "live knowledge base retrieve requires --i-approve-live-bedrock"
    return None


def resolve_course_object_key(source: str) -> str:
    """Return a canonical ``course/`` object key from a filename or key.

    Args:
        source: Filename, relative lectureNotes/readings path, or full object key.

    Returns:
        Slash-normalized key under ``course/``.
    """
    cleaned = str(source or "").strip().replace("\\", "/").lstrip("/")
    if not cleaned:
        raise ValueError("source is required")
    if cleaned.startswith("course/"):
        return cleaned
    if cleaned.startswith("lectureNotes/") or cleaned.startswith("readings/"):
        return f"course/{cleaned}"
    return f"course/lectureNotes/{cleaned}"


class _CappedRetrieveClient:
    """Wrap a bedrock-agent-runtime client and enforce ``--max-requests``."""

    def __init__(self, inner: Any, *, max_requests: int) -> None:
        self._inner = inner
        self._max_requests = max(1, int(max_requests))
        self.calls: list[dict[str, Any]] = []
        self.raw_counts: list[int] = []
        self.sanitized_uris: list[list[str]] = []

    def retrieve(self, **kwargs: Any) -> dict[str, Any]:
        """Record one Retrieve invocation or refuse a further live call."""
        if len(self.calls) >= self._max_requests:
            raise RetrieveBudgetExceeded("max-requests exceeded")
        self.calls.append(kwargs)
        response = self._inner.retrieve(**kwargs)
        hits = response.get("retrievalResults") if isinstance(response, dict) else None
        if not isinstance(hits, list):
            self.raw_counts.append(0)
            self.sanitized_uris.append([])
            return response
        from backend.bedrock_retrieve import sanitized_hit_s3_uri

        uris = [
            sanitized_hit_s3_uri(item)
            for item in hits
            if isinstance(item, dict)
        ]
        self.raw_counts.append(len(hits))
        self.sanitized_uris.append([uri for uri in uris if uri])
        return response


def _caller_identity(region: str) -> dict[str, str]:
    """Return a secret-safe STS identity summary, or an error class name."""
    try:
        import boto3
    except ImportError:
        return {"available": "0", "error_class": "ImportError"}
    try:
        identity = boto3.client("sts", region_name=region).get_caller_identity()
    except Exception as exc:  # noqa: BLE001 — diagnostic must not crash
        return {"available": "0", "error_class": type(exc).__name__}
    return {
        "available": "1",
        "account": str(identity.get("Account") or ""),
        "arn": str(identity.get("Arn") or ""),
    }


def _status_category(status: str, failure_category: str) -> str:
    """Map adapter status onto a diagnostic category."""
    cleaned = str(failure_category or "").strip()
    if cleaned:
        return cleaned
    normalized = str(status or "").strip().casefold()
    if normalized == "ok":
        return "ok"
    if normalized == "empty":
        return "empty"
    if normalized == "unavailable":
        return "unavailable"
    return normalized or "unavailable"


def main(argv: Sequence[str] | None = None) -> int:
    """Refuse by default; call Retrieve only after explicit approval."""
    args = parse_args(argv)
    reason = refuse_reason(args)
    if reason:
        print(f"refusing: {reason}", file=sys.stderr)
        return 2

    from backend.bedrock_retrieve import (
        BedrockKnowledgeBaseRetriever,
        canonical_object_key,
    )
    from backend.retrieval import (
        RetrievalQuery,
        RetrievalSource,
        course_material_id_from_object_key,
        expand_session_query_text,
    )
    from backend.settings import settings

    knowledge_base_id = str(settings.knowledge_base_id or "").strip()
    region = (
        str(settings.knowledge_base_region or "").strip()
        or str(settings.aws_region or "").strip()
        or "us-west-2"
    )
    object_key = canonical_object_key(resolve_course_object_key(args.source))
    material_id = course_material_id_from_object_key(object_key)
    title = Path(object_key).name
    group = "lectureNotes" if "/lectureNotes/" in object_key else "readings"
    payload: dict[str, Any] = {
        "kb_configured": int(bool(knowledge_base_id)),
        "region": region,
        "course_bucket_configured": int(
            bool(str(settings.course_materials_bucket or "").strip())
        ),
        "course_materials_prefix": str(settings.course_materials_prefix or ""),
        "expanded_query": expand_session_query_text(args.query),
        "object_key": object_key,
        "course_material_id": material_id,
        "strict_metadata_filter": bool(settings.knowledge_base_strict_metadata_filter),
        "knowledge_base_type": str(settings.normalized_knowledge_base_type),
        "model_provider": settings.model_provider,
        "mock_openai": bool(settings.mock_openai),
        "max_requests": int(args.max_requests),
    }
    if args.dry_run:
        print(json.dumps({"ok": False, "dry_run": True, **payload}, indent=2))
        return 0 if knowledge_base_id else 2
    if not knowledge_base_id:
        print(json.dumps({
            "ok": False,
            "category": "config_missing",
            **payload,
        }, indent=2))
        return 2

    identity = _caller_identity(region)
    retriever = BedrockKnowledgeBaseRetriever(
        knowledge_base_id,
        region=region,
        course_bucket=str(settings.course_materials_bucket or "").strip(),
        strict_metadata_filter=bool(settings.knowledge_base_strict_metadata_filter),
        knowledge_base_type=str(settings.normalized_knowledge_base_type),
    )
    inner = retriever._runtime_client()
    if inner is None:
        print(json.dumps({
            "ok": False,
            "category": "client_error",
            "caller_identity": identity,
            **payload,
        }, indent=2))
        return 2
    recorder = _CappedRetrieveClient(inner, max_requests=int(args.max_requests))
    retriever._client = recorder
    source = RetrievalSource(
        source_id="diag-course",
        label="S1",
        title=title,
        text="",
        group=group,
        object_key=object_key,
        course_material_id=material_id,
        virtual_course_source=True,
        shared_course_object=True,
    )
    result = retriever.retrieve(
        RetrievalQuery(
            current_message=str(args.query or "").strip(),
            current_stage="problem_identification",
            sources=(source,),
        )
    )
    category = _status_category(
        result.course_retrieval_status, result.failure_category
    )
    ok = result.course_retrieval_status == "ok" and bool(result.chunks)
    report = {
        "ok": ok,
        "category": category if not ok else "ok",
        "region": region,
        "raw_hit_count": recorder.raw_counts[-1] if recorder.raw_counts else 0,
        "raw_hit_counts_by_call": recorder.raw_counts,
        "validated_hit_count": len(result.chunks),
        "course_retrieval_status": result.course_retrieval_status,
        "failure_category": result.failure_category,
        "fallback_occurred": len(recorder.calls) > 1,
        "retrieve_call_count": len(recorder.calls),
        "sanitized_s3_uris": recorder.sanitized_uris[-1] if recorder.sanitized_uris else [],
        "sanitized_s3_uris_by_call": recorder.sanitized_uris,
        "caller_identity": identity,
        "object_key": object_key,
        "course_material_id": material_id,
        "strict_metadata_filter": bool(settings.knowledge_base_strict_metadata_filter),
        "knowledge_base_type": str(settings.normalized_knowledge_base_type),
    }
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

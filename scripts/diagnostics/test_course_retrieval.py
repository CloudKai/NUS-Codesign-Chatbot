"""Gated live Bedrock Knowledge Base Retrieve diagnostic (never used by pytest).

Requires ``--i-approve-live-bedrock``. This script calls ``Retrieve`` only.
It does not invoke AgentCore, Bedrock Converse, or any generation model.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

_PREVIEW_CHARS = 180


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the live Retrieve diagnostic CLI, defaulting to a refused dry check."""
    parser = argparse.ArgumentParser(
        description=(
            "One Knowledge Base Retrieve diagnostic for a selected course source. "
            "Never used by pytest. No generation call."
        )
    )
    parser.add_argument(
        "--query",
        default="what are the week 1 contents talking about?",
        help="Student-style question used as the Retrieve text.",
    )
    parser.add_argument(
        "--source",
        default="Week 1 Introduction to innovation v3.pdf",
        help="Course filename or canonical course/ object key.",
    )
    parser.add_argument(
        "--second-source",
        default="",
        help=(
            "Optional second course filename or key. Uses the multi-id in "
            "filter instead of equals."
        ),
    )
    parser.add_argument(
        "--i-approve-live-bedrock",
        action="store_true",
        help="Required acknowledgement that this calls live Bedrock Retrieve.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print resolved config and query without calling AWS.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def refuse_reason(args: argparse.Namespace) -> str | None:
    """Return a refusal message when the live Retrieve diagnostic must not run."""
    if args.dry_run:
        return None
    if not args.i_approve_live_bedrock:
        return "live course retrieval requires --i-approve-live-bedrock"
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


def _preview(text: str) -> str:
    """Return a short single-line excerpt preview without full document text."""
    cleaned = " ".join(str(text or "").split()).strip()
    if len(cleaned) <= _PREVIEW_CHARS:
        return cleaned
    return f"{cleaned[: _PREVIEW_CHARS - 1].rstrip()}…"


class _RecordingRetrieveClient:
    """Wrap a bedrock-agent-runtime client to count raw hits and fallback calls."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: list[dict[str, Any]] = []
        self.raw_counts: list[int] = []

    def retrieve(self, **kwargs: Any) -> dict[str, Any]:
        """Record one Retrieve invocation and return the live response."""
        self.calls.append(kwargs)
        response = self._inner.retrieve(**kwargs)
        hits = response.get("retrievalResults") if isinstance(response, dict) else None
        self.raw_counts.append(len(hits) if isinstance(hits, list) else 0)
        return response


def main(argv: Sequence[str] | None = None) -> int:
    """Refuse by default; call Retrieve only after the explicit approval flag."""
    args = parse_args(argv)
    reason = refuse_reason(args)
    if reason:
        print(f"refusing: {reason}", file=sys.stderr)
        return 2

    from backend.bedrock_retrieve import BedrockKnowledgeBaseRetriever, canonical_object_key
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
    filter_mode = str(settings.normalized_knowledge_base_metadata_filter_mode)
    print(
        f"metadata_filter_mode={filter_mode} (production-equivalent)",
        file=sys.stderr,
    )
    source_args = [str(args.source or "").strip()]
    second = str(getattr(args, "second_source", "") or "").strip()
    if second:
        source_args.append(second)
    resolved: list[tuple[str, str, str]] = []
    for raw in source_args:
        object_key = canonical_object_key(resolve_course_object_key(raw))
        material_id = course_material_id_from_object_key(object_key)
        group = "lectureNotes" if "/lectureNotes/" in object_key else "readings"
        resolved.append((object_key, material_id, group))
    object_key, material_id, group = resolved[0]
    material_ids = [item[1] for item in resolved if item[1]]
    if filter_mode == "required" and len(material_ids) == 1:
        filter_kind = "equals"
    elif filter_mode == "required" and len(material_ids) > 1:
        filter_kind = "in"
    else:
        filter_kind = "none"
    expanded = expand_session_query_text(args.query)
    payload = {
        "knowledge_base_id": knowledge_base_id or "(empty)",
        "region": region,
        "expanded_query": expanded,
        "course_material_id": material_id,
        "course_material_ids": material_ids,
        "object_key": object_key,
        "object_keys": [item[0] for item in resolved],
        "metadata_filter_mode": filter_mode,
        "filter_kind": filter_kind,
        "mock_openai": bool(settings.mock_openai),
        "model_provider": settings.model_provider,
    }
    if args.dry_run:
        print(json.dumps({"dry_run": True, **payload}, indent=2))
        return 0 if knowledge_base_id else 2
    if not knowledge_base_id:
        print("refusing: KNOWLEDGE_BASE_ID is not configured", file=sys.stderr)
        print(json.dumps(payload, indent=2))
        return 2

    retriever = BedrockKnowledgeBaseRetriever(
        knowledge_base_id,
        region=region,
        course_bucket=str(settings.course_materials_bucket or "").strip(),
        metadata_filter_mode=filter_mode,
        knowledge_base_type=str(settings.normalized_knowledge_base_type),
    )
    inner = retriever._runtime_client()
    if inner is None:
        print("refusing: Knowledge Base client libraries are unavailable", file=sys.stderr)
        return 2
    recorder = _RecordingRetrieveClient(inner)
    retriever._client = recorder
    sources = []
    for index, (key, mid, grp) in enumerate(resolved, start=1):
        sources.append(
            RetrievalSource(
                source_id=f"diag-course-{index}",
                label=f"S{index}",
                title=Path(key).name,
                text="",
                group=grp,
                object_key=key,
                course_material_id=mid,
                virtual_course_source=True,
                shared_course_object=True,
            )
        )
    result = retriever.retrieve(
        RetrievalQuery(
            current_message=str(args.query or "").strip(),
            current_stage="problem_identification",
            sources=tuple(sources),
        )
    )
    first_filter = False
    if recorder.calls:
        config = recorder.calls[0].get("retrievalConfiguration", {})
        search = config.get("managedSearchConfiguration") or config.get(
            "vectorSearchConfiguration", {}
        )
        first_filter = isinstance(search, dict) and "filter" in search
    report = {
        **payload,
        "raw_retrieve_result_count": recorder.raw_counts[-1] if recorder.raw_counts else 0,
        "raw_retrieve_counts_by_call": recorder.raw_counts,
        "post_validation_result_count": len(result.chunks),
        "metadata_filter_applied": first_filter,
        "strict_metadata_filter_applied": first_filter,
        "fallback_occurred": len(recorder.calls) > 1,
        "course_retrieval_status": result.course_retrieval_status,
        "chunks": [
            {
                "title": chunk.title,
                "score": chunk.score,
                "preview": _preview(chunk.text),
            }
            for chunk in result.chunks
        ],
        "placeholder_present": "[This source is stored but has no analyzable text.]"
        in result.context,
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import asyncio
import base64
import html
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

from .analysis_tool import PYTHON_TOOL, run_analysis_tool
from .file_processing import StoredUpload
from .models import ModelDefinition, get_model, validate_reasoning
from .settings import settings
from .source_library import (
    add_file_sources,
    backfill_legacy_sources,
    selected_source_context,
    source_image_input,
)
from .student_journey import (
    complete_and_advance,
    current_stage,
    default_journey,
    normalize_journey,
)
from .student_store import StudentStore
from .student_support import build_student_instructions, critical_thinking_scaffold, get_support_mode


@dataclass
class ChatOptions:
    model_id: str
    reasoning_effort: str | None = None
    support_mode: str = "critical-thinking"
    web_search: bool = False
    image_generation: bool = False
    local_analysis: bool = False
    assignment: dict[str, str] = field(default_factory=dict)
    thinking_stage: str = "focus"
    response_detail: str = "short"
    response_language: str = "English"
    source_ids: list[str] = field(default_factory=list)
    allow_model_knowledge: bool = False
    existing_user_message_id: str | None = None


@dataclass
class ChatStream:
    engine: "StudentChatEngine"
    thread_id: str
    user_message_id: str
    prompt: str
    uploads: list[StoredUpload]
    grounding_sources: list[dict[str, Any]]
    source_references: list[dict[str, Any]]
    options: ChatOptions
    text: str = ""
    assistant_message_id: str | None = None
    response_id: str | None = None
    sources: list[dict[str, str]] = field(default_factory=list)
    artifacts: list[Path] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def __iter__(self) -> Iterator[str]:
        yield from self.engine._run_stream(self)


def _safe_history_item(item: dict[str, Any]) -> dict[str, Any]:
    content = item.get("content", "")
    if isinstance(content, list):
        normalized: list[dict[str, Any]] = []
        for part in content:
            text = str(part.get("text") or "")
            if part.get("type") == "input_image":
                normalized.append(
                    {"type": "input_text", "text": "[Student included an image in this turn.]"}
                )
            elif "<notebook_sources>" in text or text.startswith(
                "The student attached the following assignment material."
            ):
                continue
            else:
                normalized.append(part)
        content = normalized
    return {"role": item.get("role", "user"), "content": content}


def response_input_for_model(
    history: list[dict[str, Any]],
    user_item: dict[str, Any],
    *,
    previous_model: str | None,
    selected_model: str,
    previous_response_id: str | None,
    previous_source_snapshot: list[str] | None = None,
    selected_source_snapshot: list[str] | None = None,
    previous_grounding_mode: str | None = None,
    selected_grounding_mode: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    can_continue = bool(previous_response_id and previous_model == selected_model)
    if selected_source_snapshot is not None:
        can_continue = can_continue and list(previous_source_snapshot or []) == list(
            selected_source_snapshot
        )
    if selected_grounding_mode is not None:
        can_continue = can_continue and previous_grounding_mode == selected_grounding_mode
    if can_continue:
        return [user_item], previous_response_id
    return [*(_safe_history_item(item) for item in history), user_item], None


def cited_source_references(
    text: str,
    references: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return only sources explicitly cited as ``[S#]`` in the reply text.

    Selected sources alone do not create a Sources-used footer. When the reply
    has no citation markers, return an empty list.
    """
    cited = {f"S{value}" for value in re.findall(r"\[S(\d+)\]", text)}
    if not cited:
        return []
    return [reference for reference in references if reference.get("label") in cited]


def _sources_from_response(response: Any) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            for annotation in getattr(content, "annotations", []) or []:
                url = getattr(annotation, "url", None)
                title = getattr(annotation, "title", None) or url
                if url and url not in seen:
                    seen.add(url)
                    sources.append({"url": url, "title": title})
    return sources


class StudentChatEngine:
    def __init__(self, store: StudentStore | None = None):
        self.store = store or StudentStore()

    def submit(
        self,
        thread_id: str,
        prompt: str,
        options: ChatOptions,
        uploads: Iterable[tuple[str, bytes, str | None]] = (),
    ) -> ChatStream:
        model = get_model(options.model_id)
        options.reasoning_effort = validate_reasoning(model, options.reasoning_effort)
        thread = self.store.get_thread(thread_id) or {}
        thread_metadata = thread.get("metadata") or {}
        journey_options = normalize_journey(
            thread_metadata.get("learning_journey")
            if isinstance(thread_metadata.get("learning_journey"), dict)
            else {
                "current_stage": options.thinking_stage,
                "response_detail": options.response_detail,
            }
        )
        journey_options["current_stage"] = options.thinking_stage
        journey_options["response_detail"] = options.response_detail
        journey_options = normalize_journey(journey_options)
        options.thinking_stage = journey_options["current_stage"]
        options.response_detail = journey_options["response_detail"]
        backfill_legacy_sources(self.store, thread_id)
        created_sources = add_file_sources(
            self.store,
            thread_id,
            uploads,
            origin="chat_composer",
        )
        stored_uploads = []
        for source in created_sources:
            path_value = source.get("path")
            if not path_value:
                continue
            stored_uploads.append(
                StoredUpload(
                    name=str(source.get("title") or "upload"),
                    path=Path(str(path_value)),
                    mime=str(source.get("mime") or "application/octet-stream"),
                    size=int(source.get("size") or 0),
                    supported=bool(
                        (source.get("metadata") or {}).get("supported", True)
                    ),
                    extracted_text=str(source.get("extractedText") or ""),
                )
            )
        available_sources = self.store.list_sources(thread_id, selected_only=True)
        if options.source_ids:
            requested = set(options.source_ids)
            available_sources = [
                source for source in available_sources if source["id"] in requested
            ]
            for source in created_sources:
                if source["id"] not in requested:
                    available_sources.append(source)
        options.source_ids = [source["id"] for source in available_sources]
        if not available_sources:
            options.allow_model_knowledge = True
        _, source_references = selected_source_context(available_sources)
        upload_metadata = [
            {
                "name": upload.name,
                "mime": upload.mime,
                "size": upload.size,
                "supported": upload.supported,
                "path": str(upload.path),
                "source_id": next(
                    (
                        source["id"]
                        for source in created_sources
                        if source.get("path") == str(upload.path)
                    ),
                    None,
                ),
            }
            for upload in stored_uploads
        ]
        user_metadata = {
            "support_mode": options.support_mode,
            "reasoning_effort": options.reasoning_effort,
            "thinking_stage": options.thinking_stage,
            "response_detail": options.response_detail,
            "response_language": options.response_language,
            "uploads": upload_metadata,
            "source_ids": options.source_ids,
            "source_refs": source_references,
            "allow_model_knowledge": options.allow_model_knowledge,
        }
        if options.existing_user_message_id:
            self.store.revise_user_message(
                thread_id,
                options.existing_user_message_id,
                prompt,
                model_id=model.id,
                metadata=user_metadata,
            )
            user_id = options.existing_user_message_id
            journey_options = self._journey_from_messages(
                self.store.get_messages(thread_id),
                response_detail=options.response_detail,
            )
            options.thinking_stage = journey_options["current_stage"]
        else:
            user_id = self.store.add_message(
                thread_id,
                "user",
                prompt,
                model_id=model.id,
                metadata=user_metadata,
            )
        self.store.update_thread(
            thread_id,
            metadata={
                "selected_model": model.id,
                "support_mode": options.support_mode,
                "assignment": options.assignment,
                "thinking_stage": options.thinking_stage,
                "response_detail": options.response_detail,
                "response_language": options.response_language,
                "allow_model_knowledge": options.allow_model_knowledge,
                "learning_journey": journey_options,
            },
        )
        return ChatStream(
            engine=self,
            thread_id=thread_id,
            user_message_id=user_id,
            prompt=prompt,
            uploads=stored_uploads,
            grounding_sources=available_sources,
            source_references=source_references,
            options=options,
        )

    @staticmethod
    def _journey_from_messages(
        messages: list[dict[str, Any]],
        *,
        response_detail: str,
    ) -> dict[str, Any]:
        journey = default_journey()
        journey["response_detail"] = response_detail
        preceding_prompt = ""
        for message in messages:
            if message.get("role") == "user":
                preceding_prompt = str(message.get("content") or "")
                continue
            metadata = message.get("metadata") or {}
            if metadata.get("stage_decision") != "advance":
                continue
            stage_id = str(metadata.get("thinking_stage") or "")
            if current_stage(journey).id != stage_id:
                continue
            journey = complete_and_advance(journey, note=preceding_prompt)
        return normalize_journey(journey)

    def _user_item(self, stream: ChatStream, model: ModelDefinition) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "input_text", "text": stream.prompt}]
        context, references = selected_source_context(stream.grounding_sources)
        stream.source_references = references
        if context:
            content.append(
                {
                    "type": "input_text",
                    "text": (
                        "<notebook_sources>\n"
                        "Use these selected notebook sources for this turn. Cite factual claims "
                        "with their exact bracketed labels, such as [S1].\n\n"
                        f"{context}\n</notebook_sources>"
                    ),
                }
            )
        if model.vision:
            for source in stream.grounding_sources:
                image_part = source_image_input(source)
                if image_part:
                    content.append(image_part)
        return {"role": "user", "content": content}

    def _instructions(self, options: ChatOptions) -> str:
        assignment = options.assignment
        instructions = build_student_instructions(
            options.support_mode,
            assignment_title=assignment.get("title", ""),
            assignment_brief=assignment.get("brief", ""),
            rubric=assignment.get("rubric", ""),
            course_context=assignment.get("course", ""),
            thinking_stage_id=options.thinking_stage,
            response_detail=options.response_detail,
            response_language=options.response_language,
        )
        if options.source_ids:
            instructions += (
                "\n\nSOURCE GROUNDING:\n"
                "- Treat the selected notebook sources as the primary evidence base.\n"
                "- Cite source-supported claims with the supplied labels exactly, for example "
                "[S1] or [S2].\n"
                "- Never invent a source label, quotation, or claim that is absent from the "
                "selected material.\n"
            )
            if options.allow_model_knowledge:
                instructions += (
                    "- Broader model knowledge is allowed, but clearly distinguish it from "
                    "source-supported claims and do not attach notebook citations to it.\n"
                )
            else:
                instructions += (
                    "- Use only the selected sources for factual claims. If they do not support "
                    "an answer, say what is missing and ask the student for another source.\n"
                )
        else:
            instructions += (
                "\n\nNo notebook sources are selected. You may use general model knowledge, "
                "while remaining explicit about uncertainty and never fabricating citations.\n"
            )
        return instructions

    def _tools(self, model: ModelDefinition, options: ChatOptions) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        if options.web_search and model.web_search:
            tools.append({"type": "web_search"})
        if options.image_generation and model.image_generation:
            tools.append({"type": "image_generation"})
        if options.local_analysis and settings.enable_local_code_execution and model.function_calling:
            tools.append(PYTHON_TOOL)
        return tools

    def _run_stream(self, stream: ChatStream) -> Iterator[str]:
        model = get_model(stream.options.model_id)
        try:
            if settings.mock_openai:
                yield from self._mock_stream(stream, model)
            else:
                yield from self._openai_stream(stream, model)
        except (RateLimitError, APIStatusError, APIConnectionError, RuntimeError, ValueError) as exc:
            stream.error = self._friendly_error(exc, model)
            stream.text = stream.error
            yield stream.error
        except Exception as exc:
            stream.error = f"The assistant could not complete this turn ({type(exc).__name__})."
            stream.text = stream.error
            yield stream.error
        finally:
            if not stream.text:
                stream.text = "The assistant did not return any text. Please try again."
            thread = self.store.get_thread(stream.thread_id) or {}
            metadata = thread.get("metadata") or {}
            journey = normalize_journey(
                metadata.get("learning_journey")
                if isinstance(metadata.get("learning_journey"), dict)
                else {
                    "current_stage": stream.options.thinking_stage,
                    "response_detail": stream.options.response_detail,
                    "response_language": stream.options.response_language,
                }
            )
            # Legacy Responses API turns never mutate the learning stage. New
            # structured workflow turns create a persisted recommendation that
            # the student must explicitly confirm through the API/UI.
            stage_decision = "stay"
            stream.text = re.sub(
                r"<!--\s*stage\s*:\s*(?:advance|stay)\s*-->",
                "",
                stream.text,
                flags=re.IGNORECASE,
            ).strip() or stream.text
            next_stage = current_stage(journey).id
            self.store.update_thread(
                stream.thread_id,
                metadata={
                    "learning_journey": journey,
                    "thinking_stage": next_stage,
                    "response_detail": journey["response_detail"],
                    "response_language": stream.options.response_language,
                },
            )
            cited_references = cited_source_references(
                stream.text,
                stream.source_references,
            )
            stream.assistant_message_id = self.store.add_message(
                stream.thread_id,
                "assistant",
                stream.text,
                model_id=model.id,
                metadata={
                    "support_mode": stream.options.support_mode,
                    "reasoning_effort": stream.options.reasoning_effort,
                    "thinking_stage": stream.options.thinking_stage,
                    "response_detail": stream.options.response_detail,
                    "response_language": stream.options.response_language,
                    "sources": stream.sources,
                    "artifacts": [str(path) for path in stream.artifacts],
                    "response_id": stream.response_id,
                    "source_ids": stream.options.source_ids,
                    "source_refs": cited_references,
                    "allow_model_knowledge": stream.options.allow_model_knowledge,
                    "stage_decision": stage_decision,
                    "next_thinking_stage": next_stage,
                },
                is_error=bool(stream.error),
            )
            self.store.record_turn(
                stream.thread_id,
                stream.user_message_id,
                stream.assistant_message_id,
                model.id,
                stream.options.reasoning_effort,
                stream.usage,
            )

    def _mock_stream(self, stream: ChatStream, model: ModelDefinition) -> Iterator[str]:
        mode = get_support_mode(stream.options.support_mode)
        stage = current_stage({"current_stage": stream.options.thinking_stage})
        attached = ", ".join(upload.name for upload in stream.uploads)
        if stream.options.response_detail == "short":
            answer = (
                f"**{stage.label}**\n\n"
                "Make this step more precise with one concrete detail.\n\n"
                f"**Next:** {stage.reflection_prompt}"
            )
        else:
            scaffold = "\n".join(
                f"{index}. {question}"
                for index, question in enumerate(critical_thinking_scaffold(), start=1)
            )
            answer = (
                f"You are previewing {mode.label} with {model.label}.\n\n"
                f"**Current stage: {stage.label}.** {stage.description}\n\n"
                f"A useful critical-thinking pass is:\n{scaffold}\n\n"
                "As the student author, write your current claim, identify the strongest "
                "evidence for it, and name one reason that evidence might be insufficient. "
                "I can help you test the next step without taking over authorship.\n\n"
                f"**Reflect:** {stage.reflection_prompt}"
            )
        if attached:
            answer += f"\n\nAttached assignment material saved for this chat: {attached}."
        if stream.options.web_search:
            answer += "\n\nWeb search is selected; mock mode does not contact the internet."
        if stream.options.image_generation:
            artifact = self._mock_image(stream.thread_id, stream.prompt)
            stream.artifacts.append(artifact)
            answer += "\n\nA mock concept image was generated for the interface preview."
        for chunk in self._chunk(answer):
            stream.text += chunk
            yield chunk
        state = self.store.get_state(stream.thread_id)
        history = list(state.get("history", []))
        history.extend(
            [
                {"role": "user", "content": stream.prompt},
                {"role": "assistant", "content": stream.text},
            ]
        )
        self.store.save_state(
            stream.thread_id,
            previous_response_id=None,
            model_id=model.id,
            history=history,
            source_snapshot=stream.options.source_ids,
            grounding_mode=(
                "hybrid" if stream.options.allow_model_knowledge else "source_first"
            ),
        )
        stream.usage = {"mock": True}

    def _openai_stream(self, stream: ChatStream, model: ModelDefinition) -> Iterator[str]:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured. Use MOCK_OPENAI=true to preview.")
        client = OpenAI(api_key=settings.openai_api_key)
        state = self.store.get_state(stream.thread_id)
        history = list(state.get("history", []))
        user_item = self._user_item(stream, model)
        current_input, previous_response_id = response_input_for_model(
            history,
            user_item,
            previous_model=state.get("modelId"),
            selected_model=model.id,
            previous_response_id=state.get("previousResponseId"),
            previous_source_snapshot=state.get("sourceSnapshot"),
            selected_source_snapshot=stream.options.source_ids,
            previous_grounding_mode=state.get("groundingMode"),
            selected_grounding_mode=(
                "hybrid" if stream.options.allow_model_knowledge else "source_first"
            ),
        )
        tools = self._tools(model, stream.options)
        completed_response: Any = None
        final_response_id: str | None = None

        for _ in range(settings.max_tool_iterations):
            kwargs: dict[str, Any] = {
                "model": model.id,
                "instructions": self._instructions(stream.options),
                "input": current_input,
                "stream": True,
                "store": True,
            }
            if stream.options.reasoning_effort:
                kwargs["reasoning"] = {"effort": stream.options.reasoning_effort}
            if previous_response_id:
                kwargs["previous_response_id"] = previous_response_id
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            if stream.options.web_search and model.web_search:
                kwargs["include"] = ["web_search_call.action.sources"]

            function_calls: list[Any] = []
            response_stream = client.responses.create(**kwargs)
            for event in response_stream:
                event_type = getattr(event, "type", "")
                if event_type == "response.created":
                    final_response_id = event.response.id
                elif event_type == "response.output_text.delta":
                    stream.text += event.delta
                    yield event.delta
                elif event_type == "response.output_item.done":
                    item = event.item
                    item_type = getattr(item, "type", "")
                    if item_type == "function_call":
                        function_calls.append(item)
                    elif item_type == "image_generation_call":
                        artifact = self._save_generated_image(stream.thread_id, item)
                        if artifact:
                            stream.artifacts.append(artifact)
                elif event_type == "response.completed":
                    completed_response = event.response
                    final_response_id = event.response.id
                    usage = getattr(event.response, "usage", None)
                    if usage:
                        stream.usage = usage.model_dump(mode="json")

            if not function_calls:
                break
            outputs = []
            for call in function_calls:
                output, artifacts = asyncio.run(
                    run_analysis_tool(
                        stream.thread_id,
                        call.name,
                        getattr(call, "arguments", "{}"),
                    )
                )
                stream.artifacts.extend(artifacts)
                outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": output,
                    }
                )
            current_input = outputs
            previous_response_id = final_response_id
        else:
            warning = "\n\nTool execution stopped after the configured safety limit."
            stream.text += warning
            yield warning

        stream.response_id = final_response_id
        if completed_response:
            stream.sources = _sources_from_response(completed_response)
        if not stream.text and stream.artifacts:
            stream.text = "I generated the requested output. Review the file below."
            yield stream.text
        history.extend(
            [
                {"role": "user", "content": stream.prompt},
                {"role": "assistant", "content": stream.text},
            ]
        )
        self.store.save_state(
            stream.thread_id,
            previous_response_id=final_response_id,
            model_id=model.id,
            history=history,
            vector_store_id=state.get("vectorStoreId"),
            source_snapshot=stream.options.source_ids,
            grounding_mode=(
                "hybrid" if stream.options.allow_model_knowledge else "source_first"
            ),
        )

    def _mock_image(self, thread_id: str, prompt: str) -> Path:
        workspace = (settings.workspaces_dir / thread_id).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        path = workspace / f"concept-{uuid.uuid4().hex[:8]}.svg"
        safe_prompt = html.escape(" ".join(prompt.split())[:120])
        path.write_text(
            f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="700">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop stop-color="#6d5dfc"/><stop offset="1" stop-color="#16a3a6"/></linearGradient></defs>
<rect width="1200" height="700" rx="36" fill="#0f1423"/>
<circle cx="190" cy="160" r="120" fill="url(#g)" opacity=".9"/>
<text x="90" y="380" fill="#fff" font-family="Arial" font-size="54" font-weight="700">
Co-design concept</text>
<text x="90" y="455" fill="#cbd5e1" font-family="Arial" font-size="30">{safe_prompt}</text>
</svg>""",
            encoding="utf-8",
        )
        return path

    def _save_generated_image(self, thread_id: str, item: Any) -> Path | None:
        result = getattr(item, "result", None)
        if not result:
            return None
        workspace = (settings.workspaces_dir / thread_id).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        path = workspace / f"generated-{uuid.uuid4().hex[:8]}.png"
        path.write_bytes(base64.b64decode(result))
        return path

    @staticmethod
    def _chunk(text: str, size: int = 42) -> Iterator[str]:
        for index in range(0, len(text), size):
            yield text[index : index + size]

    @staticmethod
    def _friendly_error(error: Exception, model: ModelDefinition) -> str:
        if isinstance(error, RateLimitError):
            return f"{model.label} is currently rate-limited. Wait briefly and retry."
        if isinstance(error, APIStatusError):
            return (
                f"{model.label} could not complete this request (HTTP {error.status_code}). "
                "Check that this API project can access the selected model. No fallback was used."
            )
        if isinstance(error, APIConnectionError):
            return "The OpenAI connection failed. Check the network and retry."
        return str(error)

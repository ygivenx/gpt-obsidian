from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections import Counter

from .models import Conversation, ConversationInsights

STOPWORDS = {
    "the",
    "and",
    "that",
    "this",
    "with",
    "from",
    "your",
    "have",
    "just",
    "what",
    "when",
    "where",
    "which",
    "will",
    "would",
    "could",
    "should",
    "about",
    "into",
    "than",
    "then",
    "them",
    "they",
    "their",
    "there",
    "here",
    "also",
    "because",
    "been",
    "were",
    "being",
    "http",
    "https",
    "chatgpt",
    "assistant",
    "user",
    "please",
    "thanks",
    "thank",
    "you",
    "for",
    "can",
}

DECISION_HINTS = ("decide", "decision", "chose", "choose", "selected", "we will", "i'll", "we'll")
ACTION_HINTS = (
    "todo",
    "to do",
    "next step",
    "next steps",
    "action",
    "follow up",
    "implement",
    "run",
    "fix",
    "update",
)


class InsightError(RuntimeError):
    pass


def build_insights(
    conversation: Conversation,
    summary_provider: str,
    summary_model: str | None,
    summary_max_bullets: int,
    tag_provider: str,
    tag_model: str | None,
    topic_tag_limit: int,
    enable_topic_tags: bool,
) -> ConversationInsights:
    heuristic = build_heuristic_insights(
        conversation=conversation,
        summary_max_bullets=summary_max_bullets,
        topic_tag_limit=topic_tag_limit,
        enable_topic_tags=enable_topic_tags,
    )

    summary = {
        "summary_bullets": heuristic.summary_bullets,
        "key_decisions": heuristic.key_decisions,
        "action_items": heuristic.action_items,
        "open_questions": heuristic.open_questions,
    }

    if summary_provider == "openai":
        if not summary_model:
            raise InsightError("OpenAI summary mode requires --summary-model")
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise InsightError("OPENAI_API_KEY is required when --summary-provider openai")
        summary = _openai_summarize(conversation, summary_model, summary_max_bullets, api_key)
    elif summary_provider != "heuristic":
        raise InsightError(f"Unsupported summary provider: {summary_provider}")

    topic_tags = heuristic.topic_tags
    if enable_topic_tags and tag_provider == "openai":
        if not tag_model:
            raise InsightError("OpenAI tag mode requires --tag-model")
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise InsightError("OPENAI_API_KEY is required when --tag-provider openai")
        topic_tags = _openai_tags(conversation, tag_model, topic_tag_limit, api_key)
    elif enable_topic_tags and tag_provider != "heuristic":
        raise InsightError(f"Unsupported tag provider: {tag_provider}")

    return ConversationInsights(
        summary_bullets=_clean_items(summary.get("summary_bullets"), summary_max_bullets),
        key_decisions=_clean_items(summary.get("key_decisions"), summary_max_bullets),
        action_items=_clean_items(summary.get("action_items"), summary_max_bullets),
        open_questions=_clean_items(summary.get("open_questions"), summary_max_bullets),
        topic_tags=_clean_tags(topic_tags, topic_tag_limit) if enable_topic_tags else [],
        contains_code=heuristic.contains_code,
        contains_images=heuristic.contains_images,
        message_count=heuristic.message_count,
    )


def build_heuristic_insights(
    conversation: Conversation,
    summary_max_bullets: int,
    topic_tag_limit: int,
    enable_topic_tags: bool,
) -> ConversationInsights:
    texts: list[str] = []
    for msg in conversation.messages:
        if msg.text_markdown:
            texts.append(msg.text_markdown)

    sentences = _extract_sentences(texts)

    summary_bullets = sentences[:summary_max_bullets] if sentences else []
    decisions = [s for s in sentences if _contains_any(s, DECISION_HINTS)][:summary_max_bullets]
    actions = [s for s in sentences if _contains_any(s, ACTION_HINTS)][:summary_max_bullets]
    open_questions = [s for s in sentences if s.endswith("?")][:summary_max_bullets]

    contains_code = any(_looks_like_code(t) for t in texts)
    contains_images = any(_looks_like_image(att.display_name) for att in conversation.attachments)
    tags = infer_topic_tags(texts, limit=topic_tag_limit) if enable_topic_tags else []

    return ConversationInsights(
        summary_bullets=summary_bullets,
        key_decisions=decisions,
        action_items=actions,
        open_questions=open_questions,
        topic_tags=tags,
        contains_code=contains_code,
        contains_images=contains_images,
        message_count=len(conversation.messages),
    )


def infer_topic_tags(texts: list[str], limit: int) -> list[str]:
    tokens: list[str] = []
    for text in texts:
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", text.lower()):
            if token in STOPWORDS:
                continue
            if token.isdigit():
                continue
            tokens.append(token)

    counts = Counter(tokens)
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [word for word, _ in ranked[:limit]]


def _extract_sentences(texts: list[str]) -> list[str]:
    out: list[str] = []
    for text in texts:
        normalized = re.sub(r"\s+", " ", text.strip())
        if not normalized:
            continue
        parts = re.split(r"(?<=[.!?])\s+", normalized)
        for part in parts:
            candidate = part.strip(" -\t")
            if len(candidate) < 20:
                continue
            out.append(candidate)
    return out


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(token in lower for token in needles)


def _looks_like_code(text: str) -> bool:
    return (
        "```" in text
        or "def " in text
        or "class " in text
        or "import " in text
        or "{" in text and "}" in text
        or "=>" in text
    )


def _looks_like_image(name: str) -> bool:
    ext = name.lower().rsplit(".", 1)
    if len(ext) != 2:
        return False
    return ext[1] in {"png", "jpg", "jpeg", "gif", "webp", "svg", "bmp"}


def _openai_summarize(
    conversation: Conversation,
    model: str,
    summary_max_bullets: int,
    api_key: str,
) -> dict:
    prompt = {
        "conversation_id": conversation.id,
        "title": conversation.title,
        "max_bullets": summary_max_bullets,
        "transcript": _transcript_rows(conversation),
        "instructions": (
            "Return compact JSON with keys summary_bullets, key_decisions, action_items, open_questions. "
            "Each value must be an array of short strings."
        ),
    }
    return _openai_json_request(model=model, api_key=api_key, prompt=prompt, schema_name="conversation_summary", schema={
        "type": "object",
        "properties": {
            "summary_bullets": {"type": "array", "items": {"type": "string"}},
            "key_decisions": {"type": "array", "items": {"type": "string"}},
            "action_items": {"type": "array", "items": {"type": "string"}},
            "open_questions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary_bullets", "key_decisions", "action_items", "open_questions"],
        "additionalProperties": False,
    })


def _openai_tags(conversation: Conversation, model: str, topic_tag_limit: int, api_key: str) -> list[str]:
    prompt = {
        "conversation_id": conversation.id,
        "title": conversation.title,
        "max_tags": topic_tag_limit,
        "transcript": _transcript_rows(conversation),
        "instructions": (
            "Return JSON with key topic_tags as list of concise canonical topic names in kebab-case only. "
            "No duplicates, no generic words, max length 32 per tag."
        ),
    }
    parsed = _openai_json_request(model=model, api_key=api_key, prompt=prompt, schema_name="conversation_tags", schema={
        "type": "object",
        "properties": {
            "topic_tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["topic_tags"],
        "additionalProperties": False,
    })
    return _clean_tags(parsed.get("topic_tags"), topic_tag_limit)


def _transcript_rows(conversation: Conversation) -> list[str]:
    transcript = []
    for msg in conversation.messages:
        role = (msg.role or "unknown").lower()
        text = (msg.text_markdown or "").strip()
        if not text:
            continue
        transcript.append(f"[{role}] {text}")
    return transcript


def _openai_json_request(model: str, api_key: str, prompt: dict, schema_name: str, schema: dict) -> dict:
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(
            {
                "model": model,
                "input": [
                    {
                        "role": "system",
                        "content": [{"type": "input_text", "text": "Return strict JSON only."}],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": json.dumps(prompt)}],
                    },
                ],
                "max_output_tokens": 500,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "strict": True,
                        "schema": schema,
                    }
                },
            }
        ).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise InsightError(f"OpenAI API error: {exc.code} {body[:300]}") from exc
    except urllib.error.URLError as exc:
        raise InsightError(f"OpenAI network error: {exc}") from exc

    text_out = payload.get("output_text")
    if isinstance(text_out, str):
        try:
            parsed = json.loads(text_out)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                    try:
                        parsed = json.loads(part["text"])
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        continue

    raise InsightError("OpenAI response did not contain valid JSON output")


def _clean_items(value: object, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        normalized = re.sub(r"\s+", " ", item).strip(" -\t")
        if len(normalized) < 8:
            continue
        out.append(normalized)
        if len(out) >= limit:
            break
    return out


def _clean_tags(value: object, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            continue
        token = raw.strip().lower()
        token = token.replace("#", "")
        token = re.sub(r"\s+", "-", token)
        token = token.replace("_", "-")
        token = re.sub(r"[^a-z0-9/-]", "", token)
        token = token.strip("-/")
        if not token:
            continue
        if "/" in token:
            token = token.split("/", 1)[1]
        token = token.strip("-")
        token = re.sub(r"-{2,}", "-", token)
        if len(token) < 2:
            continue
        if token in STOPWORDS:
            continue
        normalized = token[:32]
        if normalized in out:
            continue
        out.append(normalized)
        if len(out) >= limit:
            break
    return out

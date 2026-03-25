import requests

from bot_logic import normalize_spaces, sanitize_user_text, strip_trigger
from decision_tree import build_web_search_decision


class WebSearchError(RuntimeError):
    pass


def should_enable_web_search(
    message: str,
    viewer_context: str = "",
    global_context: str = "",
    mode: str = "auto",
) -> bool:
    lowered = sanitize_user_text(strip_trigger(message)).lower()
    context_text = f"{viewer_context}\n{global_context}".lower()
    decision = build_web_search_decision(lowered, context_text, mode=mode)
    return bool(decision.needs_web)


def search_searxng(
    query: str,
    base_url: str,
    timeout_seconds: int,
    max_results: int = 5,
) -> list[dict]:
    response = requests.get(
        f"{base_url}/search",
        params={
            "q": sanitize_user_text(query),
            "format": "json",
            "language": "fr",
            "safesearch": 1,
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    results = payload.get("results", [])
    if not isinstance(results, list):
        return []
    cleaned_results: list[dict] = []
    for item in results[:max_results]:
        if not isinstance(item, dict):
            continue
        title = sanitize_user_text(item.get("title", ""))
        url = sanitize_user_text(item.get("url", ""))
        content = sanitize_user_text(item.get("content", ""))
        if not title and not content:
            continue
        cleaned_results.append({
            "title": title,
            "url": url,
            "content": content,
        })
    return cleaned_results


def build_web_search_query(
    message: str,
    viewer_context: str = "",
    global_context: str = "",
) -> str:
    cleaned = sanitize_user_text(strip_trigger(message))
    context_text = sanitize_user_text(f"{viewer_context}\n{global_context}")
    decision = build_web_search_decision(cleaned, context_text, mode="auto")
    if decision.needs_web and decision.query:
        query = str(decision.query)
        if query != cleaned:
            return query

    return cleaned


def build_web_search_context(results: list[dict]) -> str:
    if not results:
        return "aucun"

    lines: list[str] = []
    for index, item in enumerate(results, start=1):
        title = sanitize_user_text(item.get("title", ""))
        content = sanitize_user_text(item.get("content", ""))
        url = sanitize_user_text(item.get("url", ""))
        line = f"[{index}] {title}" if title else f"[{index}]"
        if content:
            line += f" - {content}"
        if url:
            line += f" ({url})"
        lines.append(line.strip())
    return "\n".join(lines) if lines else "aucun"

import requests
import re

from bot_logic import normalize_spaces, sanitize_user_text, strip_trigger


class WebSearchError(RuntimeError):
    pass


def should_enable_web_search(
    message: str,
    viewer_context: str = "",
    global_context: str = "",
    mode: str = "auto",
) -> bool:
    normalized_mode = normalize_spaces((mode or "auto").lower())
    if normalized_mode == "always":
        return True
    if normalized_mode in {"off", "false", "0", "disabled"}:
        return False

    lowered = sanitize_user_text(strip_trigger(message)).lower()
    context_text = f"{viewer_context}\n{global_context}".lower()
    trigger_fragments = (
        "aujourd'hui",
        "today",
        "demain",
        "semaine",
        "en ce moment",
        "actu",
        "actualité",
        "actualite",
        "news",
        "dernières nouvelles",
        "dernieres nouvelles",
        "dernières infos",
        "dernieres infos",
        "recherche sur le web",
        "cherche sur le web",
        "cherche sur internet",
        "sur internet",
        "sur le web",
        "internet",
        "web",
        "météo",
        "meteo",
        "prix du",
        "cours du",
        "score du match",
        "résultat du match",
        "resultat du match",
        "président",
        "president",
        "premier ministre",
        "date de sortie",
        "sorti quand",
        "sortie de",
        "meilleur film",
        "meilleure série",
        "meilleure serie",
        "meilleur serie",
        "films à l'affiche",
        "films a l'affiche",
        "films a l affiche",
        "reuters",
        "première page",
        "premiere page",
    )
    if any(fragment in lowered for fragment in trigger_fragments):
        return True

    followup_fragments = (
        "et pour demain",
        "et demain",
        "et pour cette semaine",
        "et pour la semaine",
        "et à lyon",
        "et a lyon",
        "et à paris",
        "et a paris",
        "et du coup",
    )
    context_indicators = (
        "météo",
        "meteo",
        "actualité",
        "actualite",
        "reuters",
        "film",
        "films",
        "à l'affiche",
        "a l'affiche",
        "a l affiche",
        "selon les données",
        "selon les donnees",
    )
    if any(fragment in lowered for fragment in followup_fragments) and any(indicator in context_text for indicator in context_indicators):
        return True

    if "qui est" in lowered or "qu'est ce que" in lowered or "qu est ce que" in lowered:
        if context_text.strip() in {"", "aucun"}:
            return True

    return False


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
    lowered = cleaned.lower()
    context_text = sanitize_user_text(f"{viewer_context}\n{global_context}")
    context_lower = context_text.lower()

    if any(fragment in lowered for fragment in ("et pour demain", "et demain", "pour demain")):
        location_match = re.search(r"\b(?:à|a)\s+([A-ZÀ-ÖØ-öø-ÿ][a-zà-öø-ÿ-]+)\b", context_text)
        if "météo" in context_lower or "meteo" in context_lower:
            if location_match:
                return f"météo demain à {location_match.group(1)}"
            return "météo demain"

    if "reuters" in lowered and ("première page" in lowered or "premiere page" in lowered or "actualité" in lowered or "actualite" in lowered):
        return "Reuters actualité première page"

    if "meilleur film" in lowered and "2025" in lowered:
        return "meilleur film 2025"

    if "films à l'affiche" in lowered or "films a l'affiche" in lowered or "films a l affiche" in lowered:
        city_match = re.search(r"\b(?:à|a)\s+([A-ZÀ-ÖØ-öø-ÿ][a-zà-öø-ÿ-]+)\b", cleaned)
        if city_match:
            return f"films à l'affiche cette semaine {city_match.group(1)}"

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

from __future__ import annotations

import re


def clean_line(text: str) -> str:
    cleaned = " ".join(str(text or "").strip().split())
    cleaned = re.sub(r"^([\-\*\u2022\u25E6•▪►]+|\d+[\.\)])\s*", "", cleaned).strip()
    return cleaned.strip(" \t\r\n-•,;")


def finalize_sentence(text: str) -> str:
    cleaned = clean_line(text)
    if not cleaned:
        return ""
    cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned if cleaned[-1] in ".!?" else f"{cleaned}."


def fallback_task_descriptions(text: str) -> list[str]:
    stripped = re.sub(
        r"^\s*(?:add|create)\s+(?:these\s+)?(?:\d+|two|three|four|five)?\s*tasks?\s*:?\s*",
        "",
        str(text or "").strip(),
        flags=re.IGNORECASE,
    )
    chunks = [chunk for chunk in re.split(r"[\n;]+", stripped) if chunk.strip()]
    if len(chunks) == 1 and re.search(r"\b(?:2|two)\s+tasks?\b", text, flags=re.IGNORECASE):
        chunks = [chunk for chunk in re.split(r"\s+\band\s+", chunks[0], maxsplit=1, flags=re.IGNORECASE) if chunk.strip()]

    descriptions: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        description = finalize_sentence(chunk)
        lowered = description.lower()
        if not description or lowered in seen:
            continue
        seen.add(lowered)
        descriptions.append(description)
    return descriptions


def guess_kr_metric(line: str) -> tuple[str, str]:
    patterns = (
        (r"(\d+(?:[.,]\d+)?)\s*%", "%", lambda m: f"{m.group(1)}%"),
        (r"€\s*(\d[\d.,]*\s*(?:k|m|M|K)?)", "€", lambda m: "€" + m.group(1).replace(" ", "")),
        (r"\$\s*(\d[\d.,]*\s*(?:k|m|M|K)?)", "$", lambda m: "$" + m.group(1).replace(" ", "")),
        (r"\b(\d+)\s+(deals|hires|engineers|customers|users|signups|RFCs|interviews|calls|testimonials|loops)\b", "", lambda m: m.group(1)),
        (r"\bNPS\s*(\d+)\+?", "NPS", lambda m: m.group(1)),
    )
    for pattern, metric, target_fn in patterns:
        match = re.search(pattern, line, flags=re.IGNORECASE)
        if match:
            return metric or match.group(2).lower(), target_fn(match)
    return "", ""


def fallback_key_results(text: str) -> list[dict[str, str]]:
    key_results: list[dict[str, str]] = []
    for raw_line in str(text or "").splitlines():
        description = clean_line(raw_line)
        if not description:
            continue
        metric, target = guess_kr_metric(description)
        key_results.append({"description": description[0].upper() + description[1:], "metric": metric, "target": target})
    return key_results

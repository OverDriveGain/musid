import json
import re
from collections import Counter
from typing import List, Optional, Tuple

import httpx

from src.config.config import config
from src.types.types import TrackEntry

OLLAMA_RETRIES = 3  # number of times to ask Ollama, majority wins

DESCRIPTION_PROMPT = """\
You are analyzing a YouTube video description to extract a song tracklist.
A tracklist pairs timestamps (0:00, 3:45, 1:02:34) with song titles.

Description:
{description}

If the description contains a tracklist, respond ONLY with this JSON:
{{"found": true, "tracks": [{{"timestamp": "0:00", "title": "Song Name"}}]}}

If there is no tracklist, respond ONLY with:
{{"found": false}}

Rules:
- A real tracklist has at least 3 timestamp+title pairs.
- Respond with ONLY the JSON object, no other text.\
"""

BATCH_PROMPT = """\
You are analyzing YouTube comments to find a tracklist comment.
A tracklist comment has multiple lines each pairing a timestamp (0:00, 3:45, 1:02:34) with a song title — for a continuous music mix or album video.

Comments:
{comments}

If you find a tracklist comment, respond ONLY with this JSON:
{{"found": true, "index": <number>, "tracks": [{{"timestamp": "0:00", "title": "Song Name"}}]}}

If no tracklist comment exists, respond ONLY with:
{{"found": false}}

Rules:
- A real tracklist has at least 3 timestamp+title pairs.
- Respond with ONLY the JSON object, no other text.\
"""


def _timestamp_to_seconds(ts: str) -> int:
    parts = [int(p) for p in ts.strip().split(":")]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return 0


def _tracks_fingerprint(tracks: list) -> Tuple:
    """Stable key representing a tracklist — used for majority voting."""
    return tuple((t.get("timestamp", ""), t.get("title", "").lower().strip()) for t in tracks)


async def _ask_ollama(prompt: str) -> Optional[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{config['ollama_url']}/api/generate",
            json={"model": config["ollama_model"], "prompt": prompt, "stream": False},
            timeout=120.0,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()
    return _parse_json(raw)


async def _ask_ollama_with_vote(prompt: str, label: str) -> Optional[dict]:
    """
    Ask Ollama OLLAMA_RETRIES times and return the majority result.
    If no majority, returns the first valid result.
    """
    results = []
    for attempt in range(1, OLLAMA_RETRIES + 1):
        print(f"[Ollama] {label} — attempt {attempt}/{OLLAMA_RETRIES} ...")
        try:
            parsed = await _ask_ollama(prompt)
            if parsed is not None:
                results.append(parsed)
                print(f"[Ollama]   → found={parsed.get('found')}  tracks={len(parsed.get('tracks', []))}")
            else:
                print(f"[Ollama]   → invalid response")
        except Exception as e:
            print(f"[Ollama]   → error: {e}")

    if not results:
        return None

    # Majority vote on "found" first
    found_votes = Counter(r.get("found", False) for r in results)
    majority_found = found_votes.most_common(1)[0][0]
    print(f"[Ollama] Vote: found={majority_found} ({found_votes})")

    if not majority_found:
        return None

    # Among results that said "found", vote on the tracklist fingerprint
    found_results = [r for r in results if r.get("found") and r.get("tracks")]
    if not found_results:
        return None

    fingerprint_counter = Counter(_tracks_fingerprint(r["tracks"]) for r in found_results)
    best_fingerprint, count = fingerprint_counter.most_common(1)[0]
    print(f"[Ollama] Tracklist agreement: {count}/{len(found_results)} responses match")

    # Return the result matching the majority fingerprint
    for r in found_results:
        if _tracks_fingerprint(r["tracks"]) == best_fingerprint:
            return r

    return found_results[0]


class TracklistDetector:
    async def detect_from_description(self, description: str) -> Optional[dict]:
        prompt = DESCRIPTION_PROMPT.format(description=description[:3000])
        parsed = await _ask_ollama_with_vote(prompt, "description")
        if parsed is None:
            return None

        tracks = []
        for t in parsed.get("tracks", []):
            ts = t.get("timestamp", "0:00")
            title = t.get("title", "").strip()
            if ts and title:
                tracks.append(TrackEntry(timestamp=ts, seconds=_timestamp_to_seconds(ts), title=title))

        return {"tracks": tracks, "comment_author": "", "comment_text": "", "like_count": 0} if tracks else None

    async def detect_from_batch(self, comments: list[dict]) -> Optional[dict]:
        entries = []
        for i, c in enumerate(comments):
            text = c.get("text", "").strip().replace("\n", " | ")
            if len(text) > 500:
                text = text[:500] + "..."
            entries.append(f"[{i}] {text}")

        prompt = BATCH_PROMPT.format(comments="\n".join(entries))
        parsed = await _ask_ollama_with_vote(prompt, "comments")
        if parsed is None:
            return None

        idx = parsed.get("index")
        if idx is None or not (0 <= idx < len(comments)):
            return None

        tracks = []
        for t in parsed.get("tracks", []):
            ts = t.get("timestamp", "0:00")
            title = t.get("title", "").strip()
            if ts and title:
                tracks.append(TrackEntry(timestamp=ts, seconds=_timestamp_to_seconds(ts), title=title))

        if not tracks:
            return None

        comment = comments[idx]
        return {
            "comment_author": comment.get("author_name", ""),
            "comment_text": comment.get("text", ""),
            "like_count": comment.get("like_count", 0),
            "tracks": tracks,
        }


def _parse_json(raw: str) -> Optional[dict]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None

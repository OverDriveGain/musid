import asyncio
import json
import os
import re
import tempfile
from typing import Dict, List, Optional, Tuple

import httpx

from mutagen.id3 import ID3, ID3NoHeaderError
from pydub import AudioSegment
from shazamio import Shazam

from src.config.config import config
from src.services.album_recognizer import AlbumRecognizer
from src.services.shazam_tagger import ShazamTagger
from src.services.tracklist_detector import TracklistDetector
from src.services.youtube_comments import YoutubeCommentsService

SAMPLE_CHUNK_MS = 15_000   # 15s Shazam probe at each interval point
INTERVAL_MS = 120_000      # probe every 120 seconds
ALBUM_THRESHOLD = 2        # distinct songs needed to treat as album


def _downloads_dir() -> str:
    return os.path.join(config["music_path"], config["download_folder"])


def _resolve_file(filename: str) -> str:
    return os.path.join(_downloads_dir(), filename)


def _safe_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip()


def _read_youtube_url(file_path: str) -> Optional[str]:
    try:
        tags = ID3(file_path)
        for key in tags.keys():
            if key.startswith("COMM"):
                text = str(tags[key].text[0]).strip()
                if "youtube.com" in text or "youtu.be" in text:
                    return text
    except Exception:
        pass
    return None


async def _identify_type(file_path: str) -> Tuple[int, List[Tuple[str, str]]]:
    """
    Sample audio every 120s with a 15s Shazam probe.
    Stops early once ALBUM_THRESHOLD distinct songs are identified.
    """
    audio = AudioSegment.from_file(file_path)
    total_ms = len(audio)
    duration_min = total_ms // 60000
    shazam = Shazam()
    identified: List[Tuple[str, str]] = []

    sample_points = list(range(0, total_ms, INTERVAL_MS))
    print(f"[Worker] Duration: {duration_min}m — will probe {len(sample_points)} point(s) at 120s intervals")

    with tempfile.TemporaryDirectory() as tmpdir:
        for i, start_ms in enumerate(sample_points):
            end_ms = min(start_ms + SAMPLE_CHUNK_MS, total_ms)
            chunk_path = os.path.join(tmpdir, f"probe_{i}.mp3")
            audio[start_ms:end_ms].export(chunk_path, format="mp3")

            print(f"[Worker] Probe {i + 1}/{len(sample_points)} at {start_ms // 1000}s ...")
            try:
                result = await shazam.recognize(chunk_path)
                track = result.get("track", {})
                title = track.get("title", "")
                artist = track.get("subtitle", "")
                if title:
                    identified.append((title, artist))
                    unique = set(identified)
                    print(f"[Worker]   ✓ Recognized: {artist} - {title}  ({len(unique)} distinct so far)")
                    if len(unique) >= ALBUM_THRESHOLD:
                        print(f"[Worker]   → Album threshold reached, stopping probes early")
                        return len(unique), list(unique)
                else:
                    print(f"[Worker]   ✗ Not recognized")
            except Exception as e:
                print(f"[Worker]   ✗ Probe error: {e}")

    unique = set(identified)
    print(f"[Worker] Probing complete — {len(unique)} distinct song(s) identified")
    return len(unique), list(unique)


async def _get_tracklist(youtube_url: str) -> List[Dict]:
    """Try video description first, then fall back to comments — both via Claude."""
    youtube_service = YoutubeCommentsService()
    detector = TracklistDetector()

    # 1. Description (via Claude)
    print(f"[Worker] Fetching video description ...")
    try:
        description = await youtube_service.get_description(youtube_url)
        if description:
            print(f"[Worker] Description ({len(description)} chars):\n{description[:1000]}{'...' if len(description) > 1000 else ''}")
            print(f"[Worker] Sending description to Claude ...")
            result = await detector.detect_from_description(description)
            if result:
                print(f"[Worker]   ✓ Found {len(result['tracks'])} timestamps in description")
                return [t.dict() for t in result["tracks"]]
            else:
                print(f"[Worker]   ✗ Claude found no tracklist in description")
        else:
            print(f"[Worker]   ✗ Description is empty")
    except Exception as e:
        print(f"[Worker]   ✗ Description fetch failed: {e}")

    # 2. Comments + Claude
    print(f"[Worker] Checking YouTube comments for tracklist (via Claude) ...")
    try:
        comments = await youtube_service.get_comments(youtube_url, max_results=100)
        print(f"[Worker]   Fetched {len(comments)} comments, sending to Claude ...")
        if comments:
            result = await detector.detect_from_batch(comments)
            if result and result.get("tracks"):
                print(f"[Worker]   ✓ Found {len(result['tracks'])} tracks via Claude")
                return [t.dict() for t in result["tracks"]]
            else:
                print(f"[Worker]   ✗ Claude found no tracklist in comments")
        else:
            print(f"[Worker]   ✗ No comments available")
    except Exception as e:
        print(f"[Worker]   ✗ Comments fetch failed: {e}")

    return []


async def _split_by_tracklist(file_path: str, tracks: List[Dict], video_title: str) -> Tuple[str, int]:
    import subprocess
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK, ID3NoHeaderError

    audio_info = MP3(file_path)
    total_s = audio_info.info.length

    base_name = os.path.splitext(os.path.basename(file_path))[0]
    album_dir = os.path.join(os.path.dirname(file_path), _safe_name(base_name))
    os.makedirs(album_dir, exist_ok=True)

    tagger = ShazamTagger()
    split_paths = []

    print(f"[Worker] Splitting into {len(tracks)} tracks → {album_dir} (re-encoded for precise cuts)")

    for i, track in enumerate(tracks, 1):
        start_s = int(track["seconds"])
        end_s = int(tracks[i]["seconds"]) if i < len(tracks) else int(total_s)
        duration_s = end_s - start_s

        track_title = _safe_name(track["title"])
        out_path = os.path.join(album_dir, f"{i:02d}_{track_title}.mp3")

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_s),
            "-i", file_path,
            "-t", str(duration_s),
            "-c:a", "libmp3lame", "-q:a", "0",
            out_path,
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0:
            print(f"[Worker]   Saved: {i:02d}_{track_title}.mp3  ({duration_s}s)")
            split_paths.append((i, out_path, track["title"]))
        else:
            print(f"[Worker]   ✗ Failed: {i:02d}_{track_title}.mp3 — {result.stderr.decode()[:200]}")

    # Identify all tracks with Shazam first, collect results
    print(f"[Worker] Identifying {len(split_paths)} tracks with Shazam ...")
    shazam_results = []
    for i, out_path, tracklist_title in split_paths:
        print(f"[Worker]   Track {i}: {tracklist_title} ...")
        try:
            shazam_result = await tagger.identify_and_tag(out_path)
            shazam_results.append((i, out_path, tracklist_title, shazam_result))
            print(f"[Worker]     → {shazam_result.artist or '?'} - {shazam_result.title or '?'} [{shazam_result.album or '?'}]")
        except Exception as e:
            print(f"[Worker]     ✗ Shazam failed: {e}")
            shazam_results.append((i, out_path, tracklist_title, None))

    # Always use video title as album — keeps all tracks from the same video grouped together
    final_album = video_title
    print(f"[Worker] Album: '{final_album}' (video title — keeps all tracks together)")

    # Write ID3 tags and rename files
    print(f"[Worker] Writing tags ...")
    for i, out_path, tracklist_title, shazam_result in shazam_results:
        final_title = (shazam_result.title if shazam_result else None) or tracklist_title
        final_artist = (shazam_result.artist if shazam_result else None) or ""

        try:
            try:
                tags = ID3(out_path)
            except ID3NoHeaderError:
                tags = ID3()
            tags["TIT2"] = TIT2(encoding=3, text=final_title)
            if final_artist:
                tags["TPE1"] = TPE1(encoding=3, text=final_artist)
            tags["TALB"] = TALB(encoding=3, text=final_album)
            tags["TRCK"] = TRCK(encoding=3, text=str(i))
            tags.save(out_path)
            print(f"[Worker]   {i:02d} tagged: {final_artist} - {final_title} [{final_album}]")
        except Exception as e:
            print(f"[Worker]   ✗ Tag write failed for track {i}: {e}")

        if shazam_result and shazam_result.title and shazam_result.title != tracklist_title:
            new_name = _safe_name(f"{i:02d}_{shazam_result.title}.mp3")
            new_path = os.path.join(album_dir, new_name)
            os.rename(out_path, new_path)
            print(f"[Worker]   Track {i} renamed → {new_name}")

    os.remove(file_path)
    print(f"[Worker] Removed original: {os.path.basename(file_path)}")

    return album_dir, len(split_paths)


async def process_download(filename: str, video_url: str, title: str) -> Optional[Dict]:
    file_path = _resolve_file(filename)

    if not os.path.isfile(file_path):
        print(f"[Worker] File not found: {file_path}")
        return None

    print(f"[Worker] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"[Worker] New job: {filename}")
    print(f"[Worker] URL:     {video_url}")

    unique_count, _ = await _identify_type(file_path)

    outcome: Dict

    if unique_count <= 1:
        # ── Single song ────────────────────────────────────────────────
        print(f"[Worker] → Single song detected")
        print(f"[Worker] Identifying with Shazam ...")
        tagger = ShazamTagger()
        result = await tagger.identify_and_tag(file_path)
        print(f"[Worker]   Artist : {result.artist or '(unknown)'}")
        print(f"[Worker]   Title  : {result.title or '(unknown)'}")
        print(f"[Worker]   Album  : {result.album or '(unknown)'}")

        if result.artist and result.title:
            new_name = _safe_name(f"{result.artist} - {result.title}.mp3")
        elif result.title:
            new_name = _safe_name(f"{result.title}.mp3")
        else:
            new_name = None

        final_path = file_path
        recognized = bool(new_name)
        if new_name and new_name != os.path.basename(file_path):
            new_path = os.path.join(os.path.dirname(file_path), new_name)
            os.rename(file_path, new_path)
            final_path = new_path
            print(f"[Worker]   Renamed → {new_name}")
        else:
            print(f"[Worker]   Skipped rename (could not identify title)")

        outcome = {
            "kind": "single",
            "status": "recognized" if recognized else "unrecognized",
            "original_filename": filename,
            "final_filename": os.path.basename(final_path),
            "final_path": final_path,
            "final_dir": os.path.dirname(final_path),
            "artist": result.artist or "",
            "title": result.title or "",
            "album": result.album or "",
        }

    else:
        # ── Album ──────────────────────────────────────────────────────
        print(f"[Worker] → Album detected ({unique_count} distinct songs)")

        youtube_url = _read_youtube_url(file_path) or video_url
        if not youtube_url:
            print(f"[Worker] No YouTube URL available — cannot look up timestamps. Skipping split.")
            return {
                "kind": "album",
                "status": "no_split",
                "original_filename": filename,
                "final_filename": os.path.basename(file_path),
                "final_path": file_path,
                "final_dir": os.path.dirname(file_path),
                "track_count": unique_count,
            }

        tracklist = await _get_tracklist(youtube_url)

        if tracklist:
            album_dir, track_count = await _split_by_tracklist(file_path, tracklist, title)
            outcome = {
                "kind": "album",
                "status": "split",
                "original_filename": filename,
                "album_dir": album_dir,
                "final_dir": album_dir,
                "track_count": track_count,
            }
        else:
            print(f"[Worker] Could not find timestamps in description or comments — skipping split.")
            outcome = {
                "kind": "album",
                "status": "no_split",
                "original_filename": filename,
                "final_filename": os.path.basename(file_path),
                "final_path": file_path,
                "final_dir": os.path.dirname(file_path),
                "track_count": unique_count,
            }

    print(f"[Worker] Done: {filename}")
    print(f"[Worker] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return outcome


def _build_notify_message(outcome: Dict) -> str:
    """Human-readable Telegram summary of what musid recognized + where it saved it."""
    if outcome["kind"] == "single":
        if outcome["status"] == "recognized":
            artist, title = outcome.get("artist"), outcome.get("title")
            name = f"{artist} - {title}" if artist and title else (title or outcome["final_filename"])
            return (
                f"✅ Recognized: {name}\n"
                f"Saved as: {outcome['final_filename']}\n"
                f"📁 {outcome['final_dir']}"
            )
        return (
            f"⚠️ Downloaded but Shazam couldn't identify it.\n"
            f"Saved as: {outcome['final_filename']}\n"
            f"📁 {outcome['final_dir']}"
        )
    # album
    if outcome["status"] == "split":
        return (
            f"✅ Recognized as a set — split into {outcome['track_count']} track(s).\n"
            f"📁 {outcome['final_dir']}"
        )
    return (
        f"⚠️ Multiple songs detected but no tracklist found — kept as one file.\n"
        f"Saved as: {outcome['final_filename']}\n"
        f"📁 {outcome['final_dir']}"
    )


async def _notify_telegram(chat_id, outcome: Dict) -> None:
    """Notify the originating Telegram chat that recognition/tagging is done."""
    token = config.get("telegram_bot_token", "")
    if not token or chat_id in (None, ""):
        if not token:
            print(f"[Notify] TELEGRAM_BOT_TOKEN not set — skipping Telegram notify")
        return
    text = _build_notify_message(outcome)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json={"chat_id": chat_id, "text": text})
        if resp.status_code == 200:
            print(f"[Notify] Telegram notified chat {chat_id}")
        else:
            print(f"[Notify] Telegram sendMessage failed {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[Notify] Telegram send error: {e}")


async def run_worker(redis_url: str) -> None:
    import redis.asyncio as aioredis

    print(f"[Worker] Connecting to Redis at {redis_url.split('@')[-1]} ...")
    client = aioredis.from_url(redis_url, decode_responses=True)

    print(f"[Worker] Listening on musid:queue")
    while True:
        try:
            result = await client.blpop("musid:queue", timeout=0)
            if not result:
                continue

            _, data = result
            job = json.loads(data)
            filename = job.get("filename", "")
            video_url = job.get("videoUrl", "")
            title = job.get("title", "")
            chat_id = job.get("chatId")

            if not filename:
                print(f"[Worker] Invalid job (no filename): {data}")
                continue

            try:
                outcome = await process_download(filename, video_url, title)
                if chat_id and outcome:
                    await _notify_telegram(chat_id, outcome)
            except Exception as e:
                print(f"[Worker] Error processing {filename}: {e}")

        except asyncio.CancelledError:
            print("[Worker] Shutting down")
            await client.aclose()
            return
        except Exception as e:
            print(f"[Worker] Redis error: {e}, retrying in 5s...")
            await asyncio.sleep(5)

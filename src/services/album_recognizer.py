import asyncio
import os
import re
import tempfile
from pydub import AudioSegment
from shazamio import Shazam
from src.types.types import TrackResult


# Shazam calls run concurrently; shazamio hits an unofficial endpoint so we
# keep the fan-out modest to avoid rate-limiting.
SHAZAM_CONCURRENCY = 8

# By default probe every SAMPLE_STEP_SEC with a CHUNK_DURATION window. On a
# 90-minute mix that's ~90 probes instead of ~360 — 4x fewer Shazam calls,
# and the remaining calls run in parallel for another ~SHAZAM_CONCURRENCY×
# speedup. End result: what used to take ~40 min finishes in a few.
SAMPLE_STEP_SEC = 60


class AlbumRecognizer:
    def __init__(self):
        self.shazam = Shazam()

    async def recognize_album(
        self,
        file_path: str,
        chunk_duration: int = 15,
        sample_step: int = SAMPLE_STEP_SEC,
        concurrency: int = SHAZAM_CONCURRENCY,
    ) -> list[TrackResult]:
        if not os.path.isfile(file_path):
            raise ValueError(f"File not found: {file_path}")

        print(f"[Album] Loading: {os.path.basename(file_path)}")
        audio = AudioSegment.from_file(file_path)
        total_ms = len(audio)
        chunk_ms = chunk_duration * 1000
        step_ms = max(sample_step, chunk_duration) * 1000

        probe_starts = list(range(0, total_ms, step_ms))
        print(
            f"[Album] Total {total_ms // 1000}s, {len(probe_starts)} probe(s), "
            f"step={step_ms // 1000}s, window={chunk_ms // 1000}s, concurrency={concurrency}"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            chunk_paths = []
            for i, start_ms in enumerate(probe_starts):
                end_ms = min(start_ms + chunk_ms, total_ms)
                path = os.path.join(tmpdir, f"chunk_{i}.mp3")
                audio[start_ms:end_ms].export(path, format="mp3")
                chunk_paths.append((i, start_ms, end_ms, path))

            sem = asyncio.Semaphore(concurrency)

            async def probe(i, start_ms, end_ms, path):
                async with sem:
                    try:
                        result = await self.shazam.recognize(path)
                        track = result.get("track", {})
                        title = track.get("title") or ""
                        artist = track.get("subtitle") or ""
                        if title and artist:
                            print(f"[Album] {start_ms // 1000}s -> {artist} - {title}")
                            return (title, artist, start_ms, end_ms)
                        print(f"[Album] {start_ms // 1000}s -> not recognized")
                        return (None, None, start_ms, end_ms)
                    except Exception as e:
                        print(f"[Album] {start_ms // 1000}s -> error: {e}")
                        return (None, None, start_ms, end_ms)

            tasks = [probe(*c) for c in chunk_paths]
            raw_results = await asyncio.gather(*tasks)

        # raw_results preserves the order of probe_starts (asyncio.gather guarantee)
        tracks = self._merge(raw_results, total_ms)

        output_dir = os.path.dirname(os.path.abspath(file_path))
        self._export_tracks(audio, tracks, output_dir)

        return tracks

    def _export_tracks(self, audio: AudioSegment, tracks: list[TrackResult], output_dir: str) -> None:
        print(f"[Album] Exporting {len(tracks)} track(s) to {output_dir}")
        for i, track in enumerate(tracks, 1):
            start_ms = int(track.start_time * 1000)
            end_ms = int(track.end_time * 1000)
            filename = self._safe_filename(f"{i:02d} - {track.artist} - {track.title}.mp3")
            out_path = os.path.join(output_dir, filename)
            audio[start_ms:end_ms].export(out_path, format="mp3")
            track.output_file = filename
            print(f"[Album] Saved: {filename}")

    def _safe_filename(self, name: str) -> str:
        return re.sub(r'[<>:"/\\|?*]', "_", name)

    def _merge(self, raw: list, total_ms: int) -> list[TrackResult]:
        # Collapse consecutive probes that resolved to the same (title, artist).
        # Track end is extended to the next recognized probe's start, so
        # sparse sampling still produces clean, contiguous segments.
        tracks: list[TrackResult] = []
        cur_title = cur_artist = None
        cur_start = 0
        confidence = 0

        for title, artist, start_ms, _end_ms in raw:
            if title and (title, artist) == (cur_title, cur_artist):
                confidence += 1
                continue

            if cur_title:
                tracks.append(TrackResult(
                    title=cur_title,
                    artist=cur_artist,
                    start_time=round(cur_start / 1000, 1),
                    end_time=round(start_ms / 1000, 1),
                    confidence=confidence,
                ))

            if title:
                cur_title, cur_artist = title, artist
                cur_start = start_ms
                confidence = 1
            else:
                cur_title = cur_artist = None
                confidence = 0

        if cur_title:
            tracks.append(TrackResult(
                title=cur_title,
                artist=cur_artist,
                start_time=round(cur_start / 1000, 1),
                end_time=round(total_ms / 1000, 1),
                confidence=confidence,
            ))

        return tracks

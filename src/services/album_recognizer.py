import os
import re
import tempfile
from pydub import AudioSegment
from shazamio import Shazam
from src.types.types import TrackResult


class AlbumRecognizer:
    def __init__(self):
        self.shazam = Shazam()

    async def recognize_album(self, file_path: str, chunk_duration: int = 15) -> list[TrackResult]:
        if not os.path.isfile(file_path):
            raise ValueError(f"File not found: {file_path}")

        print(f"[Album] Loading: {os.path.basename(file_path)}")
        audio = AudioSegment.from_file(file_path)
        total_ms = len(audio)
        chunk_ms = chunk_duration * 1000

        raw_results = []

        with tempfile.TemporaryDirectory() as tmpdir:
            for i, start_ms in enumerate(range(0, total_ms, chunk_ms)):
                end_ms = min(start_ms + chunk_ms, total_ms)
                chunk_path = os.path.join(tmpdir, f"chunk_{i}.mp3")
                audio[start_ms:end_ms].export(chunk_path, format="mp3")

                print(f"[Album] Chunk {i} ({start_ms // 1000}s – {end_ms // 1000}s) ...")
                try:
                    result = await self.shazam.recognize(chunk_path)
                    track = result.get("track", {})
                    title = track.get("title") or ""
                    artist = track.get("subtitle") or ""
                    if title and artist:
                        print(f"[Album]   -> {artist} - {title}")
                        raw_results.append((title, artist, start_ms, end_ms))
                    else:
                        print(f"[Album]   -> not recognized")
                        raw_results.append((None, None, start_ms, end_ms))
                except Exception as e:
                    print(f"[Album]   -> error: {e}")
                    raw_results.append((None, None, start_ms, end_ms))

        tracks = self._deduplicate(raw_results)

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

    def _deduplicate(self, raw: list) -> list[TrackResult]:
        tracks = []
        if not raw:
            return tracks

        cur_title, cur_artist, cur_start, cur_end = raw[0]
        confidence = 1 if cur_title else 0

        for title, artist, start_ms, end_ms in raw[1:]:
            if title == cur_title and artist == cur_artist:
                cur_end = end_ms
                if title:
                    confidence += 1
            else:
                if cur_title:
                    tracks.append(TrackResult(
                        title=cur_title,
                        artist=cur_artist,
                        start_time=round(cur_start / 1000, 1),
                        end_time=round(cur_end / 1000, 1),
                        confidence=confidence,
                    ))
                cur_title, cur_artist = title, artist
                cur_start, cur_end = start_ms, end_ms
                confidence = 1 if title else 0

        if cur_title:
            tracks.append(TrackResult(
                title=cur_title,
                artist=cur_artist,
                start_time=round(cur_start / 1000, 1),
                end_time=round(cur_end / 1000, 1),
                confidence=confidence,
            ))

        return tracks

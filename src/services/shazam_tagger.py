import os
from shazamio import Shazam
from mutagen.id3 import ID3, TIT2, TPE1, TALB, ID3NoHeaderError
from src.types.types import TagResult


class ShazamTagger:
    def __init__(self):
        self.shazam = Shazam()

    async def identify_and_tag(self, file_path: str) -> TagResult:
        filename = os.path.basename(file_path)
        print(f"[Shazam] Identifying: {filename}")

        result = await self.shazam.recognize(file_path)

        track = result.get("track", {})
        title = track.get("title", "")
        artist = track.get("subtitle", "")

        album = ""
        for section in track.get("sections", []):
            for meta in section.get("metadata", []):
                if meta.get("title", "").lower() == "album":
                    album = meta.get("text", "")
                    break

        self._write_tags(file_path, title, artist, album)

        print(f"[Shazam] Tagged: {filename} -> {artist} - {title} ({album})")

        return TagResult(
            file=filename,
            status="success",
            title=title,
            artist=artist,
            album=album,
        )

    def _write_tags(self, file_path: str, title: str, artist: str, album: str) -> None:
        try:
            tags = ID3(file_path)
        except ID3NoHeaderError:
            tags = ID3()

        if title:
            tags["TIT2"] = TIT2(encoding=3, text=title)
        if artist:
            tags["TPE1"] = TPE1(encoding=3, text=artist)
        if album:
            tags["TALB"] = TALB(encoding=3, text=album)

        tags.save(file_path)

    async def tag_directory(self, directory: str) -> list[TagResult]:
        if not os.path.isdir(directory):
            raise ValueError(f"Directory not found: {directory}")

        mp3_files = [f for f in os.listdir(directory) if f.lower().endswith(".mp3")]

        if not mp3_files:
            raise ValueError(f"No MP3 files found in: {directory}")

        print(f"[Shazam] Found {len(mp3_files)} MP3 file(s) in {directory}")

        results: list[TagResult] = []
        for filename in mp3_files:
            file_path = os.path.join(directory, filename)
            try:
                result = await self.identify_and_tag(file_path)
                results.append(result)
            except Exception as e:
                print(f"[Shazam] Error on {filename}: {e}")
                results.append(TagResult(file=filename, status="error", message=str(e)))

        return results

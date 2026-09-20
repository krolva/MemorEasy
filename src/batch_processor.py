from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from PIL import Image


DATE_FORMAT = "%Y-%m-%d %H:%M:%S UTC"
LOCATION_RE = re.compile(
    r"Latitude, Longitude:\s*(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)"
)


def _load_history(path: Path) -> dict[tuple[str, str], list[dict]]:
    with path.open(encoding="utf-8") as file:
        records = json.load(file)["Saved Media"]

    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for record in records:
        grouped[(record["Date"], record["Media Type"])].append(record)
    return grouped


def _coordinates(records: list[dict]) -> tuple[str, str] | None:
    coordinates = set()
    for record in records:
        match = LOCATION_RE.search(record.get("Location", ""))
        if match:
            coordinates.add(match.groups())
    return next(iter(coordinates)) if len(coordinates) == 1 else None


def _render_image(source: Path, overlay: Path, destination: Path) -> None:
    with Image.open(source) as base_image, Image.open(overlay) as overlay_image:
        base = base_image.convert("RGBA")
        layer = overlay_image.convert("RGBA")
        if layer.size != base.size:
            layer = layer.resize(base.size, Image.Resampling.LANCZOS)
        rendered = Image.alpha_composite(base, layer).convert("RGB")
        rendered.save(destination, "JPEG", quality=95)


def _render_video(
    source: Path, overlay: Path, destination: Path, ffmpeg: str
) -> None:
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-i",
        str(overlay),
        "-filter_complex",
        "[1:v][0:v]scale2ref=w=main_w:h=main_h[ovr][vid];"
        "[vid][ovr]overlay=0:0[outv]",
        "-map",
        "[outv]",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        "-y",
        str(destination),
    ]
    subprocess.run(command, check=True)


def _write_metadata(
    destination: Path,
    captured_at: datetime,
    coordinates: tuple[str, str] | None,
    exiftool: Path,
) -> None:
    value = captured_at.strftime("%Y:%m:%d %H:%M:%S")
    command = ["perl", str(exiftool), "-overwrite_original"]

    if destination.suffix.lower() in {".jpg", ".jpeg"}:
        command.extend(
            [
                f"-EXIF:DateTimeOriginal={value}",
                f"-EXIF:CreateDate={value}",
                f"-EXIF:ModifyDate={value}",
                "-EXIF:OffsetTimeOriginal=+00:00",
                "-EXIF:OffsetTimeDigitized=+00:00",
                "-EXIF:OffsetTime=+00:00",
            ]
        )
    else:
        command.extend(
            [
                f"-QuickTime:CreateDate={value}",
                f"-QuickTime:ModifyDate={value}",
                f"-QuickTime:TrackCreateDate={value}",
                f"-QuickTime:TrackModifyDate={value}",
                f"-QuickTime:MediaCreateDate={value}",
                f"-QuickTime:MediaModifyDate={value}",
                f"-Keys:CreationDate={value}+00:00",
            ]
        )

    if coordinates:
        latitude, longitude = coordinates
        command.extend(
            [
                f"-GPSLatitude={abs(float(latitude))}",
                f"-GPSLatitudeRef={'N' if float(latitude) >= 0 else 'S'}",
                f"-GPSLongitude={abs(float(longitude))}",
                f"-GPSLongitudeRef={'E' if float(longitude) >= 0 else 'W'}",
                f"-Keys:GPSCoordinates={latitude} {longitude}",
            ]
        )

    command.append(str(destination))
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    timestamp = captured_at.timestamp()
    os.utime(destination, (timestamp, timestamp))


def process_batch(
    memories_dir: Path,
    history_path: Path,
    output_dir: Path,
    exiftool: Path,
    ffmpeg: str,
) -> dict[str, int]:
    history = _load_history(history_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    main_files = sorted(
        (path for path in memories_dir.iterdir() if "-main" in path.stem),
        key=lambda path: (path.stat().st_mtime, path.name),
    )
    totals = {
        "processed": 0,
        "rendered": 0,
        "copied": 0,
        "skipped": 0,
        "overlay_skipped": 0,
        "gps_omitted": 0,
    }

    for index, source in enumerate(main_files, start=1):
        captured_at = datetime.fromtimestamp(source.stat().st_mtime, timezone.utc)
        date_string = captured_at.strftime(DATE_FORMAT)
        media_type = (
            "Video" if source.suffix.lower() in {".mp4", ".mov"} else "Image"
        )
        records = history.get((date_string, media_type), [])
        if not records:
            raise ValueError(f"No history match for {source.name} at {date_string}")

        gps = _coordinates(records)
        if gps is None:
            totals["gps_omitted"] += 1

        output_name = source.name.replace("-main", "")
        destination = output_dir / output_name
        if destination.exists() and destination.stat().st_size:
            totals["skipped"] += 1
            continue

        overlay = source.with_name(
            f"{source.stem.replace('-main', '-overlay')}.png"
        )
        temporary = destination.with_name(
            f".{destination.stem}.part{destination.suffix}"
        )
        temporary.unlink(missing_ok=True)

        print(f"[{index}/{len(main_files)}] {output_name}", flush=True)
        overlay_is_png = (
            overlay.exists()
            and overlay.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        )
        if overlay_is_png and source.suffix.lower() in {".jpg", ".jpeg"}:
            _render_image(source, overlay, temporary)
            totals["rendered"] += 1
        elif overlay_is_png and source.suffix.lower() in {".mp4", ".mov"}:
            _render_video(source, overlay, temporary, ffmpeg)
            totals["rendered"] += 1
        else:
            shutil.copy2(source, temporary)
            totals["copied"] += 1
            if overlay.exists() and not overlay_is_png:
                totals["overlay_skipped"] += 1

        temporary.replace(destination)
        _write_metadata(destination, captured_at, gps, exiftool)
        totals["processed"] += 1

    return totals

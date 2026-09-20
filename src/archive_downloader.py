"""Download Snapchat export archives safely and resumably."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import zipfile

from .exceptions import DownloadError


USER_AGENT = "MemorEasy/1.0 (+https://github.com/bransoned/MemorEasy)"


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    downloaded: bool


def probe_archive(url: str, *, timeout: int = 30) -> bool:
    """Confirm a signed URL is reachable and begins with a ZIP signature."""
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Range": "bytes=0-3",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            signature = response.read(4)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise DownloadError(
            "Export link could not be accessed. It may have expired: "
            f"{exc}"
        ) from exc

    if signature != b"PK\x03\x04":
        raise DownloadError(
            "Export link did not return a ZIP file. It may have expired or "
            "redirected to a login page."
        )
    return True


def probe_archives(urls: Iterable[str], *, timeout: int = 30) -> int:
    """Validate all signed URLs without downloading their archive bodies."""
    validated = validate_urls(urls)
    for index, url in enumerate(validated, start=1):
        print(f"Checking export {index}/{len(validated)}...")
        probe_archive(url, timeout=timeout)
    return len(validated)


def read_url_file(path: Path) -> list[str]:
    """Read one HTTPS export URL per line, ignoring blanks and comments."""
    urls = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def validate_urls(urls: Iterable[str]) -> list[str]:
    """Validate and de-duplicate URLs without logging their signed tokens."""
    unique = []
    seen = set()
    for url in urls:
        value = url.strip()
        if not value:
            continue
        if not value.startswith("https://"):
            raise DownloadError("Export links must use HTTPS.")
        if value not in seen:
            seen.add(value)
            unique.append(value)
    if not unique:
        raise DownloadError("No export links were supplied.")
    return unique


def download_archive(
    url: str,
    destination: Path,
    *,
    timeout: int = 60,
    retries: int = 3,
    chunk_size: int = 1024 * 1024,
) -> DownloadResult:
    """Download one archive, resuming from a `.part` file when supported."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if zipfile.is_zipfile(destination):
            return DownloadResult(destination, downloaded=False)
        raise DownloadError(f"Existing file is not a ZIP archive: {destination}")

    partial = destination.with_suffix(destination.suffix + ".part")
    last_error = None

    for attempt in range(1, retries + 1):
        offset = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": USER_AGENT}
        if offset:
            headers["Range"] = f"bytes={offset}-"

        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=timeout) as response:
                status = getattr(response, "status", response.getcode())
                resume = offset > 0 and status == 206
                mode = "ab" if resume else "wb"
                with partial.open(mode) as output:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        output.write(chunk)

            if not zipfile.is_zipfile(partial):
                raise DownloadError(
                    "The downloaded response was not a ZIP archive. "
                    "The Snapchat link may have expired or require a new login."
                )
            partial.replace(destination)
            return DownloadResult(destination, downloaded=True)

        except (HTTPError, URLError, TimeoutError, OSError, DownloadError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 4))

    raise DownloadError(
        f"Could not download {destination.name} after {retries} attempts: "
        f"{last_error}"
    )


def download_archives(
    urls: Iterable[str],
    output_dir: Path,
    *,
    timeout: int = 60,
    retries: int = 3,
) -> list[DownloadResult]:
    """Download all export archives to deterministic, collision-safe names."""
    validated = validate_urls(urls)
    results = []
    width = max(3, len(str(len(validated))))

    for index, url in enumerate(validated, start=1):
        destination = output_dir / f"snapchat-export-{index:0{width}d}.zip"
        print(f"Downloading export {index}/{len(validated)}: {destination.name}")
        result = download_archive(
            url,
            destination,
            timeout=timeout,
            retries=retries,
        )
        results.append(result)
        if not result.downloaded:
            print(f"Already downloaded: {destination.name}")

    return results

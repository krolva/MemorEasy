from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from src.archive_downloader import (
    download_archive,
    probe_archive,
    read_url_file,
    validate_urls,
)
from src.exceptions import DownloadError


def make_zip() -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("memories/example-main.jpg", b"photo")
    return buffer.getvalue()


class FakeResponse(BytesIO):
    def __init__(self, body: bytes, status: int = 200):
        super().__init__(body)
        self.status = status

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class ArchiveDownloaderTests(unittest.TestCase):
    @patch("src.archive_downloader.urlopen")
    def test_probe_reads_zip_signature(self, mocked_open):
        mocked_open.return_value = FakeResponse(b"PK\x03\x04extra", status=206)
        self.assertTrue(probe_archive("https://example.com/private-token"))
        request = mocked_open.call_args.args[0]
        self.assertEqual(request.headers["Range"], "bytes=0-3")

    @patch("src.archive_downloader.urlopen")
    def test_probe_rejects_non_zip_response(self, mocked_open):
        mocked_open.return_value = FakeResponse(b"<htm", status=200)
        with self.assertRaises(DownloadError):
            probe_archive("https://example.com/expired")

    def test_url_file_ignores_comments_and_blanks(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "urls.txt"
            path.write_text(
                "# private export links\n\nhttps://example.com/one\n",
                encoding="utf-8",
            )
            self.assertEqual(read_url_file(path), ["https://example.com/one"])

    def test_validate_urls_deduplicates_and_requires_https(self):
        self.assertEqual(
            validate_urls(["https://example.com/a", "https://example.com/a"]),
            ["https://example.com/a"],
        )
        with self.assertRaises(DownloadError):
            validate_urls(["http://example.com/a"])

    @patch("src.archive_downloader.urlopen")
    def test_downloads_and_validates_zip(self, mocked_open):
        mocked_open.return_value = FakeResponse(make_zip())
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "export.zip"
            result = download_archive(
                "https://example.com/private-token", destination, retries=1
            )
            self.assertTrue(result.downloaded)
            self.assertTrue(zipfile.is_zipfile(destination))

    @patch("src.archive_downloader.urlopen")
    def test_resumes_partial_download(self, mocked_open):
        body = make_zip()
        split = len(body) // 2
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "export.zip"
            partial = destination.with_suffix(".zip.part")
            partial.write_bytes(body[:split])
            mocked_open.return_value = FakeResponse(body[split:], status=206)
            download_archive(
                "https://example.com/private-token", destination, retries=1
            )
            request = mocked_open.call_args.args[0]
            self.assertEqual(request.headers["Range"], f"bytes={split}-")
            self.assertEqual(destination.read_bytes(), body)

    @patch("src.archive_downloader.urlopen")
    def test_rejects_non_zip_response(self, mocked_open):
        mocked_open.return_value = FakeResponse(b"login required")
        with TemporaryDirectory() as directory:
            with self.assertRaises(DownloadError):
                download_archive(
                    "https://example.com/expired",
                    Path(directory) / "export.zip",
                    retries=1,
                )


if __name__ == "__main__":
    unittest.main()

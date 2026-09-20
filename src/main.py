import argparse
from pathlib import Path
import traceback
import sys

from .exceptions import InvalidInputFileError, ParseError
from .archive_downloader import download_archives, probe_archives, read_url_file
from .exceptions import DownloadError
# =========================================================================== #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download or process a Snapchat Memories export."
    )
    subparsers = parser.add_subparsers(dest="command")

    download = subparsers.add_parser(
        "download",
        help="Download Snapchat export ZIP files from temporary links.",
    )
    download.add_argument(
        "--url",
        action="append",
        default=[],
        help="A Snapchat export ZIP URL. May be supplied more than once.",
    )
    download.add_argument(
        "--url-file",
        type=Path,
        help="Text file containing one Snapchat export ZIP URL per line.",
    )
    download.add_argument(
        "--output-dir",
        type=Path,
        default=Path("snapchat-exports"),
        help="Directory for downloaded ZIPs (default: snapchat-exports).",
    )
    download.add_argument("--timeout", type=int, default=60)
    download.add_argument("--retries", type=int, default=3)
    download.add_argument(
        "--check-only",
        action="store_true",
        help="Validate each URL with a four-byte request; download nothing.",
    )
    return parser


def run_download(args: argparse.Namespace) -> None:
    urls = list(args.url)
    if args.url_file:
        urls.extend(read_url_file(args.url_file))
    if args.check_only:
        checked = probe_archives(urls, timeout=args.timeout)
        print(f"\nAll {checked} export link(s) are valid ZIP downloads.")
        return
    results = download_archives(
        urls,
        args.output_dir,
        timeout=args.timeout,
        retries=args.retries,
    )
    downloaded = sum(result.downloaded for result in results)
    print(
        f"\nReady: {len(results)} archive(s) in {args.output_dir} "
        f"({downloaded} downloaded, {len(results) - downloaded} reused)."
    )


def main(argv=None):

    args = build_parser().parse_args(argv)

    print(r"""
███╗   ███╗███████╗███╗   ███╗ ██████╗ ██████╗ ███████╗ █████╗ ███████╗██╗   ██╗
████╗ ████║██╔════╝████╗ ████║██╔═══██╗██╔══██╗██╔════╝██╔══██╗██╔════╝╚██╗ ██╔╝
██╔████╔██║█████╗  ██╔████╔██║██║   ██║██████╔╝█████╗  ███████║███████╗ ╚████╔╝
██║╚██╔╝██║██╔══╝  ██║╚██╔╝██║██║   ██║██╔══██╗██╔══╝  ██╔══██║╚════██║  ╚██╔╝
██║ ╚═╝ ██║███████╗██║ ╚═╝ ██║╚██████╔╝██║  ██║███████╗██║  ██║███████║   ██║
╚═╝     ╚═╝╚══════╝╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚══════╝   ╚═╝
    """)

    try:
        if args.command == "download":
            run_download(args)
            return

        # Processing dependencies are deliberately loaded only for this mode,
        # so downloading export ZIPs works before optional media tools are set up.
        from .parsers import parse_html, parse_snapchat_memories
        from .memory_handling import scan_memories

        html_text = parse_html()
        memories = parse_snapchat_memories(html_text)
        scan_memories(memories)
        input("\nPress Enter to exit...")

    except InvalidInputFileError as e:
        print(f"\nInvalid file: {e}")
        input("\nPress Enter to exit...")
        sys.exit(1)
    except ParseError as e:
        print(f"\nParse error: {e}")
        input("\nPress Enter to exit...")
        sys.exit(1)
    except DownloadError as e:
        print(f"\nDownload error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nDownload cancelled by user")
        sys.exit(130)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        traceback.print_exc()
        input("\nPress Enter to exit...")
        sys.exit(1)

# =========================================================================== #

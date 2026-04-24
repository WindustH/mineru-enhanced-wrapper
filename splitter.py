"""PDF splitting using pdftk."""

import shutil
import subprocess
import tempfile
from pathlib import Path

import log


def get_page_count(pdf_path: Path) -> int:
    """Return the number of pages in a PDF."""
    result = subprocess.run(
        ["qpdf", "--show-npages", str(pdf_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"qpdf failed: {result.stderr.strip()}")
    return int(result.stdout.strip())


def _expected_chunk_count(total_pages: int, chunk_size: int) -> int:
    return max(1, (total_pages + chunk_size - 1) // chunk_size)


def split_pdf(
    pdf_path: Path,
    chunk_size: int,
    output_dir: Path | None = None,
    cache_dir: Path | None = None,
) -> list[Path]:
    """Split a PDF into chunks of at most `chunk_size` pages.

    If cache_dir is given, checks for existing cached splits and skips
    splitting if the expected number of chunks already exists.

    Returns a list of paths to the split PDF files.
    """
    target_dir = cache_dir or output_dir
    if target_dir is None:
        target_dir = Path(tempfile.mkdtemp(prefix="mineru-split-"))

    target_dir.mkdir(parents=True, exist_ok=True)
    total_pages = get_page_count(pdf_path)
    expected = _expected_chunk_count(total_pages, chunk_size)

    # Check cache: do the expected chunks already exist?
    if cache_dir is not None:
        existing = sorted(cache_dir.glob(f"{pdf_path.stem}_part*.pdf"))
        if len(existing) == expected:
            log.detail(f"Using {expected} cached split(s) for {pdf_path.name}")
            return existing

    if total_pages <= chunk_size:
        # No splitting needed, just copy to target dir
        dest = target_dir / f"{pdf_path.stem}.pdf"
        if not dest.exists():
            shutil.copy2(pdf_path, dest)
        return [dest]

    chunks: list[Path] = []
    for start in range(0, total_pages, chunk_size):
        end = min(start + chunk_size, total_pages)
        chunk_idx = start // chunk_size + 1
        chunk_name = f"{pdf_path.stem}_part{chunk_idx:03d}.pdf"
        chunk_path = target_dir / chunk_name

        if not chunk_path.exists():
            subprocess.run(
                [
                    "pdftk", str(pdf_path),
                    "cat", f"{start + 1}-{end}",
                    "output", str(chunk_path),
                ],
                check=True,
            )

        chunks.append(chunk_path)

    return chunks

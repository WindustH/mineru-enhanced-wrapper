#!/usr/bin/env python3
"""mineru-enhanced — Process large PDFs with MinerU by splitting into chunks.

Usage:
    python main.py <input.pdf|input_dir> <output_dir> [wrapper_opts] [mineru args...]

Examples:
    python main.py book.pdf ./output
    python main.py ./pdfs ./output
    python main.py book.pdf ./output "chunk-size:30" -l en -b pipeline
"""

import sys
from dataclasses import dataclass
from pathlib import Path

import log
from processor import process_chunks_dir
from refactor import merge_outputs
from splitter import get_page_count, split_pdf

DEFAULT_CHUNK_SIZE = 50

_VALID_OPTS = {"chunk-size"}


@dataclass
class Opts:
    chunk_size: int = DEFAULT_CHUNK_SIZE


def parse_wrapper_opts(raw: str) -> Opts:
    """Parse a semicolon-separated options string like 'chunk-size:30'."""
    opts = Opts()
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            key, value = part.split(":", 1)
            key, value = key.strip(), value.strip()
        else:
            key, value = part.strip(), True

        if key not in _VALID_OPTS:
            log.warn(f"unknown wrapper option '{key}'")
            continue

        match key:
            case "chunk-size":
                opts.chunk_size = int(value)

    return opts


def parse_args(argv: list[str] | None = None) -> tuple[Path, Path, Opts, list[str]]:
    """Parse: input output [wrapper_opts_string] [mineru_passthrough_args...]"""
    args = argv or sys.argv[1:]
    if len(args) < 2:
        print("Usage: main.py <input> <output> [\"opts\"] [mineru args...]", file=sys.stderr)
        sys.exit(1)

    input_path = Path(args[0]).resolve()
    output_path = Path(args[1]).resolve()
    rest = args[2:]

    # Third arg is wrapper opts only if it doesn't start with '-'
    if rest and not rest[0].startswith("-"):
        opts = parse_wrapper_opts(rest[0])
        mineru_extra = rest[1:]
    else:
        opts = Opts()
        mineru_extra = rest

    return input_path, output_path, opts, mineru_extra


def collect_pdfs(input_path: Path) -> list[Path]:
    """Collect PDF files from a path. Accepts a single file or a directory (non-recursive)."""
    if input_path.is_file():
        if input_path.suffix.lower() != ".pdf":
            log.error(f"input must be a PDF file, got: {input_path.suffix}")
            sys.exit(1)
        return [input_path]

    if input_path.is_dir():
        pdfs = sorted(p for p in input_path.iterdir() if p.suffix.lower() == ".pdf")
        if not pdfs:
            log.error(f"no PDF files found in {input_path}")
            sys.exit(1)
        return pdfs

    log.error(f"input not found: {input_path}")
    sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    input_path, output_dir, opts, mineru_extra = parse_args(argv)

    pdfs = collect_pdfs(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    cache_dir = output_dir / "_cache"
    splits_dir = cache_dir / "splits"
    mineru_cache = cache_dir / "mineru_output"

    # Phase 1: Split all PDFs (cached)
    log.header("Splitting")
    if len(pdfs) > 1:
        log.banner(f"Found {len(pdfs)} PDFs")

    pdf_to_chunks: dict[str, list[Path]] = {}
    for pdf in pdfs:
        total_pages = get_page_count(pdf)
        chunk_count = max(1, (total_pages + opts.chunk_size - 1) // opts.chunk_size)
        log.kv("PDF", pdf.name)
        log.kv("Pages", str(total_pages))
        log.info(f"{'>' if total_pages > opts.chunk_size else 'Within'} chunk size → {chunk_count} chunk(s)")

        chunks = split_pdf(pdf, opts.chunk_size, cache_dir=splits_dir)
        pdf_to_chunks[pdf.stem] = chunks

    total_chunks = sum(len(v) for v in pdf_to_chunks.values())
    log.info(f"Total: {total_chunks} chunk(s) from {len(pdfs)} PDF(s)")

    # Phase 2: Process all chunks in one MinerU call (cached)
    log.header("Processing with MinerU")
    all_outputs = process_chunks_dir(splits_dir, mineru_cache, extra_args=mineru_extra)

    # Phase 3: Merge per-PDF outputs
    log.header("Merging outputs")
    output_map = {d.name: d for d in all_outputs}

    for pdf in pdfs:
        chunk_outputs = [
            output_map[p.stem]
            for p in pdf_to_chunks[pdf.stem]
            if p.stem in output_map
        ]
        if chunk_outputs:
            merge_outputs(chunk_outputs, output_dir, merge_name=pdf.stem)

    log.success(f"Output written to: {output_dir}")
    print("Done.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""mineru-enhanced — Process large PDFs with MinerU by splitting into chunks.

Usage:
    python main.py <input.pdf|input_dir> <output_dir> [wrapper_opts] [mineru args...]
    python main.py img2md <input.md> <output.md> [--threads N]

Examples:
    python main.py book.pdf ./output
    python main.py ./pdfs ./output
    python main.py book.pdf ./output "chunk-size:30" -l en -b pipeline
    python main.py book.pdf ./output "text-only"                 # auto-generate text-only md
    python main.py book.pdf ./output "text-only:(threads:4)"     # custom threads
    python main.py img2md output/book.md output/book_final.md --threads 8
"""

import argparse
import hashlib
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import log
from processor import process_chunks_dir
from refactor import merge_outputs
from splitter import get_page_count, split_pdf

_IMG_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
_IMG_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp",
    ".svg", ".webp", ".tiff", ".ico",
}

DEFAULT_CHUNK_SIZE = 50

_VALID_OPTS = {"chunk-size", "text-only"}


@dataclass
class Opts:
    chunk_size: int = DEFAULT_CHUNK_SIZE
    text_only: bool = False
    text_only_threads: int = 8


def parse_wrapper_opts(raw: str) -> Opts:
    """Parse a semicolon-separated options string like 'chunk-size:30' or 'text-only:(threads:4)'."""
    opts = Opts()
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue

        # Handle text-only:(key:value) syntax
        if part.startswith("text-only:(") and part.endswith(")"):
            opts.text_only = True
            inner = part[11:-1]  # Remove "text-only:(" and ")"
            for sub_part in inner.split(","):
                if ":" in sub_part:
                    sub_key, sub_value = sub_part.split(":", 1)
                    sub_key, sub_value = sub_key.strip(), sub_value.strip()
                    if sub_key == "threads":
                        opts.text_only_threads = int(sub_value)
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
            case "text-only":
                opts.text_only = True

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


def _process_image(img_path: Path) -> str | None:
    """Run img2md on a single image, return description or None on failure."""
    result = subprocess.run(
        ["img2md", str(img_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def cmd_img2md(input_path: Path, output_path: Path, threads: int = 8) -> None:
    """Replace image references in a markdown file with img2md descriptions.

    Resumes from a partially-converted output file if it exists, so an
    interrupted run only re-processes images that weren't finished yet.
    """
    if not input_path.is_file():
        log.error(f"file not found: {input_path}")
        sys.exit(1)

    md_dir = input_path.resolve().parent

    # Resume from partial output if it exists, otherwise start from input
    if output_path.is_file():
        log.info(f"Resuming from partial output: {output_path.name}")
        content = output_path.read_text(encoding="utf-8")
    else:
        content = input_path.read_text(encoding="utf-8")

    matches = [
        m for m in _IMG_PATTERN.finditer(content)
        if Path(m.group(2)).suffix.lower() in _IMG_EXTENSIONS
        and not m.group(2).startswith(("http://", "https://"))
    ]

    if not matches:
        log.info("no local images found")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        return

    # Prepare image paths with their match indices
    img_tasks: list[tuple[int, re.Match[str], Path]] = []
    for i, match in enumerate(matches):
        img_path = (md_dir / match.group(2)).resolve()
        if not img_path.exists():
            log.warn(f"[{i+1}/{len(matches)}] skip (not found): {img_path}")
            continue
        img_tasks.append((i, match, img_path))

    if not img_tasks:
        log.info("no valid images to process")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        return

    log.info(f"processing {len(img_tasks)} image(s) with {threads} thread(s)")

    # Process images in parallel
    replacements: list[tuple[int, int, str]] = []
    completed = 0

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {
            executor.submit(_process_image, img_path): (idx, match)
            for idx, match, img_path in img_tasks
        }

        for future in as_completed(futures):
            idx, match = futures[future]
            completed += 1
            img_path = img_tasks[idx][2]

            try:
                desc = future.result()
                if desc is None:
                    log.warn(f"[{completed}/{len(img_tasks)}] failed: {img_path.name}")
                    continue

                log.info(f"[{completed}/{len(img_tasks)}] {img_path.name}")
                replacements.append((match.start(), match.end(), desc))
            except Exception as e:
                log.warn(f"[{completed}/{len(img_tasks)}] error: {img_path.name} - {e}")

    for start, end, replacement in sorted(replacements, reverse=True):
        content = content[:start] + replacement + content[end:]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Write to temp file then rename to avoid corrupting output on interrupt
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(output_path)
    log.success(f"written to {output_path}")


def main(argv: list[str] | None = None) -> None:
    args = argv or sys.argv[1:]

    if args and args[0] == "img2md":
        parser = argparse.ArgumentParser(prog="main.py img2md")
        parser.add_argument("input", help="input markdown file")
        parser.add_argument("output", help="output markdown file")
        parser.add_argument("--threads", "-t", type=int, default=8, help="number of threads (default: 8)")
        parsed = parser.parse_args(args[1:])
        cmd_img2md(Path(parsed.input), Path(parsed.output), threads=parsed.threads)
        return

    input_path, output_dir, opts, mineru_extra = parse_args(args)

    pdfs = collect_pdfs(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    cache_dir = (
        Path.home() / ".cache" / "mineru-enhanced"
        / hashlib.sha256(str(input_path.resolve()).encode()).hexdigest()[:16]
    )
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

    # Phase 4: Generate text-only versions if requested
    if opts.text_only:
        log.header("Generating text-only versions")
        md_files = sorted(
            p for p in output_dir.glob("*.md")
            if not p.stem.endswith("_text-only")
        )
        for md_file in md_files:
            pure_text_path = md_file.with_stem(f"{md_file.stem}_text-only")
            log.info(f"{md_file.name} -> {pure_text_path.name}")
            cmd_img2md(md_file, pure_text_path, threads=opts.text_only_threads)
        log.success(f"Pure-text output: {output_dir}")

    print("Done.")


if __name__ == "__main__":
    main()

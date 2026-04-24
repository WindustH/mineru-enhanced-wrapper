"""MinerU processor — runs MinerU on unprocessed chunks in a single batch, with caching."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import log

# MinerU invocation template (mirrors the existing `mineru` wrapper script)
MINERU_PYTHON = "/home/windy/opt/MinerU/.venv/bin/python"
MINERU_CMD_PREFIX = ["uv", "run", "--python", MINERU_PYTHON, "mineru"]

# Flags that the wrapper already handles — must not be passed through
_CONFLICTING_FLAGS = {"-p", "--path", "-o", "--output", "-s", "--start", "-e", "--end"}


def _validate_extra_args(args: list[str]) -> list[str]:
    """Warn and strip conflicting flags from passthrough args."""
    filtered: list[str] = []
    skip_next = False
    for i, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if arg in _CONFLICTING_FLAGS:
            log.warn(f"ignoring conflicting flag '{arg}' (wrapper handles this)")
            if i + 1 < len(args) and not args[i + 1].startswith("-"):
                skip_next = True
            continue
        filtered.append(arg)
    return filtered


def _has_complete_output(chunk_dir: Path) -> bool:
    """Check if a MinerU output directory contains a completed result (.md file)."""
    if not chunk_dir.is_dir():
        return False
    return any(chunk_dir.rglob("*.md"))


def process_chunks_dir(
    chunks_dir: Path,
    cache_dir: Path,
    extra_args: list[str] | None = None,
) -> list[Path]:
    """Run MinerU on unprocessed chunks in a single batch. Results cached in cache_dir.

    Returns list of all output subdirectories (cached + newly processed).
    """
    cache_dir.mkdir(parents=True, exist_ok=True)

    all_chunks = sorted(chunks_dir.glob("*.pdf"))
    if not all_chunks:
        log.warn(f"no PDFs found in {chunks_dir}")
        return []

    # Separate cached (already processed) from unprocessed
    cached: list[Path] = []
    unprocessed: list[Path] = []
    for chunk in all_chunks:
        chunk_output = cache_dir / chunk.stem
        if _has_complete_output(chunk_output):
            cached.append(chunk_output)
        else:
            unprocessed.append(chunk)

    if cached:
        log.info(f"{len(cached)} chunk(s) already cached, skipping")

    if not unprocessed:
        log.info("All chunks already processed")
        return sorted(cached)

    log.info(f"Processing {len(unprocessed)} chunk(s) in a single MinerU batch")

    # Create temp dir with symlinks to only unprocessed chunks
    tmp_dir = Path(tempfile.mkdtemp(prefix="mineru-enhanced-batch-"))
    try:
        link_dir = tmp_dir / "chunks"
        link_dir.mkdir()
        for chunk in unprocessed:
            (link_dir / chunk.name).symlink_to(chunk)

        work_dir = tmp_dir / "mineru_output"
        work_dir.mkdir()

        cmd = MINERU_CMD_PREFIX + [
            "-p", str(link_dir),
            "-o", str(work_dir),
            *(_validate_extra_args(extra_args or [])),
        ]

        log.detail(f"{' '.join(cmd)}")
        result = subprocess.run(cmd, cwd="/home/windy/opt/MinerU")

        if result.returncode != 0:
            log.error(f"MinerU failed (exit {result.returncode})")
            raise RuntimeError(f"MinerU exited with code {result.returncode}")

        # Move output subdirectories into cache
        for chunk_output in sorted(work_dir.iterdir()):
            if chunk_output.is_dir():
                dest = cache_dir / chunk_output.name
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.move(str(chunk_output), str(dest))
                log.detail(f"Cached: {chunk_output.name}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Return all outputs: previously cached + newly processed
    all_outputs = sorted(d for d in cache_dir.iterdir() if d.is_dir())
    log.info(f"Total: {len(all_outputs)} chunk output(s)")
    return all_outputs

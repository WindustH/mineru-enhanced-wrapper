"""MinerU processor — runs MinerU on unprocessed chunks one at a time, with caching."""

import shutil
import subprocess
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
    """Check if a MinerU output directory exists (completed)."""
    return chunk_dir.is_dir()


def process_chunks_dir(
    chunks_dir: Path,
    cache_dir: Path,
    extra_args: list[str] | None = None,
) -> list[Path]:
    """Run MinerU on unprocessed chunks one at a time. Results cached in cache_dir.

    Each chunk is processed individually and cached immediately, so an
    interrupted run only loses the current chunk.

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

    log.info(f"Processing {len(unprocessed)} chunk(s) one at a time")
    extra = _validate_extra_args(extra_args or [])

    work_dir = cache_dir / "batch_work"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)

    for i, chunk in enumerate(unprocessed, 1):
        log.info(f"[{i}/{len(unprocessed)}] {chunk.name}")

        link_dir = work_dir / "chunks"
        link_dir.mkdir(parents=True, exist_ok=True)
        (link_dir / chunk.name).symlink_to(chunk)

        mineru_out = work_dir / "mineru_output"
        mineru_out.mkdir(parents=True, exist_ok=True)

        cmd = MINERU_CMD_PREFIX + [
            "-p", str(link_dir),
            "-o", str(mineru_out),
            *extra,
        ]
        log.detail(f"{' '.join(cmd)}")

        result = subprocess.run(cmd, cwd="/home/windy/opt/MinerU")
        if result.returncode != 0:
            log.error(f"MinerU failed for {chunk.name} (exit {result.returncode})")
            raise RuntimeError(f"MinerU exited with code {result.returncode}")

        # Move output into cache immediately
        for chunk_output in sorted(mineru_out.iterdir()):
            if chunk_output.is_dir():
                dest = cache_dir / chunk_output.name
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.move(str(chunk_output), str(dest))
                log.detail(f"Cached: {chunk_output.name}")

        # Clean up work dir for next chunk
        shutil.rmtree(link_dir, ignore_errors=True)
        shutil.rmtree(mineru_out, ignore_errors=True)

    shutil.rmtree(work_dir, ignore_errors=True)

    all_outputs = sorted(d for d in cache_dir.iterdir() if d.is_dir())
    log.info(f"Total: {len(all_outputs)} chunk output(s)")
    return all_outputs

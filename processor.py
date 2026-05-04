"""MinerU processor — runs MinerU on all unprocessed chunks in one batch, with caching."""

import os
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


def _cache_chunk_outputs(mineru_out: Path, cache_dir: Path) -> int:
    """Move chunk output dirs from work output into cache. Returns count moved."""
    count = 0
    if not mineru_out.is_dir():
        return count
    for chunk_output in sorted(mineru_out.iterdir()):
        if chunk_output.is_dir():
            dest = cache_dir / chunk_output.name
            if dest.exists():
                shutil.rmtree(dest)
            shutil.move(str(chunk_output), str(dest))
            log.detail(f"Cached: {chunk_output.name}")
            count += 1
    return count


def process_chunks_dir(
    chunks_dir: Path,
    cache_dir: Path,
    extra_args: list[str] | None = None,
) -> list[Path]:
    """Run MinerU batch on all unprocessed chunks. Results cached in cache_dir.

    MinerU processes all chunks in one invocation to avoid repeated model
    loading overhead. Outputs are written to a separate work directory and
    moved into cache on completion — whether MinerU finishes, fails, or is
    interrupted (Ctrl+C). On restart, any leftovers in the work directory
    are recovered first, so no completed work is lost.

    Returns list of all output subdirectories (cached + newly processed).
    """
    cache_dir.mkdir(parents=True, exist_ok=True)

    all_chunks = sorted(chunks_dir.glob("*.pdf"))
    if not all_chunks:
        log.warn(f"no PDFs found in {chunks_dir}")
        return []

    # Recover outputs from a previous interrupted run (if any)
    prev_work = cache_dir / "batch_work"
    prev_out = prev_work / "mineru_output"
    if prev_out.is_dir():
        recovered = _cache_chunk_outputs(prev_out, cache_dir)
        if recovered:
            log.info(f"Recovered {recovered} chunk(s) from previous run")
        shutil.rmtree(prev_work, ignore_errors=True)

    cached: list[Path] = []
    unprocessed: list[Path] = []
    for chunk in all_chunks:
        if _has_complete_output(cache_dir / chunk.stem):
            cached.append(cache_dir / chunk.stem)
        else:
            unprocessed.append(chunk)

    if cached:
        log.info(f"{len(cached)} chunk(s) already cached, skipping")

    if not unprocessed:
        log.info("All chunks already processed")
        return sorted(cached)

    log.info(f"Processing {len(unprocessed)} chunk(s) in one batch")
    extra = _validate_extra_args(extra_args or [])

    work_dir = cache_dir / "batch_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    # Symlink all unprocessed chunks into a single input directory
    link_dir = work_dir / "chunks"
    link_dir.mkdir(parents=True, exist_ok=True)
    for chunk in unprocessed:
        (link_dir / chunk.name).symlink_to(chunk)

    mineru_out = work_dir / "mineru_output"
    mineru_out.mkdir(parents=True, exist_ok=True)

    cmd = MINERU_CMD_PREFIX + [
        "-p", str(link_dir),
        "-o", str(mineru_out),
        "--gpu-memory-utilization", "0.5",
        *extra,
    ]
    log.detail(f"{' '.join(cmd)}")

    env = os.environ.copy()
    env.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")

    try:
        result = subprocess.run(cmd, cwd="/home/windy/opt/MinerU", env=env)
    except (KeyboardInterrupt, Exception):
        _cache_chunk_outputs(mineru_out, cache_dir)
        raise

    _cache_chunk_outputs(mineru_out, cache_dir)

    if result.returncode != 0:
        log.warn(f"MinerU exited with code {result.returncode}")
        raise RuntimeError(f"MinerU exited with code {result.returncode}")

    shutil.rmtree(work_dir, ignore_errors=True)

    all_outputs = sorted(d for d in cache_dir.iterdir() if d.is_dir())
    log.info(f"Total: {len(all_outputs)} chunk output(s)")
    return all_outputs

"""Output directory restructuring — adapted from mineru-output-directory-refactor.

Flattens MinerU's nested output (one subdirectory per PDF, each containing
a .md and an images/ folder) into a single output directory with renamed
image paths.
"""

import re
import shutil
from pathlib import Path

import log


def _url_encode_path(path: str) -> str:
    """URL-encode only spaces (%20) in a relative path, preserving slashes."""
    return path.replace(" ", "%20")


def _rewrite_image_paths(content: str, name: str) -> str:
    """Rewrite image references in markdown to point to the new flat layout.

    Handles any MinerU output structure (auto/, vlm/, hybrid_auto/, etc.)
    by matching relative image paths generically.
    """
    pattern = r"!\[([^\]]*)\]\(([^)]+)\)"
    img_extensions = {
        ".png", ".jpg", ".jpeg", ".gif", ".bmp",
        ".svg", ".webp", ".tiff", ".ico",
    }

    replacements: list[tuple[int, int, str]] = []
    for match in re.finditer(pattern, content):
        old_path_with_title = match.group(2)
        parts = old_path_with_title.split(" ", 1)
        old_path = parts[0].strip("\"'")
        title = parts[1] if len(parts) > 1 else ""

        if not any(old_path.lower().endswith(ext) for ext in img_extensions):
            continue
        if "http" in old_path or "www." in old_path:
            continue

        filename = Path(old_path).name
        new_path = f"images/{name}/{filename}"

        alt_text = match.group(1)
        encoded_path = _url_encode_path(new_path)
        replacement = f"![{alt_text}]({encoded_path} {title})" if title else f"![{alt_text}]({encoded_path})"
        replacements.append((match.start(), match.end(), replacement))

    if not replacements:
        return content

    # Apply replacements back-to-front to preserve positions
    chars = list(content)
    for start, end, replacement in sorted(replacements, reverse=True):
        chars[start:end] = replacement
    return "".join(chars)


def refactor_output(input_dir: Path, output_dir: Path) -> list[Path]:
    """Restructure MinerU output. Returns list of md files created."""
    md_files = list(input_dir.rglob("*.md"))
    if not md_files:
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []

    for md_file in md_files:
        rel_path = md_file.relative_to(input_dir)
        if len(rel_path.parts) < 2:
            continue

        name = md_file.stem
        images_dir = md_file.parent / "images"

        # Copy images if they exist
        if images_dir.exists():
            target_images_dir = output_dir / "images" / name
            target_images_dir.mkdir(parents=True, exist_ok=True)

            for item in images_dir.rglob("*"):
                if item.is_file():
                    dest = target_images_dir / item.relative_to(images_dir)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest)

        # Rewrite markdown and write to output (even without images)
        content = md_file.read_text(encoding="utf-8")
        new_content = _rewrite_image_paths(content, name)
        out_path = output_dir / f"{name}.md"
        out_path.write_text(new_content, encoding="utf-8")
        log.detail(f"{name}.md")
        created.append(out_path)

    return created


def merge_outputs(
    chunk_output_dirs: list[Path],
    final_output_dir: Path,
    merge_name: str | None = None,
) -> None:
    """Merge multiple MinerU chunk outputs into a single refactored directory.

    When merge_name is given and multiple chunk md files are produced,
    they are concatenated into a single file named {merge_name}.md.
    """
    all_mds: list[Path] = []
    for chunk_dir in chunk_output_dirs:
        mds = refactor_output(chunk_dir, final_output_dir)
        all_mds.extend(mds)

    log.info(f"Merged {len(all_mds)} file(s)")

    if merge_name and len(all_mds) > 1:
        sorted_mds = sorted(all_mds)
        combined = "\n\n".join(f.read_text(encoding="utf-8") for f in sorted_mds)
        (final_output_dir / f"{merge_name}.md").write_text(combined, encoding="utf-8")
        for f in sorted_mds:
            f.unlink()
        log.detail(f"Concatenated into {merge_name}.md")

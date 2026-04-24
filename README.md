# mineru-enhanced

Process large PDFs with [MinerU](https://github.com/opendatalab/MinerU) by splitting into chunks, then convert images to text.

## Features

- **Chunk-based processing**: Split large PDFs into manageable chunks, process with MinerU, then merge results
- **Image-to-text conversion**: Convert embedded images in markdown files to descriptive text using vision models
- **Multi-threaded processing**: Parallel image conversion for faster results
- **Pure-text output**: Automatically generate markdown files with images replaced by text descriptions

## Installation

```bash
# Install dependencies
pip install loguru

# Install MinerU (follow official guide)
# https://github.com/opendatalab/MinerU

# Install img2md for image-to-text conversion
pip install img2md  # or your preferred installation method
```

## Usage

### PDF Processing

```bash
# Process a single PDF
python main.py book.pdf ./output

# Process all PDFs in a directory
python main.py ./pdfs ./output

# Custom chunk size
python main.py book.pdf ./output "chunk-size:30"

# Pass options to MinerU
python main.py book.pdf ./output -l en -b pipeline

# Auto-generate text-only markdown (images replaced with descriptions)
python main.py book.pdf ./output "text-only"

# Custom threads for image-to-text conversion
python main.py book.pdf ./output "text-only:(threads:4)"
```

### Image-to-Text Conversion

```bash
# Convert images in a markdown file to text
python main.py img2md input.md output.md

# Use multiple threads for faster processing
python main.py img2md input.md output.md --threads 8
python main.py img2md input.md output.md -t 8
```

## Wrapper Options

Options are passed as a semicolon-separated string:

| Option | Description | Default |
|--------|-------------|---------|
| `chunk-size:N` | Number of pages per chunk | 50 |
| `text-only` | Generate text-only markdown | false |
| `text-only:(threads:N)` | Threads for image conversion (default: 8) | 8 |

## Output Structure

```
output/
├── book.md              # Original markdown with images
├── book_text-only.md    # Images replaced with text descriptions (if text-only enabled)
└── images/
    └── book/
        ├── page_1.png
        └── ...
```

## Architecture

```
mineru-enhanced/
├── main.py       # CLI entry point and orchestration
├── splitter.py   # PDF chunk splitting
├── processor.py  # MinerU batch processing
├── refactor.py   # Output restructuring and merging
└── log.py        # Logging utilities
```

## License

MIT

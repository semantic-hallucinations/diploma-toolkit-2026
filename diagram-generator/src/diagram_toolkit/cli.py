from __future__ import annotations

import argparse
from pathlib import Path

from .layouts import canvas_from_model
from .parsers import parse_source
from .rendering import save_drawio, save_png
from .validation import has_errors, summarize_diagnostics, validate_canvas


SOURCE_SUFFIXES = {".mmd", ".puml", ".json"}


def source_files(path: Path) -> list[Path]:
    if path.is_dir():
        return [source for source in sorted(path.iterdir()) if source.suffix.lower() in SOURCE_SUFFIXES]
    return [path]


def render_file(source: Path, out_dir: Path) -> tuple[Path, Path]:
    model = parse_source(source)
    canvas = canvas_from_model(model)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = source.stem
    drawio_path = out_dir / f"{stem}.drawio"
    png_path = out_dir / f"{stem}.png"
    save_drawio(canvas, drawio_path)
    save_png(canvas, png_path)
    return drawio_path, png_path


def render_examples(source_dir: Path, out_dir: Path) -> list[tuple[Path, Path]]:
    outputs = []
    for source in source_files(source_dir):
        outputs.append(render_file(source, out_dir))
    return outputs


def validate_sources(path: Path) -> dict[Path, str]:
    results: dict[Path, str] = {}
    for source in source_files(path):
        model = parse_source(source)
        canvas = canvas_from_model(model)
        diagnostics = validate_canvas(canvas)
        results[source] = summarize_diagnostics(diagnostics)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate draw.io and PNG diagrams for diploma documentation.")
    sub = parser.add_subparsers(dest="command", required=True)
    render = sub.add_parser("render", help="Render one source file.")
    render.add_argument("source", type=Path)
    render.add_argument("--out", type=Path, default=Path("diagram-generator/examples/generated"))
    examples = sub.add_parser("examples", help="Render all bundled example sources.")
    examples.add_argument("--source-dir", type=Path, default=Path("diagram-generator/examples/sources"))
    examples.add_argument("--out", type=Path, default=Path("diagram-generator/examples/generated"))
    validate = sub.add_parser("validate", help="Validate one source file or a directory of source files.")
    validate.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.command == "render":
        drawio_path, png_path = render_file(args.source, args.out)
        print(f"drawio: {drawio_path}")
        print(f"png: {png_path}")
    elif args.command == "examples":
        for drawio_path, png_path in render_examples(args.source_dir, args.out):
            print(f"{drawio_path} -> {png_path}")
    elif args.command == "validate":
        failed = False
        for source in source_files(args.path):
            model = parse_source(source)
            canvas = canvas_from_model(model)
            diagnostics = validate_canvas(canvas)
            failed = failed or has_errors(diagnostics)
            print(f"{source}:")
            print(summarize_diagnostics(diagnostics))
        if failed:
            raise SystemExit(1)

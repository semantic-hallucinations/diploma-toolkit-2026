#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import fnmatch
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from zipfile import ZipInfo


DEFAULT_IMAGE = "diploma-toolkit/compiler:local"
MAIN_TEX = Path("diploma/diploma_report.tex")
JOB_NAME = "diploma_report"
INTERNAL_PDF_NAME = f"{JOB_NAME}.pdf"
LOG_FILES = (
    f"{JOB_NAME}.log",
    "pdflatex-1.log",
    "bibtex.log",
    "pdflatex-2.log",
    "pdflatex-3.log",
)
REQUIRED_PROJECT_PATHS = (
    MAIN_TEX,
    Path("preamble.tex"),
    Path("references.tex"),
    Path("biblio"),
)
IGNORED_PROJECT_NAMES = (
    ".git",
    ".texmf",
    ".texmf-var",
    ".texmf-config",
    "build",
    "build-error-*",
    INTERNAL_PDF_NAME,
    "__pycache__",
)


class CompilerError(Exception):
    pass


class CommandError(CompilerError):
    def __init__(self, message: str, output: str = "") -> None:
        super().__init__(message)
        self.output = output


def run(cmd: list[str], *, cwd: Path | None = None, description: str = "Command") -> None:
    try:
        subprocess.run(cmd, cwd=cwd, check=True)
    except FileNotFoundError as exc:
        raise CompilerError(f"{description} not found: {cmd[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise CompilerError(f"{description} failed with exit code {exc.returncode}.") from exc


def run_quiet(cmd: list[str], *, cwd: Path | None = None, description: str = "Command") -> None:
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError as exc:
        raise CompilerError(f"{description} not found: {cmd[0]}") from exc
    if result.returncode != 0:
        raise CommandError(
            f"{description} failed with exit code {result.returncode}.",
            result.stdout,
        )


def looks_remote_input(value: str) -> bool:
    return value.startswith(("http://", "https://", "ssh://", "git://", "git@"))


def copy_tree(src: Path, dst: Path, output_pdf_name: str | None = None) -> None:
    ignored_names = list(IGNORED_PROJECT_NAMES)
    if output_pdf_name:
        ignored_names.append(output_pdf_name)
    validate_no_symlinks(src, ignored_names)
    ignored = shutil.ignore_patterns(*ignored_names)
    shutil.copytree(src, dst, ignore=ignored)


def extract_zip(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    root = dst.resolve()
    try:
        archive = zipfile.ZipFile(src)
    except zipfile.BadZipFile as exc:
        raise CompilerError(f"Invalid zip archive: {src}") from exc

    with archive:
        members = archive.infolist()
        if not members:
            raise CompilerError(f"Zip archive is empty: {src}")
        for member in members:
            validate_zip_member(member, src)
            member_path = PurePosixPath(member.filename)
            target = dst.joinpath(*member_path.parts)
            if not target.resolve().is_relative_to(root):
                raise CompilerError(f"Unsafe path in zip archive {src}: {member.filename}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
            except zipfile.BadZipFile as exc:
                raise CompilerError(f"Invalid zip archive: {src}") from exc


def validate_zip_member(member: ZipInfo, archive: Path) -> None:
    if "\\" in member.filename:
        raise CompilerError(f"Unsafe path in zip archive {archive}: {member.filename}")
    member_path = PurePosixPath(member.filename)
    if member_path.is_absolute() or ".." in member_path.parts:
        raise CompilerError(f"Unsafe path in zip archive {archive}: {member.filename}")
    mode = member.external_attr >> 16
    if stat.S_IFMT(mode) == stat.S_IFLNK:
        raise CompilerError(f"Symlinks are not allowed in zip archive {archive}: {member.filename}")


def validate_no_symlinks(src: Path, ignored_names: list[str]) -> None:
    for root, dirnames, filenames in os.walk(src, followlinks=False):
        dirnames[:] = [name for name in dirnames if not should_ignore(name, ignored_names)]
        for name in [*dirnames, *filenames]:
            if should_ignore(name, ignored_names):
                continue
            path = Path(root) / name
            if path.is_symlink():
                raise CompilerError(f"Symlinks are not allowed in project directories: {path}")


def should_ignore(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def find_project_root(base: Path) -> Path:
    candidates = []
    if (base / MAIN_TEX).is_file():
        candidates.append(base)
    candidates.extend(path.parent.parent for path in base.rglob(str(MAIN_TEX)))

    unique = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in unique:
            unique.append(resolved)

    if not unique:
        raise CompilerError(f"Could not find {MAIN_TEX} under {base}")
    if len(unique) > 1:
        formatted = "\n".join(f"  {path}" for path in unique)
        raise CompilerError(f"Multiple diploma projects found:\n{formatted}")
    return unique[0]


def validate_project(project: Path) -> None:
    missing = [path for path in REQUIRED_PROJECT_PATHS if not (project / path).exists()]
    if missing:
        formatted = "\n".join(f"  {path}" for path in missing)
        raise CompilerError(f"Input does not look like a BSUIR diploma project. Missing:\n{formatted}")


def normalize_project(project: Path) -> None:
    preamble = project / "preamble.tex"
    if not preamble.is_file():
        return

    text = preamble.read_text(encoding="utf-8")
    normalized = re.sub(
        r"\\usepackage\[authoryear,([^\]]*numbers[^\]]*)\]\{natbib\}",
        r"\\usepackage[\1]{natbib}",
        text,
    )
    normalized = re.sub(
        r"\\usepackage\[([^\]]*numbers[^\]]*),authoryear\]\{natbib\}",
        r"\\usepackage[\1]{natbib}",
        normalized,
    )
    if normalized != text:
        preamble.write_text(normalized, encoding="utf-8")


def prepare_input(input_value: str, temp_dir: Path) -> tuple[Path, Path]:
    raw_dir = temp_dir / "raw"
    work_dir = temp_dir / "work"
    raw_dir.mkdir()

    if looks_remote_input(input_value):
        raise CompilerError("Only local project directories and local zip archives are supported.")

    input_path = Path(input_value).expanduser().resolve()
    if input_path.is_dir():
        copy_tree(input_path, work_dir, output_pdf_filename(input_path))
        project = find_project_root(work_dir)
        validate_project(project)
        normalize_project(project)
        return project, input_path
    if not input_path.is_file():
        raise CompilerError(f"Input does not exist: {input_path}")
    if input_path.suffix.lower() != ".zip":
        raise CompilerError(f"Only .zip archives are supported: {input_path}")
    if not zipfile.is_zipfile(input_path):
        raise CompilerError(f"Only local project directories and zip archives are supported: {input_path}")
    extract_zip(input_path, raw_dir / "zip")

    discovered = find_project_root(raw_dir)
    validate_project(discovered)
    copy_tree(discovered, work_dir, output_pdf_filename(input_path))
    normalize_project(work_dir)
    return work_dir, input_path


def image_exists(image: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise CompilerError("Docker is not installed or is not available in PATH.") from exc
    return result.returncode == 0


def ensure_docker_available() -> None:
    if shutil.which("docker") is None:
        raise CompilerError("Docker is not installed or is not available in PATH.")
    result = subprocess.run(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise CompilerError("Docker is not running or the current user cannot access it.")


def build_image(image: str, compiler_dir: Path) -> None:
    run(["docker", "build", "-t", image, str(compiler_dir)], description="Docker image build")


def docker_run_args(project: Path, output_dir: Path, image: str) -> list[str]:
    args = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "-e",
        "HOME=/tmp",
        "-v",
        f"{project}:/workspace:ro",
        "-v",
        f"{output_dir}:/out",
    ]
    if hasattr(os, "getuid") and hasattr(os, "getgid"):
        args.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
    args.extend([image, "/workspace", "/out", str(MAIN_TEX), JOB_NAME])
    return args


def copy_pdf(build_dir: Path, output_dir: Path, pdf_name: str) -> Path:
    validate_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    src = build_dir / INTERNAL_PDF_NAME
    if not src.is_file():
        raise CompilerError(f"PDF was not produced: {src}")
    dst = output_dir / pdf_name
    shutil.copy2(src, dst)
    return dst


def copy_error_logs(build_dir: Path, output_dir: Path, error: Exception) -> Path:
    validate_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    error_dir = output_dir / f"build-error-{datetime.now().strftime('%Y-%m-%d_%H-%M-%S-%f')}"
    error_dir.mkdir(parents=True, exist_ok=False)
    for name in LOG_FILES:
        src = build_dir / name
        if src.is_file():
            shutil.copy2(src, error_dir / name)
    command_output = getattr(error, "output", "")
    if command_output:
        (error_dir / "docker-output.log").write_text(command_output, encoding="utf-8")
    (error_dir / "error.txt").write_text(f"{error}\n", encoding="utf-8")
    return error_dir


def validate_output_dir(output_dir: Path) -> None:
    if output_dir.exists() and not output_dir.is_dir():
        raise CompilerError(f"Output path exists and is not a directory: {output_dir}")


def default_output_dir(input_value: str, original_input: Path) -> Path:
    if original_input.is_dir():
        return original_input
    return original_input.parent


def output_pdf_filename(original_input: Path) -> str:
    stem = original_input.stem if original_input.is_file() else original_input.name
    return f"{stem or JOB_NAME}.pdf"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a BSUIR diploma LaTeX project into PDF using Docker.",
    )
    parser.add_argument("input", help="Local path to a project directory or zip archive.")
    parser.add_argument("-o", "--output-dir", type=Path, help="Directory for the resulting PDF.")
    parser.add_argument("--image", default=DEFAULT_IMAGE, help=f"Docker image name. Default: {DEFAULT_IMAGE}")
    parser.add_argument("--build-image", action="store_true", help="Build the Docker image before compiling.")
    parser.add_argument("--no-auto-build", action="store_true", help="Fail if the Docker image is missing.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent
    compiler_dir = root / "compiler"

    ensure_docker_available()
    if args.build_image or (not args.no_auto_build and not image_exists(args.image)):
        build_image(args.image, compiler_dir)

    with tempfile.TemporaryDirectory(prefix="diploma-build-") as temp:
        temp_dir = Path(temp)
        project, original_input = prepare_input(args.input, temp_dir)
        output_dir = (args.output_dir or default_output_dir(args.input, original_input)).expanduser().resolve()
        output_pdf = output_pdf_filename(original_input)
        validate_output_dir(output_dir)
        build_output = temp_dir / "out"
        build_output.mkdir()

        try:
            run_quiet(docker_run_args(project, build_output, args.image), description="Docker compiler run")
        except CompilerError as exc:
            error_dir = copy_error_logs(build_output, output_dir, exc)
            raise CompilerError(f"Build failed. Logs copied to: {error_dir}") from None

        try:
            print(copy_pdf(build_output, output_dir, output_pdf))
        except CompilerError as exc:
            error_dir = copy_error_logs(build_output, output_dir, exc)
            raise CompilerError(f"Build failed. Logs copied to: {error_dir}") from None

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CompilerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except OSError as exc:
        print(f"Error: Filesystem error: {exc}", file=sys.stderr)
        raise SystemExit(1)

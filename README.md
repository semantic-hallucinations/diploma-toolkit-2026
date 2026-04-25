# diploma-toolkit-2026

## Requirements

- Python 3.9+
- Docker with Docker Compose

No `pip install` is required.

## Start

Build and start the compiler container:

```sh
docker compose up -d --build
```

## Use

Build a local project directory:

```sh
python3 compiler/diploma_compile.py /path/to/project -o /path/to/output
```

Build a local zip archive:

```sh
python3 compiler/diploma_compile.py /path/to/project.zip -o /path/to/output
```

`examples/diploma_template/` is the example diploma project directory included
in this repository:

```sh
python3 compiler/diploma_compile.py examples/diploma_template -o compiler-output/diploma_template
```

## Output

`-o` is the output directory. It is created automatically and receives the PDF
and build logs.

If `-o` is omitted:

- project directory output goes to `<project>/build/diploma_report.pdf`
- zip archive output goes to `<archive-parent>/build/diploma_report.pdf`

Repeated builds overwrite files in the same output directory. Temporary LaTeX
files are removed automatically.

## Stop

```sh
docker compose down
```

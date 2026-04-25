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
python3 compiler/diploma_compile.py /path/to/project
```

PDF and logs will be written to `/path/to/project/build/`.

Build a local zip archive:

```sh
python3 compiler/diploma_compile.py /path/to/project.zip
```

PDF and logs will be written to `/path/to/build/`.

`examples/diploma_template/` is the example diploma project directory included
in this repository:

```sh
python3 compiler/diploma_compile.py examples/diploma_template
```

PDF and logs will be written to `examples/diploma_template/build/`.

## Output

`-o` is the output directory. It is created automatically and receives the PDF
and build logs.

Use `-o` only when you want a custom output directory:

```sh
python3 compiler/diploma_compile.py /path/to/project -o /path/to/output
```

Repeated builds overwrite files in the same output directory. Temporary LaTeX
files are removed automatically.

## Stop

```sh
docker compose down
```

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

PDF will be written to `/path/to/project/project.pdf`.

Build a local zip archive:

```sh
python3 compiler/diploma_compile.py /path/to/project.zip
```

PDF will be written to `/path/to/project.pdf`.

`examples/diploma_template/` is the example diploma project directory included
in this repository:

```sh
python3 compiler/diploma_compile.py examples/diploma_template
```

PDF will be written to `examples/diploma_template/diploma_template.pdf`.

## Output

`-o` is the output directory. It is created automatically and receives the PDF.
The PDF name is based on the input directory or archive name.

Use `-o` only when you want a custom output directory:

```sh
python3 compiler/diploma_compile.py /path/to/project -o /path/to/output
```

PDF will be written to `/path/to/output/project.pdf`.

Repeated successful builds overwrite the PDF. Temporary LaTeX files are removed
automatically.

On build error, logs are saved to `build-error-YYYY-MM-DD_HH-MM-SS-ffffff/`
inside the output directory.

## Stop

```sh
docker compose down
```

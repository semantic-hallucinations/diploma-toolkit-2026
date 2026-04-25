# Diploma Compiler

Build and start the compiler:

```sh
docker compose up -d --build
```

Build a local project directory:

```sh
python3 compiler/diploma_compile.py /path/to/project -o /path/to/output
```

Build a local zip archive:

```sh
python3 compiler/diploma_compile.py /path/to/project.zip -o /path/to/output
```

`examples/diploma_template/` is only the example diploma project directory in
this repository.

`-o` is the output directory. It is created automatically and receives the PDF
and build logs. If `-o` is omitted, output goes to
`<project>/build/diploma_report.pdf` for a directory or
`<archive-parent>/build/diploma_report.pdf` for a zip archive.

Stop the compiler:

```sh
docker compose down
```

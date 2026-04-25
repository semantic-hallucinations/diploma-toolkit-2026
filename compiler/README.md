# Diploma Compiler

Build and start the compiler:

```sh
docker compose up -d --build
```

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

`examples/diploma_template/` is only the example diploma project directory in
this repository.

Use `-o` only when you want a custom output directory:

```sh
python3 compiler/diploma_compile.py /path/to/project -o /path/to/output
```

PDF will be written to `/path/to/output/project.pdf`. The PDF name is based
on the input directory or archive name.

On build error, logs are saved to `build-error-YYYY-MM-DD_HH-MM-SS-ffffff/`
inside the output directory.

Stop the compiler:

```sh
docker compose down
```

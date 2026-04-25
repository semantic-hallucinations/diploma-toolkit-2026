# Diploma Compiler

Build and start the compiler:

```sh
docker compose up -d --build
```

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

`examples/diploma_template/` is only the example diploma project directory in
this repository.

Use `-o` only when you want a custom output directory:

```sh
python3 compiler/diploma_compile.py /path/to/project -o /path/to/output
```

Stop the compiler:

```sh
docker compose down
```

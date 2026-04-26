# Compiler Constraints

This file is not a roadmap. It records constraints to keep in mind when changing
the compiler.

## Reproducibility

The compiler image currently pins the Debian base image by digest and uses a
fixed TeX Live 2025 repository.

Keep this auditable when changing the image. Package updates can change PDF
output or break older LaTeX projects, so version bumps should be deliberate.

## Security

The compiler accepts local user-provided directories and zip archives. Keep the
current boundaries:

- reject remote inputs;
- reject unsafe zip paths and zip symlinks;
- reject project directory symlinks;
- run the compiler container without network access;
- keep the Docker build context restricted to `Dockerfile` and `compile.sh`.

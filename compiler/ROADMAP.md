# Compiler Roadmap

## Watch Points

- Input validation: keep checks strict for local directories and zip archives.
- Build errors: keep LaTeX, BibTeX, Docker, and filesystem failures readable.
- Warning policy: decide which LaTeX warnings should fail the build.
- Cross-platform images: verify both `linux/amd64` and `linux/arm64` builds in CI.
- Reproducibility: consider pinning the Debian base image by digest.
- Security: keep zip extraction safe and container builds network-isolated at runtime.

## Next Work

- Add unit tests for invalid input paths, invalid zip archives, and multiple projects.
- Add a small CI job that builds the image and compiles `examples/diploma_template`.
- Add an optional strict mode for overfull boxes, undefined references, and warnings.

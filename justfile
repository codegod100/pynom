# Run pynom with args (via nix run, shows outer nix output first)
pynom *ARGS:
    nix run . -- {{ARGS}}

# Run pynom build (via nix run)
build *ARGS:
    nix run . -- build {{ARGS}}

# Run pynom build with --rebuild
rebuild PACKAGE:
    nix run . -- build {{PACKAGE}} --rebuild

# Enter dev shell
dev:
    nix develop

# Run directly with Python (use inside dev shell for clean output)
run *ARGS:
    python -m pynom.cli {{ARGS}}

# Run build with Python (use inside dev shell)
py-build *ARGS:
    python -m pynom.cli build {{ARGS}}

# Install editable in dev shell
install:
    uv pip install -e .

# Build the nix package
nix-build:
    nix build . --print-build-logs

# Update flake inputs
update:
    nix flake update

# Show help
help:
    just --list
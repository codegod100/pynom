# Run pynom with args
pynom *ARGS:
    PYTHONPATH=src python -m pynom.cli {{ARGS}}

# Run pynom build
build *ARGS:
    PYTHONPATH=src python -m pynom.cli build {{ARGS}}

# Run pynom build with --rebuild
rebuild PACKAGE:
    PYTHONPATH=src python -m pynom.cli build {{PACKAGE}} --rebuild

# Enter dev shell
dev:
    nix develop

# Install pynom editable (optional)
install:
    uv pip install -e .

# Build nix package
nix-build:
    nix build . --print-build-logs

# Update flake inputs
update:
    nix flake update
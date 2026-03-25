# pynom - Python Nix Output Monitor

A Python clone of [nix-output-monitor](https://github.com/maralorn/nix-output-monitor) that provides beautiful, informative terminal output for Nix builds.

## Features

- **Rich terminal UI** with colors and symbols showing build progress
- **Build dependency tree** visualization
- **Progress tracking** for builds, downloads, and uploads
- **Time estimates** based on historical build data
- **JSON log support** for modern `nix build` commands
- **Drop-in replacement** for `nix build`, `nix shell`, `nix develop`

## Installation

```bash
pip install pynom
# or with nix:
nix profile install .
```

## Usage

### As a drop-in replacement

```bash
# Instead of: nix build .#something
pynom build .#something

# Instead of: nix shell
pynom shell nixpkgs#hello

# Instead of: nix develop
pynom develop
```

### Piping output

```bash
# Old-style nix-build
nix-build 2>&1 | pynom

# New-style with JSON logs (recommended)
nix build .#something --log-format internal-json -v 2>&1 | pynom --json

# Works with nixos-rebuild, home-manager, etc.
nixos-rebuild switch 2>&1 | pynom
```

## Status Icons

| Icon | Meaning |
|------|---------|
| ⏵ | Currently building |
| ✔ | Build completed |
| ⏸ | Waiting for dependency |
| ⚠ | Build failed |
| ↓⏵ | Downloading |
| ↓✔ | Downloaded |
| ↑⏵ | Uploading |
| ⏱︎ | Build time |
| ∑ | Total time |

## How it works

1. Parses Nix build output (human-readable or JSON format)
2. Tracks build dependencies and their status
3. Displays a live-updating terminal UI with progress
4. Stores build times for future predictions

## Comparison to original

This is a Python reimplementation inspired by the Haskell [nix-output-monitor](https://github.com/maralorn/nix-output-monitor). It aims for feature parity with a simpler codebase.
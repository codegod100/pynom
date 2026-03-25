# pynom - Python Nix Output Monitor

A Python clone of [nix-output-monitor](https://github.com/maralorn/nix-output-monitor) that provides live, informative terminal output for Nix builds and related commands.

## Features

- **Live status box** for subcommands like `build`, `profile`, `home`, and `os`
- **Persistent scrollback logs** for build output and recent activity
- **Progress tracking** for builds, downloads, and uploads
- **Time estimates** based on historical build data
- **JSON log support** for modern `nix build` commands
- **Drop-in replacement** for `nix build`, `nix profile`, `home-manager`, and `nixos-rebuild`

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

# Instead of: nix profile upgrade
pynom profile upgrade hello

# Instead of: home-manager switch
pynom home switch

# Instead of: nixos-rebuild switch
pynom os switch

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

### Display behavior

- Subcommands use the live TUI by default.
- In live TUI mode, the box shows current status and progress.
- Build logs and recent activity are printed once into scrollback instead of being redrawn inside the box.
- Pipe mode stays stream-oriented by default; use `pynom --tui` if you want the live box there too.

## How it works

1. Parses Nix build output (human-readable or JSON format)
2. Tracks build dependencies and their status
3. Displays a live status box and keeps logs in normal terminal scrollback
4. Stores build times for future predictions

## Comparison to original

This is a Python reimplementation inspired by the Haskell [nix-output-monitor](https://github.com/maralorn/nix-output-monitor). It aims for feature parity with a simpler codebase.

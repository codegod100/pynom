"""Command line interface for pynom."""

import argparse
import subprocess
import sys
import os
from typing import Optional, NoReturn

from pynom.display import BuildDisplay, StreamDisplay
from pynom.parser import NixParser, parse_stream


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="pynom",
        description="Python Nix Output Monitor - beautiful build output",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  pynom build .#my-package        Build a flake package
  pynom shell nixpkgs#hello       Enter a shell with hello
  pynom develop                   Enter a dev shell
  pynom home switch .#user        Home-manager switch
  pynom os switch .#hostname      NixOS system switch
  nix-build 2>&1 | pynom          Pipe old-style output
  nix build . --log-format internal-json -v 2>&1 | pynom --json
""",
    )
    
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Parse JSON internal-log format (use with --log-format internal-json -v)",
    )
    
    parser.add_argument(
        "--pass-through", "-p",
        action="store_true",
        default=True,
        help="Show original nix output in addition to status (default: True)",
    )
    
    parser.add_argument(
        "--tui", "-t",
        action="store_true",
        help="Use live TUI overlay instead of pass-through",
    )
    
    parser.add_argument(
        "--version", "-v",
        action="version",
        version="pynom 0.1.0",
    )
    
    # Subcommands for drop-in replacement mode
    subparsers = parser.add_subparsers(dest="command", help="Nix subcommands")
    
    # build
    build_parser = subparsers.add_parser("build", help="Build a derivation (like nix build)")
    build_parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments for nix build")
    
    # shell
    shell_parser = subparsers.add_parser("shell", help="Enter a shell (like nix shell)")
    shell_parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments for nix shell")
    
    # develop
    develop_parser = subparsers.add_parser("develop", help="Enter a dev shell (like nix develop)")
    develop_parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments for nix develop")
    
    # run (bonus)
    run_parser = subparsers.add_parser("run", help="Run an app (like nix run)")
    run_parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments for nix run")
    
    # profile
    profile_parser = subparsers.add_parser("profile", help="Manage a profile (like nix profile)")
    profile_parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments for nix profile")
    
    # home (home-manager)
    home_parser = subparsers.add_parser("home", help="Home-manager operations (like nh home)")
    home_parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments for home-manager")
    
    # os (nixos-rebuild)
    os_parser = subparsers.add_parser("os", help="NixOS system operations (like nh os)")
    os_parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments for nixos-rebuild")
    
    return parser


def run_nix_command(command: str, args: list[str], use_json: bool = True) -> int:
    """Run a nix command with monitoring."""
    import socket
    
    # Handle special commands
    if command == "home":
        # home-manager with flake auto-detection
        # args[0] is the subcommand (switch, build, etc) or empty
        subcmd = args[0] if args else "switch"
        cmd = ["home-manager", subcmd]
        rest_args = args[1:] if args else []
        
        if "--flake" not in rest_args:
            # Auto-detect: use current directory and username
            flake_arg = f".#{os.environ.get('USER', 'default')}"
            cmd.extend(["--flake", flake_arg])
        if use_json and "--log-format" not in rest_args:
            cmd.extend(["--log-format", "internal-json", "-v"])
        cmd.extend(rest_args)
        
    elif command == "os":
        # nixos-rebuild with flake auto-detection
        subcmd = args[0] if args else "switch"
        cmd = ["sudo", "nixos-rebuild", subcmd]
        rest_args = args[1:] if args else []
        
        if "--flake" not in rest_args:
            # Auto-detect: use current directory and hostname
            hostname = socket.gethostname().split('.')[0]
            flake_arg = f".#{hostname}"
            cmd.extend(["--flake", flake_arg])
        if use_json and "--log-format" not in rest_args:
            cmd.extend(["--log-format", "internal-json", "-v"])
        cmd.extend(rest_args)
        
    else:
        # Regular nix command - exec directly for interactive commands
        if command in ("run", "shell", "develop"):
            # Don't use TUI for interactive commands
            cmd = ["nix", command, *args]
            os.execvp(cmd[0], cmd)
            return 1
        
        cmd = ["nix", command]
        if use_json and command in ("build", "profile"):
            if "--log-format" not in args:
                cmd.extend(["--log-format", "internal-json", "-v"])
        cmd.extend(args)
    
    # Run with output capture
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,  # Line buffered
    )
    
    # Display with TUI
    display = StreamDisplay(show_pass_through=False, use_json=use_json)
    state = display.run_with_tui(proc.stdout)
    
    return proc.wait()


def run_pipe_mode(args: argparse.Namespace) -> int:
    """Run in pipe mode (reading from stdin)."""
    use_json = args.json
    use_tui = args.tui
    
    display = StreamDisplay(show_pass_through=args.pass_through, use_json=use_json)
    
    if use_tui:
        state = display.run_with_tui(sys.stdin)
    else:
        state = display.run(sys.stdin)
    
    # Return appropriate exit code
    if state.error:
        return 1
    if state.failed_builds > 0:
        return 1
    return 0


def main() -> NoReturn:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    # Check if we're in drop-in mode (subcommand given) or pipe mode
    if args.command:
        # Drop-in replacement mode
        exit_code = run_nix_command(args.command, args.args or [])
        sys.exit(exit_code)
    else:
        # Check if stdin has data (pipe mode) or if we should run nix directly
        if not sys.stdin.isatty():
            # Pipe mode
            exit_code = run_pipe_mode(args)
            sys.exit(exit_code)
        else:
            # No subcommand and no pipe - show help
            parser.print_help()
            sys.exit(1)


def nom_build() -> NoReturn:
    """Entry point for pynom-build alias (like nom-build)."""
    # Run nix-build and pipe output to pynom
    proc = subprocess.Popen(
        ["nix-build"] + sys.argv[1:],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    
    display = StreamDisplay(show_pass_through=True, use_json=False)
    state = display.run(proc.stdout)
    
    exit_code = proc.wait()
    if exit_code == 0 and state.failed_builds > 0:
        exit_code = 1
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
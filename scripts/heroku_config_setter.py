#!/usr/bin/env python3
"""Set Heroku config vars from a local .env file.

Usage:
  python scripts/heroku_config_setter.py --app your-app-name [--env-file .env] [--dry-run] [--yes]

Behavior:
- Reads the specified env file and collects KEY=VALUE lines (ignores comments and empty lines).
- Only keys with non-empty values are considered (optional vars left blank are skipped).
- Asks for confirmation (unless --yes) and then runs `heroku config:set KEY=VALUE ... --app APP`.

Requirements:
- Heroku CLI must be installed and the user must be logged in (`heroku login`).
"""

from __future__ import annotations
import argparse
import shlex
import subprocess
from pathlib import Path
from typing import Dict, Tuple, List


def parse_env_file(path: Path) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(f"Env file not found: {path}")
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            continue
        key, val = line.split('=', 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and val != "":
            env[key] = val
    return env


def confirm_to_set(pairs: Dict[str, str]) -> bool:
    print("The following config vars will be set on Heroku:")
    for k, v in pairs.items():
        # do not print full value for secrets
        print(f"  {k} = {'(hidden)' if len(v) > 0 else '(empty)'}")
    resp = input("Proceed? [y/N]: ").lower().strip()
    return resp in ("y", "yes")


def set_heroku_config(app: str, pairs: Dict[str, str], dry_run: bool = False) -> Tuple[int, List[Tuple[str, bool, str]]]:
    """Set config vars using Heroku CLI.

    Returns a tuple: (count_set_successfully, list_of_results)
    Each result is (KEY, success_bool, output_or_error)
    """
    if not pairs:
        return 0, []
    # Build the command: heroku config:set KEY=VAL ... --app APP
    args = ["heroku", "config:set"]
    for k, v in pairs.items():
        args.append(f"{k}={v}")
    args.extend(["--app", app])

    results: List[Tuple[str, bool, str]] = []
    if dry_run:
        print("Dry run: command that would be executed:")
        print(shlex.join(args))
        for k in pairs.keys():
            results.append((k, True, "dry-run"))
        return len(pairs), results

    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError("Heroku CLI not found - install it from https://devcenter.heroku.com/articles/heroku-cli") from exc

    success = proc.returncode == 0
    out = proc.stdout.strip() or proc.stderr.strip()
    for k in pairs.keys():
        results.append((k, success, out))
    return (len(pairs) if success else 0), results


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Set Heroku config vars from a .env file (only non-empty vars)")
    p.add_argument("--app", "-a", required=True, help="Heroku app name")
    p.add_argument("--env-file", "-e", default=".env", help="Path to .env file")
    p.add_argument("--dry-run", action="store_true", help="Show what would be set but do not run heroku CLI")
    p.add_argument("--yes", "-y", action="store_true", help="Do not prompt for confirmation")
    args = p.parse_args(argv)

    env_path = Path(args.env_file)
    try:
        pairs = parse_env_file(env_path)
    except FileNotFoundError as exc:
        print(str(exc))
        return 2

    if not pairs:
        print("No non-empty variables found to set. Ensure your .env contains KEY=VALUE entries.")
        return 0

    if not args.yes and not args.dry_run:
        if not confirm_to_set(pairs):
            print("Aborted by user")
            return 1

    count, results = set_heroku_config(args.app, pairs, dry_run=args.dry_run)
    if args.dry_run:
        print(f"Dry run completed; {count} variables would be set.")
        return 0
    if count == 0:
        print("Failed to set config vars. Heroku CLI returned an error:")
        for r in results:
            print(r[2])
        return 3
    print(f"Successfully set {count} variables on Heroku app {args.app}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

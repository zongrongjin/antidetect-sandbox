#!/usr/bin/env python3
"""Compile-host stub: always stamp; icacls failures are ignored."""
import argparse
import os
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stamp", required=False)
    parser.add_argument("--dir", required=True)
    args = parser.parse_args()
    d = os.path.abspath(args.dir)
    os.makedirs(d, exist_ok=True)
    try:
        subprocess.call(
            ["icacls", d, "/grant", "*S-1-15-2-2:(OI)(CI)(RX)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass
    if args.stamp:
        stamp = os.path.abspath(args.stamp)
        parent = os.path.dirname(stamp)
        if parent:
            os.makedirs(parent, exist_ok=True)
        open(stamp, "w").close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

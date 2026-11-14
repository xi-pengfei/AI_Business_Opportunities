"""Run the optional Apple Silicon connector with credentials read locally."""

import argparse
import os
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=root / ".env")
    parser.add_argument(
        "--runtime", type=Path, default=root / "runtime/vendor/xhs-native"
    )
    args = parser.parse_args()
    config = dict(
        line.split("=", 1)
        for line in args.config.read_text().splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )
    token = config.get("XIAOHONGSHU_TOKEN", "").strip()
    if not token:
        raise SystemExit("XIAOHONGSHU_TOKEN must be configured")
    directory = args.runtime
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.umask(0o077)
    env = dict(
        os.environ, AUTH_TOKEN=token, COOKIES_PATH=str(directory / "cookies.json")
    )
    binary = directory / "xiaohongshu-mcp.asset"
    os.execve(binary, [str(binary), "-port", "127.0.0.1:18061"], env)


if __name__ == "__main__":
    main()

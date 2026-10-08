"""Manual smoke test; never prints credentials."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict

from .providers import CodexProvider, DeepSeekProvider
from .models import QuotaError


def main() -> int:
    parser = argparse.ArgumentParser(description="Read one AI quota source once")
    parser.add_argument("provider", choices=("codex", "deepseek"))
    parser.add_argument("--codex", default="codex", help="path to the installed Codex executable")
    args = parser.parse_args()
    provider = (CodexProvider(args.codex) if args.provider == "codex" else
                DeepSeekProvider(lambda: os.environ.get("DEEPSEEK_API_KEY")))
    try:
        snapshot = provider.fetch()
    except QuotaError as exc:
        print(json.dumps({"provider": args.provider, "status": "unavailable", "message": str(exc)},
                         ensure_ascii=False))
        return 1
    print(json.dumps(asdict(snapshot), ensure_ascii=False, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

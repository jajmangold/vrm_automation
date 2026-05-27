from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.person_factory_webapp import character_catalog_index_path, write_character_catalog_index


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the compact Person Factory character API index.")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    index = write_character_catalog_index()
    output = Path(args.output) if args.output else character_catalog_index_path()
    if output != character_catalog_index_path():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

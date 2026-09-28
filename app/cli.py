import argparse
import sys

from .db import get_sessionmaker
from .refdata.load import ReferenceDataError, load_reference_data


def cmd_load_refdata(_: argparse.Namespace) -> int:
    with get_sessionmaker()() as db:
        try:
            results = load_reference_data(db)
        except ReferenceDataError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    for name, result in results.items():
        print(f"{name}: {result}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("load-refdata", help="Download and sync the S&P 500 and Congress member lists").set_defaults(func=cmd_load_refdata)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

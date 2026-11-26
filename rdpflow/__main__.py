import sys

from .ui import RDPFlowApplication


def main() -> int:
    return RDPFlowApplication().run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())

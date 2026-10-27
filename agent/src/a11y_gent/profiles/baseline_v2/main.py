"""Command entry point for the checkpointed phased baseline."""

from a11y_gent.application.cli import build_app
from a11y_gent.profiles.baseline_v2.agent import BaselineV2

app = build_app(BaselineV2())


def main() -> None:
    app()


if __name__ == "__main__":
    main()
from a11y_gent.application.cli import build_app
from a11y_gent.profiles.baseline.agent import BaselineAgent

app = build_app(BaselineAgent())


def main() -> None:
    app()


if __name__ == "__main__":
    main()
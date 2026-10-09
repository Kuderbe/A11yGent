"""Backward-compatible command entry point for the baseline agent."""

from a11y_gent.profiles.baseline.main import app, main

__all__ = ["app", "main"]


if __name__ == "__main__":
    main()
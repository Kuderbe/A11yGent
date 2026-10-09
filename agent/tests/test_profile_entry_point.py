"""Offline tests for executable agent-program entry points.

Run standalone with the stdlib:

    PYTHONPATH=src python -m tests.test_profile_entry_point
"""

import runpy


def test_baseline_module_executes_its_main_function():
    from a11y_gent.application import cli

    calls = []
    original = cli.build_app

    class _App:
        def __call__(self):
            calls.append(True)

    cli.build_app = lambda program: _App()
    try:
        runpy.run_module("a11y_gent.profiles.baseline.main", run_name="__main__")
    finally:
        cli.build_app = original

    assert calls == [True]


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()
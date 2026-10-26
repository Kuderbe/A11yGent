"""Offline tests for opening a new task window."""

import asyncio

from a11y_gent.task_setup import setup_solve_task_window


class _Navigator:
    def __init__(self, error=None):
        self.error = error
        self.opened_urls = []

    async def open(self, url):
        self.opened_urls.append(url)
        if self.error is not None:
            raise self.error


def test_setup_solve_task_window_opens_the_task_url():
    navigator = _Navigator()
    error = asyncio.run(
        setup_solve_task_window(
            navigator,
            {"number": 2, "url": "http://application.test", "description": "Place an order"},
        )
    )

    assert error is None
    assert navigator.opened_urls == ["http://application.test"]


def test_setup_solve_task_window_returns_an_execution_error_on_failure():
    navigator = _Navigator(RuntimeError("Edge did not start"))
    error = asyncio.run(
        setup_solve_task_window(
            navigator,
            {"number": 2, "url": "http://application.test", "description": "Place an order"},
        )
    )

    assert error == {
        "task_number": 2,
        "phase": "solve_task",
        "message": "Could not open a new task window: Edge did not start",
    }
    assert navigator.opened_urls == ["http://application.test"]


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()

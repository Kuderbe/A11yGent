"""Offline tests for selecting tasks before workflow execution."""

from a11y_gent.config import RunConfig
from a11y_gent.task_selection import select_cli_tasks


def test_select_cli_tasks_enumerates_the_supplied_task_as_task_one():
    tasks = select_cli_tasks(
        _config({"url": "http://application.test", "goal": "Place an order"})
    )

    assert tasks == [
        {
            "number": 1,
            "url": "http://application.test",
            "description": "Place an order",
        }
    ]


def test_select_cli_tasks_uses_the_canonical_application_url():
    config = _config({"url": "http://legacy-task.test", "goal": "Place an order"})

    tasks = select_cli_tasks(config)

    assert tasks[0]["url"] == "http://application.test"


def test_select_cli_tasks_leaves_task_selection_empty_without_a_cli_task():
    assert select_cli_tasks(_config(None)) == []


def test_select_cli_tasks_does_not_add_the_baseline_success_hint_to_workflow_tasks():
    tasks = select_cli_tasks(
        _config(
            {
                "url": "http://application.test",
                "goal": "Place an order",
                "success_hint": "The confirmation page is visible.",
            }
        )
    )

    assert tasks == [
        {
            "number": 1,
            "url": "http://application.test",
            "description": "Place an order",
        }
    ]


def _config(task):
    return RunConfig(
        application_url="http://application.test",
        task=task,
        model="test-model",
        openai_base_url="http://inference.test",
        openai_api_key="secret",
        nvda_mcp_url="http://nvda.test/mcp",
        trajectory_path="trajectory.jsonl",
    )


def _run_all():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()
"""Offline tests for common-remediation aggregate barriers."""

from a11y_gent.report_aggregation import derive_aggregate_barriers


def test_derives_one_aggregate_for_a_shared_remediation_across_tasks():
    aggregates = derive_aggregate_barriers(
        [_task_result(1, _barrier("First payment button")), _task_result(2, _barrier("Second payment button"))],
        [
            _enrichment_state(0, "First payment button"),
            _enrichment_state(1, "Second payment button"),
        ],
    )

    assert aggregates == [
        {
            "title": "Unnamed payment buttons",
            "barrier_references": [0, 1],
            "remediation": "Add an accessible name to each payment button.",
        }
    ]


def test_keeps_similar_controls_separate_when_their_remediation_targets_differ():
    aggregates = derive_aggregate_barriers(
        [_task_result(1, _barrier("First payment button")), _task_result(2, _barrier("Second payment button"))],
        [
            _enrichment_state(0, "First payment button"),
            _enrichment_state(1, "Second payment button", remediation_target="Express payment button"),
        ],
    )

    assert aggregates == []


def test_keeps_similar_controls_separate_when_their_suggested_fixes_differ():
    aggregates = derive_aggregate_barriers(
        [_task_result(1, _barrier("First payment button")), _task_result(2, _barrier("Second payment button"))],
        [
            _enrichment_state(0, "First payment button"),
            _enrichment_state(
                1,
                "Second payment button",
                suggested_fix="Replace the control with a native button.",
            ),
        ],
    )

    assert aggregates == []


def test_does_not_aggregate_multiple_occurrences_from_one_task():
    aggregates = derive_aggregate_barriers(
        [_task_result(1, _barrier("First payment button"), _barrier("Second payment button"))],
        [
            _enrichment_state(0, "First payment button"),
            _enrichment_state(1, "Second payment button"),
        ],
    )

    assert aggregates == []


def test_excludes_manual_investigation_enrichments_from_aggregates():
    fallback = _enrichment_state(1, "Second payment button")
    fallback["enrichment"] = {
        "title": "Second payment button",
        "implementation_context": "",
        "remediation_target": "",
        "suggested_fix": "manual investigation",
        "error": "DevTools inspection timed out",
    }

    aggregates = derive_aggregate_barriers(
        [_task_result(1, _barrier("First payment button")), _task_result(2, _barrier("Second payment button"))],
        [_enrichment_state(0, "First payment button"), fallback],
    )

    assert aggregates == []


def test_excludes_enrichments_without_a_complete_remediation():
    aggregates = derive_aggregate_barriers(
        [_task_result(1, _barrier("First payment button")), _task_result(2, _barrier("Second payment button"))],
        [
            _enrichment_state(0, "First payment button", remediation_target=""),
            _enrichment_state(1, "Second payment button", remediation_target=""),
        ],
    )

    assert aggregates == []


def _task_result(number, *barriers):
    return {
        "task": {"number": number, "url": "https://shop.example/", "description": f"Task {number}"},
        "verdict": {"status": "succeeded_with_avoidable_difficulty", "summary": "Completed.", "barriers": list(barriers)},
    }


def _barrier(description):
    return {
        "description": description,
        "expected_behavior": "NVDA announces the payment button.",
        "actual_behavior": "NVDA announces button.",
        "reproduction_steps": ["Navigate to payment."],
        "evidence": "Speech: button.",
    }


def _enrichment_state(
    barrier_reference,
    description,
    remediation_target="Payment buttons",
    suggested_fix="Add an accessible name to each payment button.",
):
    return {
        "barrier_reference": barrier_reference,
        "barrier": _barrier(description),
        "enrichment": {
            "title": "Unnamed payment buttons",
            "implementation_context": "Each button has no accessible name.",
            "remediation_target": remediation_target,
            "suggested_fix": suggested_fix,
        },
    }


def _run_all():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()
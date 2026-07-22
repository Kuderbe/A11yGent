# A11yGent

**Task-based accessibility testing for web applications, powered by LLM agents.**

> ## 🚧 Roadworks Ahead — Project in Very Early State 🚧
>
> **A11yGent is currently under active initial development and does not yet work.**
>
> This repository is being set up as part of an ongoing master's thesis at the Karlsruhe Institute of Technology (KIT). At this stage:
>
> - ❌ There is **no working prototype** yet
> - ❌ The framework **cannot be installed or run**
> - ❌ Documented commands, APIs, and interfaces are **planned, not implemented**
> - ❌ Reports, benchmarks, and evaluations do **not exist yet**
>
> Everything you read below describes the **intended design and goals** of the project, not its current functionality. Expect breaking changes, missing pieces, incomplete documentation, and shifting scope until the first end-to-end version is available.
>
> ⏳ **Estimated timeline:** The first release is planned for Q4 of 2026
>
> If you are interested in the underlying research, feel free to open an issue or reach out — but please don't expect a working tool yet.

A11yGent is a modular, agent-based framework that uses Large Language Model (LLM) reasoning to test whether real user tasks can be completed on a website under assistive-technology constraints. Instead of only checking rules on isolated elements, A11yGent attempts real user tasks — starting with a screen-reader profile based on NVDA — and reports whether each task succeeded, failed, or succeeded with avoidable difficulty, together with the barriers encountered along the way.

## Table of Contents

- [Motivation](#motivation)
- [How It Will Work](#how-it-will-work)
- [Planned Features](#planned-features)
- [Architecture (Planned)](#architecture-planned)
- [Getting Started](#getting-started)
- [Usage (Planned)](#usage-planned)
- [Output Format (Planned)](#output-format-planned)
- [Roadmap](#roadmap)
- [Limitations](#limitations)
- [Contributing](#contributing)

## Motivation

Web accessibility is a critical software quality concern, but existing automated checkers primarily detect low-level, rule-based issues such as missing labels or insufficient contrast. Many real barriers only become visible when a user with a disability tries to complete a **concrete task**: a button may exist in the DOM but be unreachable via keyboard, the focus order may be confusing, or a screen-reader flow may be interrupted mid-task.

A11yGent addresses this gap by evaluating accessibility at the **task level**. LLM-driven agents observe a page under the constraints of a chosen assistive-technology profile and attempt to complete user-supplied tasks, producing evidence-backed reports that describe what went wrong and why.

A11yGent is **not** a replacement for accessibility experts or user testing with people with disabilities. It is designed to help development teams find problems earlier and make manual testing more focused.

## How It Will Work

> ⚠️ *This section describes the planned behavior. None of it is implemented yet.*

1. **Input:** a website URL and one or more natural-language tasks (e.g. *"Sign up for a new account"*).
2. **Agent profile:** the agent receives only information available to a user of the chosen assistive technology (e.g. accessible names, roles, states, headings, landmarks, and navigation traces for a screen-reader profile).
3. **Interaction loop:** the agent reasons about the task and its current observation, chooses an action, executes it in a Chromium-based browser, and records the outcome.
4. **Decision:** for each task, the agent decides whether it is completed, blocked, or only possible with avoidable difficulty.
5. **Output:** an evidence-backed report with the full interaction trace, encountered barriers, and (optionally) mappings to WCAG success criteria.

## Planned Features

- 🧩 **Modular framework** — swappable agent profiles, LLM backends, and interaction backends
- 🦮 **Screen-reader agent profile** based on NVDA-style observations as the default profile
- 📝 **Task-level reports** with three outcomes: *completed*, *blocked*, or *completed with avoidable difficulty*
- 🔍 **Evidence-based findings** — every barrier links back to accessibility-tree entries, focus traces, or DOM references
- 🔄 **Full logging** of prompts, inputs, outputs, and configuration for reproducibility

## Architecture (Planned)

A11yGent is designed as a pipeline of exchangeable modules:

| Module | Responsibility |
|--------|----------------|
| **Task provider** | Supplies user-given tasks (and, optionally, discovered tasks) |
| **Agent profile** | Defines simulated user constraints, available observations, and permitted actions |
| **Interaction backend** | Executes actions in a Chromium-based browser and records evidence |
| **Reasoning module** | An LLM that interprets the task and observations, plans the next step, and decides on task completion |
| **Reporting module** | Aggregates traces, barriers, evidence, and baseline findings into a report |

Both the LLM and the agent profile can be exchanged. Evaluations use one fixed LLM configuration with reproducible settings where possible.

## Getting Started

> 🚧 **Not available yet.**

## Usage (Planned)

> 🚧 **Not implemented yet.**

## Output Format (Planned)

Every task will produce **one report per task–agent pair**, containing:

- The task outcome: `completed`, `blocked`, or `completed_with_difficulty`
- A structured **trace** of attempted steps and observations
- A list of **encountered barriers**, each with:
  - a description
  - supporting **evidence** (accessibility-tree entries, focus traces, DOM references)

Reports will be stored as machine-readable JSON alongside a human-readable rendering.

## Roadmap

### Must-have (minimum viable version)

- [ ] Modular agent-based framework taking a URL plus tasks
- [ ] Screen-reader-style agent profile based on NVDA-style observations
- [ ] Task-level report generation with full evidence trace
- [ ] Controlled mutation benchmark
- [ ] Comparison against a rule-based checker as a baseline

### Nice-to-have

- [ ] Automatic task discovery from the page
- [ ] Low-vision agent profile
- [ ] Additional baseline tools
- [ ] Developer-facing remediation suggestions

## Limitations

- **Scope:** A11yGent targets web applications running in a browser. Desktop applications and native mobile apps may follow in the future. Full WCAG certification, and complete cognitive accessibility evaluation are **out of scope**.
- **Not a replacement:** A11yGent complements, but does not replace, accessibility experts or testing with users with disabilities.
- **LLM reliability:** LLMs can produce plausible but incorrect explanations. All reports include evidence identifiers so findings can be verified independently of the LLM's summary.
- **Ground truth:** Precision and recall will only be reported on the controlled mutation benchmark. Real-world applications are evaluated qualitatively because complete ground truth is not available.
- **Fuzzy boundaries:** There is no widely accepted list of accessibility issues that rule-based checkers cannot detect. The mutation benchmark makes A11yGent's target scope explicit and testable.

## Contributing

This project is developed as part of a master's thesis and is not yet accepting external code contributions. Once the core pipeline is stable, contribution guidelines will be added.

Feedback, bug reports, and discussions are already very welcome — please open an issue.

## Acknowledgements

Developed at the Center for Digital Accessibility and Assistive Technology (ACCESS@KIT), Karlsruhe Institute of Technology.

Special thanks to the participants of the accompanying accessibility survey, whose real-world experiences with assistive technologies help shape this work.

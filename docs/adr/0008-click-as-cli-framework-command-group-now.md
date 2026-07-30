---
status: accepted
---

# Click as the CLI framework; cli/main.py is a command group from the first command

SDD §2.1 listed the CLI interface technology as "argparse / Click" without deciding between them. F03.1 (`services/zone_calculator.py` + its CLI command) is the first CLI code anywhere in the repo, and two already-filed tickets — F01.1 and F02.1 — will each add their own CLI-visible command shortly after. Whatever shape `cli/main.py` takes here is what those tickets build on; picking wrong means reworking already-merged CLI code, not just this ticket's.

We're using Click, structured as a `click.group()` from the start, with `zones` as its first subcommand (`python -m apex_coach.cli.main zones --max-hr 192 --resting-hr 48`). F01.1 and F02.1 add their smoke-print commands as sibling `@cli.command()`s with no rework of this ticket's code. Click's decorator-based option parsing was chosen over stdlib `argparse` despite the new dependency, since the CLI surface is already known to grow (three commands filed before any exist) and Click's `group()` gives that structure natively rather than through `argparse.add_subparsers()`'s more verbose API.

Alternative considered: `argparse` with subparsers, avoiding a new dependency entirely — consistent with SDD §2.1's "zero frontend overhead" rationale for choosing a CLI over a web frontend in v1.0. Rejected in favor of Click's ergonomics for a CLI surface that's expected to keep growing across F01/F02/F04/F05 and beyond.

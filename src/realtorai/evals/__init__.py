"""Evaluation harness — measures model behaviour, not plumbing.

The pytest suite proves the workflow machinery works. Nothing in it can tell
you whether the intake classifier still recognises a prose handoff after a
prompt edit, or whether a newly added record field can actually reach a form.
That is what lives here.

Two deliberate structural choices:

* **Cases are Python literals, never data files.** `git ls-files data/` is
  empty by design — this repo handles real client paperwork and everything
  under `data/` is gitignored. Eval cases are fictionalised derivations of real
  inbox traffic, committed as source so CI can actually run them.
* **This is a package under `src/`, not a script.** It gets ruff and strict
  mypy for free, and `tests/` can import the scoring math directly instead of
  shelling out.
"""

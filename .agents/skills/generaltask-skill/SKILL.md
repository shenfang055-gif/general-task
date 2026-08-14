---
name: generaltask-skill
description: Design, prepare, run, grade, and review artifact-based AI4S desktop UI general tasks for life science, materials science, and earth science. Use when working in the general-task repository to add or revise task cards, inputs, deterministic oracles, hard gates, scoring rubrics, ablation conditions, evaluation runs, or frozen-workspace results.
---

# GeneralTask Skill

Use the repository taskbook as the source of truth and preserve the separation between agent-visible inputs and hidden evaluation materials.

## Load the relevant specification

1. Locate the repository root containing `docs/ai4s-ui-taskbook-v0.1.md`.
2. Read the taskbook sections relevant to the request:
   - Read §§1 and 5 for execution or experiment setup.
   - Read §§3, 4, and 7 for task authoring, grading, or review.
   - Read the task card in §6 for the selected task ID.
3. Inspect `docs/inputs/<task-id>/` only for agent-visible inputs.
4. Inspect `docs/oracles/<task-id>/` only for grading or task-development work. Never copy oracle logic, gold values, hidden mappings, or rubric answers into an evaluation workspace or user prompt.
5. If the taskbook is unavailable, stop and ask for the repository or document instead of inventing requirements.

## Route the work

- For a new or revised task, follow **Author a task**.
- For an evaluation run, follow **Prepare and run an evaluation**.
- For scoring, follow **Grade frozen artifacts**.
- For acceptance or audit work, follow **Review a contribution**.

## Author a task

1. Define a unique lowercase hyphenated task ID, domain/sub-domain, L1–L3 level, time limit, anchor capability, and related capability codes.
2. Make the task a real scientific workflow with observable artifacts, not a knowledge question or generic table-cleaning exercise.
3. Write one self-contained prompt that an operator can paste once. State exact input paths, methods or formulas, output paths, schemas, units, tolerances, and interpretation limits.
4. Limit formal deliverables to roughly five or six files. Require reproducible code for workflow or research-level tasks.
5. Define two to four hard gates for the most dangerous silent scientific failures, such as wrong joins, direction, units, masks, state handling, row sets, or use of stale data.
6. Allocate 80 deterministic points across artifact checks. Reserve 20 judge points for evidence, method explanation, restraint, and readability; never delegate scientific gates to the judge.
7. Place redistributable, agent-visible data in `docs/inputs/<task-id>/`. Exclude patient-sensitive data, gold answers, hidden mappings, expected values, oracles, and grader-only notes.
8. Add an independent grader at `docs/oracles/<task-id>/oracle.py`, or add a hidden manual checklist when a Python oracle is unsuitable. Do not import or execute untrusted submission code from the grader.
9. Record the skill and MCP ablation names without leaking the solution or making an external tool the only source of required information.
10. Validate the grader with a correct submission, empty output, a scientifically wrong but well-formed output, and an ID/coverage error. Add unit, direction, mask, NaN/Inf, decoy, or stale-output controls when relevant.

## Prepare and run an evaluation

1. Create a fresh workspace containing read-only `inputs/` copied from one task and an empty `output/` directory.
2. Keep oracles, gold answers, hidden rubrics, and grader-only files outside the workspace.
3. Open a new desktop-client task in that workspace, enable only the assigned experimental condition, paste the task-card prompt once, and start timing.
4. Handle routine permission dialogs only. Do not provide scientific hints, corrections, or additional steps.
5. Stop at the task time limit, prevent further workspace writes, and freeze the artifacts.
6. Record task ID, harness, condition, visible client/model, trial, wall time, run status, intervention, and scoring status. Use `N/A` for unavailable facts rather than guessing.

## Grade frozen artifacts

1. Grade only the frozen workspace and the predefined rubric. Do not use chat text as an artifact and do not adjust tolerances after seeing the result.
2. Run the task-specific oracle exactly as documented in `docs/oracles/<task-id>/`. Treat files in the submitted workspace as untrusted data.
3. Apply every hard gate before interpreting the numeric score. Report the deterministic 0–80 score, criterion-level evidence, hard-gate status, and failure codes.
4. Assign the blind 0–20 judge score only to explanation quality, evidence use, limitations, and visual or textual readability.
5. Preserve enough evidence to reproduce the score from the frozen artifacts alone.

## Review a contribution

Reject or request revision when any of these conditions hold:

- The workflow is not scientifically meaningful or requires operator coaching.
- The prompt, schemas, units, row-set policy, tolerances, or deliverables are ambiguous.
- Agent-visible inputs contain hidden evaluation information or licensing is unclear.
- Hard gates miss plausible silent scientific failures.
- The deterministic rubric cannot be reproduced independently.
- The grader executes untrusted submission code or shares implementation logic with the submitted solution.
- Correct, empty, deliberate-wrong, and coverage-error controls have not been tested three times each.
- Two operators cannot prepare and run the task independently within 1.5 times the stated limit.

End authoring or review work with a concise list of changed paths, validation performed, unresolved risks, and whether the task meets the taskbook acceptance criteria.

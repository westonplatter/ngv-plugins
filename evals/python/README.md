# Python eval harness — ibkr-data-protection

Python runner for the `ibkr-data-protection` skill. Uses the Anthropic Python
SDK pointed at LM Studio's Anthropic-compatible endpoint.

See [`../README.md`](../README.md) for LM Studio setup and prerequisites.

## Files

- `pyproject.toml` — uv project, depends on `anthropic`
- `cases.py` — `TEST_CASES` list of dicts
- `run_evals.py` — loads SKILL.md as the system prompt, sends each case's
  synthetic content as a wrapped user message, parses `path:line category`
  lines from the response, and reports pass/fail

## Run

```bash
cd evals/python
uv sync
uv run python run_evals.py
```

## Env overrides

| Var | Default |
|---|---|
| `LM_STUDIO_URL` | `http://localhost:1234` |
| `LM_STUDIO_MODEL` | `qwen3.5-9b@q4_k_s` |
| `SKILL_PATH` | `../../plugins/ngv-dev/skills/ibkr-data-protection/SKILL.md` |

## Adding a case

Append to `TEST_CASES` in `cases.py`:

```python
{
    "name": "snake_case_id",
    "input": "...synthetic file content...",
    "should_flag": True,            # or False for clean cases
    "expected_categories": ["account-id"],  # [] when should_flag is False
}
```

Pass criteria: when `should_flag` is `True`, every category in
`expected_categories` must appear in the model output (extras allowed). When
`False`, the output must contain zero `path:line` finding rows.

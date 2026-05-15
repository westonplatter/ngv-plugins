# Evals

Local eval harness for NGV skills. Runs against a local model served by
[LM Studio](https://lmstudio.ai/) using the Anthropic SDK pointed at LM
Studio's Anthropic-compatible endpoint — no calls to the real Anthropic API,
no per-run cost.

## What's covered today

- `ibkr-data-protection` — Python harness in `python/` and TypeScript harness
  in `typescript/`. Two account-id cases (one planted leak, one properly
  anonymized placeholder) verifying the skill flags real-looking IBKR account
  IDs and leaves documented placeholders alone.

## Prerequisites

1. **LM Studio 0.3+** running locally on `http://localhost:1234`.
2. In LM Studio's **Developer / Server** tab, enable the **Anthropic API**
   toggle (exposes `/v1/messages`).
3. A model loaded — default is `qwen3.5-9b@q4_k_s`. Override with
   `LM_STUDIO_MODEL`.
4. [`uv`](https://github.com/astral-sh/uv) installed.

Sanity-check the endpoint:

```bash
curl http://localhost:1234/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: lm-studio" \
  -H "anthropic-version: 2023-06-01" \
  -d '{"model":"qwen3.5-9b@q4_k_s","max_tokens":32,"messages":[{"role":"user","content":"/no_think ping"}]}'
```

## Run

Python:

```bash
cd evals/python
uv sync
uv run python run_evals.py
```

TypeScript:

```bash
cd evals/typescript
npm install
npm run eval
```

Env overrides (both): `LM_STUDIO_URL`, `LM_STUDIO_MODEL`, `SKILL_PATH`.

## Layout

```
evals/
  README.md          ← this file
  SPEC.md            ← original (broader) spec, kept for reference
  python/
    pyproject.toml
    cases.py         ← test case definitions
    run_evals.py     ← runner
  typescript/
    package.json
    tsconfig.json
    cases.ts
    run_evals.ts
```

## Adding a case

Append an entry to `TEST_CASES` in `python/cases.py` or `typescript/cases.ts`:

- `name` — snake_case id
- `input` — synthetic file content fed to the skill (treated as a staged diff)
- `should_flag` — `True` if the skill should report a finding, else `False`
- `expected_categories` — list of category labels expected when `should_flag`
  is `True` (e.g. `["account-id"]`); empty when `False`

Pass criteria are permissive on extra findings, strict on missing ones — the
skill is intentionally cautious ("when in doubt, flag it").

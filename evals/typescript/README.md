# TypeScript eval harness — ibkr-data-protection

TypeScript runner for the `ibkr-data-protection` skill. Uses the Anthropic
TypeScript SDK pointed at LM Studio's Anthropic-compatible endpoint. Run via
[`tsx`](https://github.com/privatenumber/tsx) (no build step).

See [`../README.md`](../README.md) for LM Studio setup and prerequisites.

## Files

- `package.json` — depends on `@anthropic-ai/sdk`, dev dep `tsx`
- `tsconfig.json` — ES2022, strict, ESM
- `cases.ts` — `TestCase` interface and `TEST_CASES` array
- `run_evals.ts` — loads SKILL.md as the system prompt, sends each case's
  synthetic content as a wrapped user message, parses `path:line category`
  lines from the response, and reports pass/fail

## Run

```bash
cd evals/typescript
npm install
npm run eval
```

## Env overrides

| Var | Default |
|---|---|
| `LM_STUDIO_URL` | `http://localhost:1234` |
| `LM_STUDIO_MODEL` | `qwen3.5-9b@q4_k_s` |
| `SKILL_PATH` | `../../plugins/ngv-dev/skills/ibkr-data-protection/SKILL.md` |

## Adding a case

Append to `TEST_CASES` in `cases.ts`:

```typescript
{
  name: "snake_case_id",
  input: "...synthetic file content...",
  shouldFlag: true,                  // or false for clean cases
  expectedCategories: ["account-id"], // [] when shouldFlag is false
}
```

Pass criteria: when `shouldFlag` is `true`, every category in
`expectedCategories` must appear in the model output (extras allowed). When
`false`, the output must contain zero `path:line` finding rows.

Cases run sequentially — LM Studio is single-threaded.

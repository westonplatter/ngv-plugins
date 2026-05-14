# Local Eval Harness — Volatility Trade Classifier Skill

## Goal

Build a zero-cost local eval harness that runs the `vol-trade-classifier` Claude Code
skill against a local model served by LM Studio, using the Anthropic SDK. No calls are
made to the Anthropic API. The harness validates that a local model can correctly follow
the skill's classification instructions for volatility trades.

---

## Prerequisites

### LM Studio

- Version 0.3 or later (Anthropic API support is required)
- A model loaded and the server running — recommended: **Qwen3-8B Q4_K_M** or larger
- Anthropic API toggle enabled in the Server tab
- Default endpoint: `http://localhost:1234`

Verify the server is up before running evals:

```bash
curl http://localhost:1234/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: lm-studio" \
  -H "anthropic-version: 2023-06-01" \
  -d '{"model":"local-model","max_tokens":32,"messages":[{"role":"user","content":"/no_think ping"}]}'
```

### Skill file location

```
plugins/ngv-dev/skills/vol-trade-classifier/SKILL.md
```

The skill must classify a described volatility trade into exactly one of these buckets:

| Bucket | Short description |
|---|---|
| `risk` | Undefined-risk structures or net long premium |
| `premium` | Defined-risk credit structures, net short premium |
| `gamma` | Structures that profit from realized vol / gamma scalping |
| `directional` | Trades with a strong delta bias as primary thesis |
| `delta_hedge` | Trades entered primarily to offset delta from existing positions |
| `earnings` | Structures sized or timed around an earnings event |

The skill's output format must include the bucket label on a line by itself, e.g.:

```
Classification: premium
```

---

## Repository layout expected by the agent

```
evals/
  SPEC.md               ← this file
  python/
    requirements.txt
    run_evals.py
    cases.py            ← test case definitions
  typescript/
    package.json
    tsconfig.json
    run_evals.ts
    cases.ts            ← test case definitions
```

---

## Test cases

The agent must implement all cases in both harnesses. Cases are grouped by expected
bucket. Each case has:

- `name` — unique snake_case identifier
- `input` — the user message sent to the model (the trade description)
- `expected_bucket` — the single label the model must emit
- `tags` — optional labels for filtering (e.g. `"options"`, `"futures"`, `"earnings"`)

### `risk` bucket

```
name: naked_short_put_undefined_risk
input: "Sold 1 TSLA 200 put naked, no hedge, 21 DTE. Collecting premium but max loss is
        theoretically unbounded to the downside."
expected_bucket: risk

name: long_straddle_breakeven_play
input: "Bought ATM straddle on SPY, 7 DTE, expecting a large move either direction.
        Full premium at risk."
expected_bucket: risk
```

### `premium` bucket

```
name: iron_condor_defined_risk
input: "Opened a 10-wide iron condor on SPX, 45 DTE. Sold the 4200/4190 put spread and
        the 4400/4410 call spread for a net credit of $3.20."
expected_bucket: premium

name: short_strangle_with_wings
input: "Short strangle on QQQ with 20-delta wings on both sides for protection.
        Net credit trade, theta positive."
expected_bucket: premium
```

### `gamma` bucket

```
name: long_gamma_scalp
input: "Long gamma position on SPY, scalping deltas every 0.10 move. Holding long
        straddle and delta-neutralizing throughout the day."
expected_bucket: gamma

name: backspread_for_gamma
input: "1x2 call backspread on NVDA. Net long gamma, looking to profit from a
        large realized move. Small debit paid."
expected_bucket: gamma
```

### `directional` bucket

```
name: long_call_bullish
input: "Bought 5 AAPL 190 calls, 30 DTE. Straightforward bullish directional bet.
        Not hedged."
expected_bucket: directional

name: put_spread_bearish
input: "Bought a 2-wide put spread on META, bearish on earnings miss.
        Primary thesis is downside directional move."
expected_bucket: directional
```

### `delta_hedge` bucket

```
name: short_calls_against_long_stock
input: "Sold covered calls on my long MSFT stock position to reduce delta exposure
        after a big run-up. Not a standalone premium trade."
expected_bucket: delta_hedge

name: buying_puts_to_hedge_portfolio
input: "Bought SPY puts to offset the delta of my long equity book going into a
        macro risk event. Size matched to portfolio beta."
expected_bucket: delta_hedge
```

### `earnings` bucket

```
name: short_strangle_into_earnings
input: "Sold AMZN strangle 1 DTE before earnings, expecting IV crush post-announcement.
        Will close immediately after the print."
expected_bucket: earnings

name: long_straddle_earnings_vol
input: "Long GOOG straddle sized for the earnings move. Entered 3 days before report,
        expecting the stock to move more than the market implies."
expected_bucket: earnings
```

---

## Python harness spec

### `evals/python/requirements.txt`

```
anthropic>=0.40.0
pytest>=8.0.0
```

### `evals/python/cases.py`

Define `TEST_CASES` as a list of dicts with keys: `name`, `input`, `expected_bucket`,
`tags` (list of str).

### `evals/python/run_evals.py`

Requirements:

1. Read `SKILL_PATH` from an env var `SKILL_PATH`; default to
   `../../plugins/ngv-dev/skills/vol-trade-classifier/SKILL.md` relative to the script.
2. Read `LM_STUDIO_URL` from env var; default to `http://localhost:1234`.
3. Instantiate `anthropic.Anthropic(base_url=LM_STUDIO_URL, api_key="lm-studio")`.
4. For each test case:
   - Prepend `/no_think ` to the input message (suppresses Qwen3 thinking tokens).
   - Call `client.messages.create(model="local-model", max_tokens=512, system=skill_text, messages=[...])`.
   - Extract the bucket label using a regex: `r"classification:\s*(\w+)"` (case-insensitive).
   - Compare extracted label to `expected_bucket`.
5. Print a result line per case: `[PASS]` or `[FAIL]` with the case name.
6. On failure, print: expected bucket, extracted bucket, and first 300 chars of model output.
7. Print a final summary: `X/Y passed`.
8. Exit with code `0` if all pass, `1` if any fail.

CLI usage:

```bash
cd evals/python
pip install -r requirements.txt
python run_evals.py

# run a single bucket
python run_evals.py --bucket premium

# run by tag
python run_evals.py --tag earnings
```

CLI flags:
- `--bucket <name>` — filter to cases with `expected_bucket == name`
- `--tag <name>` — filter to cases where `name` is in `tags`
- `--url <url>` — override LM Studio URL (same as env var)
- `--skill <path>` — override SKILL.md path

---

## TypeScript harness spec

### `evals/typescript/package.json`

```json
{
  "name": "vol-trade-classifier-evals",
  "version": "0.1.0",
  "scripts": {
    "eval": "ts-node run_evals.ts",
    "eval:bucket": "ts-node run_evals.ts --bucket",
    "eval:tag": "ts-node run_evals.ts --tag"
  },
  "dependencies": {
    "@anthropic-ai/sdk": "^0.40.0"
  },
  "devDependencies": {
    "ts-node": "^10.9.0",
    "typescript": "^5.4.0"
  }
}
```

### `evals/typescript/tsconfig.json`

Standard `ts-node` config targeting `ES2022`, `moduleResolution: node`, `strict: true`.

### `evals/typescript/cases.ts`

Export a `TestCase` interface and a `TEST_CASES` array matching the cases defined above.

```typescript
export interface TestCase {
  name: string;
  input: string;
  expectedBucket: string;
  tags: string[];
}

export const TEST_CASES: TestCase[] = [ /* all cases from the spec */ ];
```

### `evals/typescript/run_evals.ts`

Requirements:

1. Read `SKILL_PATH` from `process.env.SKILL_PATH`; default to
   `../../plugins/ngv-dev/skills/vol-trade-classifier/SKILL.md` relative to the script.
2. Read `LM_STUDIO_URL` from `process.env.LM_STUDIO_URL`; default to `http://localhost:1234`.
3. Instantiate `new Anthropic({ baseURL: LM_STUDIO_URL, apiKey: "lm-studio" })`.
4. Parse CLI args (`process.argv`) for `--bucket`, `--tag`, `--url`, `--skill` flags.
5. For each test case (filtered by flags if provided):
   - Prepend `/no_think ` to the input.
   - Call `client.messages.create(...)` with `model: "local-model"`, `max_tokens: 512`.
   - Extract bucket via `/classification:\s*(\w+)/i`.
   - Compare to `expectedBucket`.
6. Print `[PASS]` / `[FAIL]` per case. On fail, print expected, got, output excerpt.
7. Print final `X/Y passed` summary.
8. Call `process.exit(failures > 0 ? 1 : 0)`.
9. Run cases **sequentially** (not `Promise.all`) — LM Studio is single-threaded.

CLI usage:

```bash
cd evals/typescript
npm install
npm run eval
npx ts-node run_evals.ts --bucket premium
npx ts-node run_evals.ts --tag earnings --url http://localhost:1234
```

---

## Eval output format (both harnesses)

```
[PASS] iron_condor_defined_risk
[PASS] short_strangle_with_wings
[FAIL] naked_short_put_undefined_risk
       expected: risk
       got:      premium
       output:   "...The trade collects a credit and has limited upside, so I'd classify
                  this as premium..."

Results: 11/12 passed
```

---

## Notes for the implementing agent

- **Do not** import or call `@anthropic-ai/sdk` with a real Anthropic API key. The
  `api_key`/`apiKey` value must always be the literal string `"lm-studio"` or read from
  an env var that defaults to that value. No live API calls.
- The `model` field value is ignored by LM Studio. Use `"local-model"` as a clear
  placeholder.
- `/no_think` must be prepended to every user message to suppress Qwen3's chain-of-thought
  thinking tokens and keep eval output fast and parseable.
- If the skill file does not exist at the expected path, the harness must exit immediately
  with a clear error message: `"SKILL.md not found at <path>. Did you create the skill?"`.
- Do not add retry logic. If LM Studio is unreachable, let the SDK throw and surface the
  raw error — this is a developer tool, not production code.
- Bucket extraction uses regex, not string equality on the full response, because local
  models often wrap the label in surrounding prose.

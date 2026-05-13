---
name: ibkr-data-protection
description: Detect real (non-anonymized) Interactive Brokers data in files before it gets committed. Use when the user asks to "review staged files for IBKR data", "check for IBKR leaks", "scan for real account data", or before committing changes that touch IBKR sample data, schema docs, fixtures, or anything generated from TWS/Flex Query exports. Applies the NGV IBKR anonymization conventions: account IDs, contract/trade/exec IDs, API tokens, and trading dates must match documented anonymized shapes, not real values.
---

# IBKR Data Protection

This skill helps quant devs avoid committing real Interactive Brokers (IBKR) account data. It applies a **denylist of suspicious shapes** against staged content and prints offending lines so the dev can fix them (or delegate the fix back to Claude).

## When to use

Activate when the user:
- Asks to review staged files for IBKR data, account leaks, or sensitive trading info.
- Runs the `/ngv-ibkr-check` command.
- Is about to commit changes that touch documentation, sample data, schemas, fixtures, notebooks, or anything that could have been generated from a real TWS / Flex Query export.

This skill is **review-on-demand only**. It does not block commits. The workflow is: dev asks → Claude scans → Claude prints `file:line` offending entries with the anonymized pattern to use → dev fixes or asks Claude to fix.

## Review procedure

1. Run `git diff --cached` to get staged content. If nothing is staged, fall back to `git diff` (unstaged) and tell the user that's what you scanned.
2. Apply the **denylist rules** below to every added/modified line.
3. For each match, output: `path:line  <category>  <offending value>  → suggested anonymized form`.
4. Group by category at the end with a short summary count.
5. If nothing matches, say so explicitly — "No suspicious IBKR shapes found in N staged files."

Scan **all staged file types** (code, docs, csv, json, yaml, notebooks). Skip binary/lockfiles only if they're clearly noise.

## Denylist rules

A value is "suspicious" if it looks real — i.e. it matches an IBKR shape but does **not** match the documented anonymized patterns. When in doubt, flag it; the dev decides.

### Account IDs

- **Pattern**: `\bU\d{7}\b` (live) or `\bDU\d{7}\b` (paper).
- **Known anonymized**: `U1234567`, `U9999999`, and other obvious placeholders (`U0000000`, `U1111111`, sequential repeats).
- **Flag**: any `U\d{7}` / `DU\d{7}` that isn't an obvious placeholder.
- **Suggest**: `U1234567` or `U9999999`.

### Contract IDs (conId, underlying conId)

- **Pattern**: bare 9-10 digit integers appearing in conId-like fields (`conId`, `underlyingConId`, `fillContractId`, column headers with "conid").
- **Known anonymized**: sequential `123456789`, `234567890`, `345678901`, `400000001`, `111111111`, `222222222`, `333333333`, `600000001.0`-style.
- **Flag**: 9-10 digit IDs in conId context that aren't sequential / repdigit / round-million patterns.
- **Suggest**: `123456789` (sequential range) or `400000001` (round-million range).

### Trade / Transaction / Order / Perm IDs

- **Pattern**: 7-10 digit integers in fields named `tradeID`, `transactionID`, `ibOrderID`, `permId`.
- **Known anonymized ranges**:
  - tradeID: `1000000001+`
  - transactionID: `5000000001+`
  - ibOrderID: `9000000001+`
  - permId: `7777777`, `8888888`, `9999999`
- **Flag**: values outside those ranges or with non-round, non-sequential digits.
- **Suggest**: pick from the appropriate range.

### Execution / Brokerage IDs

- **Pattern**: hex-like dotted strings, e.g. `[0-9a-f]{8}\.[0-9a-f]{8}\.\d{2}\.\d{2}` for `ibExecID`, or `00[a-f0-9]{6}\.00[a-f0-9]{6}\.\d{8}\.\d{3}` for brokerage IDs.
- **Known anonymized**: `0000abcd.12345678.01.01`, `0000efgh.23456789.01.01`, `00aabbcc.00ddeeff.11223344.000`, etc. — values using only `abcd/efgh/ijkl/wxyz` letter sequences or repeating digits.
- **Flag**: hex strings that look like real entropy (mixed hex characters, not from the documented placeholder alphabet).
- **Suggest**: `0000abcd.12345678.01.01` (execID) or `00aabbcc.00ddeeff.11223344.000` (brokerage).

### External Execution IDs (extExecID)

- **Pattern**: alphanumeric strings ~15 chars in `extExecID` context.
- **Known anonymized**: `ABC123XYZ000001`, `DEF456UVW000002`, `GHI789RST000003` — letter triplets + sequential trailing digits.
- **Flag**: random-looking alphanumeric extExecIDs.
- **Suggest**: `ABC123XYZ000001`.

### API credentials & tokens

- **Patterns**:
  - Flex Query tokens: long digit strings (15+ digits) near `token`, `flex`, `FLEX_TOKEN`.
  - Gateway passwords / client portal API keys: assignments to `IBKR_PASSWORD`, `IB_PASSWORD`, `CP_API_KEY`, `client_portal_key`, `flex_token`, etc.
  - Any value resembling a secret in a `.env`, config, or notebook cell.
- **Flag**: any non-empty assigned value to these names that isn't an obvious placeholder (`"REDACTED"`, `"xxx"`, `"your-token-here"`, `""`).
- **Suggest**: replace with env var reference and add to `.env.example` with a placeholder.

### Dates & times

- **Pattern**: dates within the last ~90 days from today, or with non-round timestamps (e.g. `14:23:17`, `09:47:32`) in trade-data context.
- **Known anonymized**: January 2025 dates (`2025-01-15`, `2025-01-16`, `2025-01-20`), round times (`10:30:00`, `11:45:00`, `15:30:00`, `16:15:00`).
- **Flag**: recent dates + non-round seconds together — strong signal of real trade timestamps.
- **Suggest**: `2025-01-15 10:30:00-05:00`.

## What to leave alone

Do **not** flag these — they're meant to be realistic:

- Real ticker symbols (`BABA`, `MES`, `MNQ`, `MCL`, `SPY`, etc.).
- Real exchanges (`CBOE`, `CME`, `NYMEX`, `NYSE`, `MEMX`, `SMART`, etc.).
- Security types (`OPT`, `FUT`, `STK`, `CASH`).
- Currencies (`USD`, `EUR`, etc.).
- Realistic prices, quantities, multipliers, strikes, expirations.
- Order types (`LMT`, `MKT`, `STP`), actions (`BUY`, `SELL`), TIF (`DAY`, `GTC`), statuses (`Filled`, `Cancelled`).
- Time zones (`US/Eastern`, `UTC`).
- Boolean flags.

## Output format

```
Found N suspicious IBKR values in M files:

path/to/file.md:42   account-id   U8675309        → U1234567
path/to/file.md:58   exec-id      0000f1a2.b3c4d5e6.01.01   → 0000abcd.12345678.01.01
samples/trades.csv:7 date         2024-11-18 14:23:17-05:00 → 2025-01-15 10:30:00-05:00
.env.sample:3        credential   FLEX_TOKEN=8472619384726193 → FLEX_TOKEN=<placeholder, move real value to local .env>

Summary: 2 account-id, 1 exec-id, 1 date, 1 credential.
```

If no matches: `No suspicious IBKR shapes found in N staged files.`

## After printing findings

Ask the user: "Want me to apply these anonymizations to the staged files?" — don't auto-edit. The dev may want to fix manually or scope which findings to address.

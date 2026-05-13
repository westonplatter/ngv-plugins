---
description: Scan staged git changes for real (non-anonymized) IBKR account data, exec IDs, tokens, and trade timestamps. Prints offending lines so you can fix them or delegate the fix.
---

Review the currently staged changes for real Interactive Brokers data that should be anonymized before commit.

Procedure:

1. Run `git diff --cached --no-color` to get staged content. If nothing is staged, run `git diff --no-color` instead and note that you're scanning unstaged changes.
2. Apply the rules in the `ibkr-data-protection` skill to every added/modified line.
3. Print findings in the format documented in that skill (`path:line  <category>  <value>  → suggested`).
4. End with a summary count by category.
5. Ask the user whether to apply anonymizations — do not auto-edit.

If no suspicious values are found, say so explicitly.

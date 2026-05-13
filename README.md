# ngv-plugins

Claude Code marketplace for NGV quant development plugins.

## Install

```
/plugin marketplace add westonplatter/ngv-plugins
/plugin install ngv-quant-dev@ngv-plugins
```

Or for local development:

```
/plugin marketplace add /Users/weston/clients/westonplatter/ngv-plugins
/plugin install ngv-quant-dev@ngv-plugins
```

## Plugins

### ngv-quant-dev

Guardrails and helpers for NGV quant developers working with IBKR data.

- **Skill `ibkr-data-protection`** — auto-loads when reviewing staged IBKR-related changes. Detects real account IDs, exec IDs, tokens, and recent trade timestamps that should be anonymized per NGV conventions.
- **Command `/ngv-ibkr-check`** — explicit entry point. Runs the staged-diff scan and prints offending lines.

Review-on-demand only — does not block commits.

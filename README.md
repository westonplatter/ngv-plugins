# ngv-plugins

Claude Code marketplace for NGV (NextGenVol) plugins.

## Install

```
/plugin marketplace add westonplatter/ngv-plugins
/plugin install ngv-dev@ngv-plugins
```

Or for local development:

```
/plugin marketplace add /Users/weston/clients/westonplatter/ngv-plugins
/plugin install ngv-dev@ngv-plugins
```

## Plugins

### ngv-dev

NextGenVol agentic toolkit for quant development. Review-on-demand only — does not block commits.

**Skills** — auto-loaded by Claude when context matches.

<table>
  <thead>
    <tr><th>Name</th><th>What it does</th></tr>
  </thead>
  <tbody>
    <tr>
      <td><code>ngv-dev:ibkr-data-protection</code></td>
      <td>Auto-loads on staged IBKR-related changes. Flags real account IDs, exec IDs, tokens, and recent trade timestamps that should be anonymized.</td>
    </tr>
  </tbody>
</table>

**Commands** — user-invoked via slash command.

<table>
  <thead>
    <tr><th>Name</th><th>What it does</th></tr>
  </thead>
  <tbody>
    <tr>
      <td><code>/ngv-dev:ibkr-data-protection</code></td>
      <td>Manual entry point for the IBKR scan. Reads the staged diff and prints offending lines with suggested anonymized values.</td>
    </tr>
  </tbody>
</table>

## Evals

Local, zero-cost eval harness for NGV skills, run against a model served by
LM Studio via the Anthropic SDK. Currently covers `ibkr-data-protection`.

See [`evals/README.md`](./evals/README.md) for setup, prerequisites, and how
to add cases.

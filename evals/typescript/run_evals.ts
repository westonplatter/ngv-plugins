import { readFileSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import Anthropic from "@anthropic-ai/sdk";
import { TEST_CASES, type TestCase } from "./cases.ts";

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const DEFAULT_SKILL_PATH = resolve(
  SCRIPT_DIR,
  "..",
  "..",
  "plugins",
  "ngv-dev",
  "skills",
  "ibkr-data-protection",
  "SKILL.md",
);

const LM_STUDIO_URL = process.env.LM_STUDIO_URL ?? "http://localhost:1234";
const MODEL = process.env.LM_STUDIO_MODEL ?? "qwen3.5-9b@q4_k_s";
const SKILL_PATH = process.env.SKILL_PATH ?? DEFAULT_SKILL_PATH;

const USER_WRAPPER = (content: string) =>
  `/no_think Scan the following staged content for IBKR data leaks per the ` +
  `skill instructions. Treat it as the output of \`git diff --cached\` for a ` +
  `single file named sample.yaml. Report findings in the documented ` +
  `\`path:line  category  value  -> suggestion\` format, or state that ` +
  `nothing was found.\n\n<<<\n${content}\n>>>`;

const FINDING_LINE = /^\S+:\d+\s+(\S+)\s+/gm;

function loadSkill(): string {
  if (!existsSync(SKILL_PATH)) {
    console.error(`SKILL.md not found at ${SKILL_PATH}. Did you create the skill?`);
    process.exit(1);
  }
  return readFileSync(SKILL_PATH, "utf8");
}

function extractCategories(output: string): string[] {
  const cats: string[] = [];
  for (const m of output.matchAll(FINDING_LINE)) cats.push(m[1]);
  return cats;
}

function evaluateCase(c: TestCase, output: string): { ok: boolean; detail: string } {
  const categories = extractCategories(output);
  if (c.shouldFlag) {
    const missing = c.expectedCategories.filter((x) => !categories.includes(x));
    if (missing.length > 0) {
      return { ok: false, detail: `missing categories: ${JSON.stringify(missing)}; got: ${JSON.stringify(categories)}` };
    }
    return { ok: true, detail: `flagged: ${JSON.stringify(categories)}` };
  }
  if (categories.length > 0) {
    return { ok: false, detail: `expected no findings, got categories: ${JSON.stringify(categories)}` };
  }
  return { ok: true, detail: "no findings (correct)" };
}

async function main(): Promise<void> {
  const skillText = loadSkill();
  const client = new Anthropic({ baseURL: LM_STUDIO_URL, apiKey: "lm-studio" });

  let passed = 0;
  for (const c of TEST_CASES) {
    const resp = await client.messages.create({
      model: MODEL,
      max_tokens: 1024,
      system: skillText,
      messages: [{ role: "user", content: USER_WRAPPER(c.input) }],
    });
    const output = resp.content
      .filter((b): b is Anthropic.TextBlock => b.type === "text")
      .map((b) => b.text)
      .join("");

    const { ok, detail } = evaluateCase(c, output);
    const marker = ok ? "[PASS]" : "[FAIL]";
    console.log(`${marker} ${c.name}  (${detail})`);
    if (!ok) console.log(`       output: ${JSON.stringify(output.slice(0, 400))}`);
    if (ok) passed++;
  }

  const total = TEST_CASES.length;
  console.log(`\nResults: ${passed}/${total} passed`);
  process.exit(passed === total ? 0 : 1);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

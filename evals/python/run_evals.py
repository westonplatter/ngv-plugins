"""Local eval runner for the ibkr-data-protection skill against LM Studio.

Uses the Anthropic SDK pointed at LM Studio's Anthropic-compatible endpoint.
No calls to the real Anthropic API.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import anthropic

from cases import TEST_CASES

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SKILL_PATH = (
    SCRIPT_DIR.parent.parent
    / "plugins"
    / "ngv-dev"
    / "skills"
    / "ibkr-data-protection"
    / "SKILL.md"
)

LM_STUDIO_URL = os.environ.get("LM_STUDIO_URL", "http://localhost:1234")
MODEL = os.environ.get("LM_STUDIO_MODEL", "qwen3.5-9b@q4_k_s")
SKILL_PATH = Path(os.environ.get("SKILL_PATH", str(DEFAULT_SKILL_PATH)))

USER_WRAPPER = (
    "/no_think Scan the following staged content for IBKR data leaks per the "
    "skill instructions. Treat it as the output of `git diff --cached` for a "
    "single file named sample.yaml. Report findings in the documented "
    "`path:line  category  value  -> suggestion` format, or state that nothing "
    "was found.\n\n<<<\n{content}\n>>>"
)

FINDING_LINE = re.compile(r"^\S+:\d+\s+(\S+)\s+", re.MULTILINE)


def load_skill() -> str:
    if not SKILL_PATH.exists():
        sys.exit(f"SKILL.md not found at {SKILL_PATH}. Did you create the skill?")
    return SKILL_PATH.read_text()


def extract_categories(output: str) -> list[str]:
    return FINDING_LINE.findall(output)


def evaluate(case: dict, output: str) -> tuple[bool, str]:
    categories = extract_categories(output)
    if case["should_flag"]:
        missing = [c for c in case["expected_categories"] if c not in categories]
        if missing:
            return False, f"missing categories: {missing}; got: {categories}"
        return True, f"flagged: {categories}"
    if categories:
        return False, f"expected no findings, got categories: {categories}"
    return True, "no findings (correct)"


def main() -> int:
    skill_text = load_skill()
    client = anthropic.Anthropic(base_url=LM_STUDIO_URL, api_key="lm-studio")

    passed = 0
    for case in TEST_CASES:
        prompt = USER_WRAPPER.format(content=case["input"])
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=skill_text,
            messages=[{"role": "user", "content": prompt}],
        )
        output = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )
        ok, detail = evaluate(case, output)
        marker = "[PASS]" if ok else "[FAIL]"
        print(f"{marker} {case['name']}  ({detail})")
        if not ok:
            print(f"       output: {output[:400]!r}")
        if ok:
            passed += 1

    total = len(TEST_CASES)
    print(f"\nResults: {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())

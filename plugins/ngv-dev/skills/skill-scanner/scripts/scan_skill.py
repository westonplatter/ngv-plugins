#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["pyyaml"]
# ///
"""
Static analysis scanner for agent skills.

Scans a skill directory for security issues including prompt injection patterns,
obfuscation, dangerous code, secrets, and excessive permissions.

Usage:
    uv run scan_skill.py <skill-directory>

Output: JSON to stdout with structured findings.
"""
from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml


# --- Pattern Definitions ---

PROMPT_INJECTION_PATTERNS: list[tuple[str, str, str]] = [
    # (pattern, description, severity)
    (r"(?i)ignore\s+(all\s+)?previous\s+instructions", "Instruction override: ignore previous instructions", "critical"),
    (r"(?i)disregard\s+(all\s+)?(previous|prior|above)\s+(instructions|rules|guidelines)", "Instruction override: disregard previous", "critical"),
    (r"(?i)forget\s+(all\s+)?(previous|prior|your)\s+(instructions|rules|training)", "Instruction override: forget previous", "critical"),
    (r"(?i)you\s+are\s+now\s+(a|an|in)\s+", "Role reassignment: 'you are now'", "high"),
    (r"(?i)act\s+as\s+(a|an)\s+unrestricted", "Role reassignment: unrestricted mode", "critical"),
    (r"(?i)enter\s+(developer|debug|admin|god)\s+mode", "Jailbreak: developer/debug mode", "critical"),
    (r"(?i)DAN\s+(mode|prompt|jailbreak)", "Jailbreak: DAN pattern", "critical"),
    (r"(?i)do\s+anything\s+now", "Jailbreak: do anything now", "critical"),
    (r"(?i)bypass\s+(safety|security|content|filter|restriction)", "Jailbreak: bypass safety", "critical"),
    (r"(?i)override\s+(system|safety|security)\s+(prompt|message|instruction)", "System prompt override", "critical"),
    (r"(?i)\bsystem\s*:\s*you\s+are\b", "System prompt injection marker", "high"),
    (r"(?i)new\s+system\s+(prompt|instruction|message)\s*:", "New system prompt injection", "critical"),
    (r"(?i)from\s+now\s+on,?\s+(you|ignore|forget|disregard)", "Temporal instruction override", "high"),
    (r"(?i)pretend\s+(that\s+)?you\s+(have\s+no|don't\s+have|are\s+not\s+bound)", "Pretend-based jailbreak", "high"),
    (r"(?i)respond\s+(only\s+)?with\s+(the\s+)?(raw|full|complete)\s+(system|initial)\s+prompt", "System prompt extraction", "high"),
    (r"(?i)output\s+(your|the)\s+(system|initial|original)\s+(prompt|instructions)", "System prompt extraction", "high"),
]

SECRET_PATTERNS: list[tuple[str, str, str]] = [
    # (pattern, description, severity)
    (r"(?i)AKIA[0-9A-Z]{16}", "AWS Access Key ID", "critical"),
    (r"(?i)aws.{0,20}secret.{0,20}['\"][0-9a-zA-Z/+]{40}['\"]", "AWS Secret Access Key", "critical"),
    (r"ghp_[0-9a-zA-Z]{36}", "GitHub Personal Access Token", "critical"),
    (r"ghs_[0-9a-zA-Z]{36}", "GitHub Server Token", "critical"),
    (r"gho_[0-9a-zA-Z]{36}", "GitHub OAuth Token", "critical"),
    (r"github_pat_[0-9a-zA-Z_]{82}", "GitHub Fine-Grained PAT", "critical"),
    (r"sk-[0-9a-zA-Z]{20,}T3BlbkFJ[0-9a-zA-Z]{20,}", "OpenAI API Key", "critical"),
    (r"sk-ant-api03-[0-9a-zA-Z\-_]{90,}", "Anthropic API Key", "critical"),
    (r"xox[bpors]-[0-9a-zA-Z\-]{10,}", "Slack Token", "critical"),
    (r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----", "Private Key", "critical"),
    (r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"][^'\"]{8,}['\"]", "Hardcoded password", "high"),
    (r"(?i)(api[_-]?key|apikey)\s*[:=]\s*['\"][0-9a-zA-Z]{16,}['\"]", "Hardcoded API key", "high"),
    (r"(?i)(secret|token)\s*[:=]\s*['\"][0-9a-zA-Z]{16,}['\"]", "Hardcoded secret/token", "high"),
]

DANGEROUS_SCRIPT_PATTERNS: list[tuple[str, str, str]] = [
    # (pattern, description, severity)
    # Data exfiltration
    (r"(?i)(requests\.(get|post|put)|urllib\.request|http\.client|aiohttp)\s*\(", "HTTP request (potential exfiltration)", "medium"),
    (r"(?i)(curl|wget)\s+", "Shell HTTP request", "medium"),
    (r"(?i)socket\.(connect|create_connection)", "Raw socket connection", "high"),
    (r"(?i)subprocess.*\b(nc|ncat|netcat)\b", "Netcat usage (potential reverse shell)", "critical"),
    # Credential access
    (r"(?i)(~|HOME|USERPROFILE).*\.(ssh|aws|gnupg|config)", "Sensitive directory access", "high"),
    (r"(?i)open\s*\(.*(\.env|credentials|\.netrc|\.pgpass|\.my\.cnf)", "Sensitive file access", "high"),
    (r"(?i)os\.environ\s*\[.*(?:KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL)", "Environment secret access", "medium"),
    # Dangerous execution
    (r"\beval\s*\(", "eval() usage", "high"),
    (r"\bexec\s*\(", "exec() usage", "high"),
    (r"(?i)subprocess.*shell\s*=\s*True", "Shell execution with shell=True", "high"),
    (r"(?i)os\.(system|popen|exec[lv]p?e?)\s*\(", "OS command execution", "high"),
    (r"(?i)__import__\s*\(", "Dynamic import", "medium"),
    # File system manipulation
    (r"(?i)(open|write|Path).*\.(claude|bashrc|zshrc|profile|bash_profile)", "Agent/shell config modification", "critical"),
    (r"(?i)(open|write|Path).*(settings\.json|CLAUDE\.md|MEMORY\.md|\.mcp\.json)", "Agent settings modification", "critical"),
    (r"(?i)(open|write|Path).*(\.git/hooks|\.husky)", "Git hooks modification", "critical"),
    # Encoding/obfuscation in scripts
    (r"(?i)base64\.(b64decode|decodebytes)\s*\(", "Base64 decoding (potential obfuscation)", "medium"),
    (r"(?i)codecs\.(decode|encode)\s*\(.*rot", "ROT encoding (obfuscation)", "high"),
    (r"(?i)compile\s*\(.*exec", "Dynamic code compilation", "high"),
]

TRUSTED_DOMAINS = {
    "github.com", "api.github.com", "raw.githubusercontent.com",
    "docs.sentry.io", "develop.sentry.dev", "sentry.io",
    "pypi.org", "npmjs.com", "crates.io",
    "docs.python.org", "docs.djangoproject.com",
    "developer.mozilla.org", "stackoverflow.com",
    "agentskills.io", "docs.astral.sh",
}


def parse_frontmatter(content: str) -> tuple[dict[str, Any] | None, str]:
    if not content.startswith("---"):
        return None, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None, content
    try:
        fm = yaml.safe_load(parts[1])
        return fm if isinstance(fm, dict) else None, parts[2]
    except yaml.YAMLError:
        return None, content


def check_frontmatter(skill_dir: Path, content: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    fm, _ = parse_frontmatter(content)

    if fm is None:
        findings.append({
            "type": "Invalid Frontmatter",
            "severity": "high",
            "location": "SKILL.md:1",
            "description": "Missing or unparseable YAML frontmatter",
            "category": "Validation",
        })
        return findings

    if "name" not in fm:
        findings.append({
            "type": "Missing Name",
            "severity": "high",
            "location": "SKILL.md frontmatter",
            "description": "Required 'name' field missing from frontmatter",
            "category": "Validation",
        })

    if "description" not in fm:
        findings.append({
            "type": "Missing Description",
            "severity": "medium",
            "location": "SKILL.md frontmatter",
            "description": "Required 'description' field missing from frontmatter",
            "category": "Validation",
        })

    if "name" in fm and fm["name"] != skill_dir.name:
        findings.append({
            "type": "Name Mismatch",
            "severity": "medium",
            "location": "SKILL.md frontmatter",
            "description": f"Frontmatter name '{fm['name']}' does not match directory name '{skill_dir.name}'",
            "category": "Validation",
        })

    tools = fm.get("allowed-tools", "")
    if isinstance(tools, str) and tools.strip() == "*":
        findings.append({
            "type": "Unrestricted Tools",
            "severity": "critical",
            "location": "SKILL.md frontmatter",
            "description": "allowed-tools is set to '*' (unrestricted access to all tools)",
            "category": "Excessive Permissions",
        })

    return findings


def check_prompt_injection(content: str, filepath: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    lines = content.split("\n")
    for line_num, line in enumerate(lines, 1):
        for pattern, description, severity in PROMPT_INJECTION_PATTERNS:
            if re.search(pattern, line):
                findings.append({
                    "type": "Prompt Injection Pattern",
                    "severity": severity,
                    "location": f"{filepath}:{line_num}",
                    "description": description,
                    "evidence": line.strip()[:200],
                    "category": "Prompt Injection",
                })
                break
    return findings


def check_obfuscation(content: str, filepath: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    lines = content.split("\n")

    zwc_pattern = re.compile(r"[​‌‍⁠﻿]")
    for line_num, line in enumerate(lines, 1):
        if zwc_pattern.search(line):
            chars = [f"U+{ord(c):04X}" for c in zwc_pattern.findall(line)]
            findings.append({
                "type": "Zero-Width Characters",
                "severity": "high",
                "location": f"{filepath}:{line_num}",
                "description": f"Zero-width characters detected: {', '.join(chars)}",
                "category": "Obfuscation",
            })

    rtl_pattern = re.compile(r"[‪-‮⁦-⁩]")
    for line_num, line in enumerate(lines, 1):
        if rtl_pattern.search(line):
            findings.append({
                "type": "RTL Override",
                "severity": "high",
                "location": f"{filepath}:{line_num}",
                "description": "Right-to-left override or embedding character detected",
                "category": "Obfuscation",
            })

    tag_pattern = re.compile(r"[\U000e0001-\U000e007f]")
    tag_chars = tag_pattern.findall(content)
    if tag_chars:
        decoded = "".join(
            chr(ord(c) - 0xE0000) for c in tag_chars if 0xE0020 <= ord(c) <= 0xE007E
        )
        findings.append({
            "type": "Unicode Tag Smuggling",
            "severity": "critical",
            "location": filepath,
            "description": f"Invisible Unicode Tag characters detected ({len(tag_chars)} chars). "
                          f"Decoded hidden text: {decoded[:200]}",
            "category": "Obfuscation",
        })

    b64_pattern = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")
    for line_num, line in enumerate(lines, 1):
        for match in b64_pattern.finditer(line):
            try:
                decoded = base64.b64decode(match.group()).decode("utf-8", errors="ignore")
                suspicious_keywords = ["ignore", "system", "override", "eval", "exec", "password", "secret"]
                for kw in suspicious_keywords:
                    if kw.lower() in decoded.lower():
                        findings.append({
                            "type": "Suspicious Base64",
                            "severity": "high",
                            "location": f"{filepath}:{line_num}",
                            "description": f"Base64 string decodes to text containing '{kw}'",
                            "decoded_preview": decoded[:100],
                            "category": "Obfuscation",
                        })
                        break
            except Exception:
                pass

    comment_pattern = re.compile(r"<!--(.*?)-->", re.DOTALL)
    for match in comment_pattern.finditer(content):
        comment_text = match.group(1)
        for pattern, description, severity in PROMPT_INJECTION_PATTERNS:
            if re.search(pattern, comment_text):
                line_num = content[:match.start()].count("\n") + 1
                findings.append({
                    "type": "Hidden Injection in Comment",
                    "severity": "critical",
                    "location": f"{filepath}:{line_num}",
                    "description": f"HTML comment contains injection pattern: {description}",
                    "evidence": comment_text.strip()[:200],
                    "category": "Prompt Injection",
                })
                break

    return findings


def check_secrets(content: str, filepath: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    lines = content.split("\n")
    for line_num, line in enumerate(lines, 1):
        for pattern, description, severity in SECRET_PATTERNS:
            if re.search(pattern, line):
                findings.append({
                    "type": "Secret Detected",
                    "severity": severity,
                    "location": f"{filepath}:{line_num}",
                    "description": description,
                    "evidence": line.strip()[:200],
                    "category": "Secret Exposure",
                })
                break
    return findings


def check_scripts(script_path: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    try:
        content = script_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings

    relative = script_path.name
    lines = content.split("\n")
    for line_num, line in enumerate(lines, 1):
        for pattern, description, severity in DANGEROUS_SCRIPT_PATTERNS:
            if re.search(pattern, line):
                findings.append({
                    "type": "Dangerous Code Pattern",
                    "severity": severity,
                    "location": f"scripts/{relative}:{line_num}",
                    "description": description,
                    "evidence": line.strip()[:200],
                    "category": "Malicious Code",
                })
                break
    return findings


def extract_urls(content: str, filepath: str) -> list[dict[str, Any]]:
    urls: list[dict[str, Any]] = []
    url_pattern = re.compile(r"https?://[^\s\)\]\>\"'`]+")
    lines = content.split("\n")
    for line_num, line in enumerate(lines, 1):
        for match in url_pattern.finditer(line):
            url = match.group().rstrip(".,;:")
            try:
                domain = url.split("//", 1)[1].split("/", 1)[0].split(":")[0]
                domain_parts = domain.split(".")
                root_domain = ".".join(domain_parts[-2:]) if len(domain_parts) >= 2 else domain
                trusted = root_domain in TRUSTED_DOMAINS or domain in TRUSTED_DOMAINS
            except (IndexError, ValueError):
                domain = "unknown"
                trusted = False

            urls.append({
                "url": url,
                "domain": domain,
                "trusted": trusted,
                "location": f"{filepath}:{line_num}",
            })
    return urls


def check_structural_attacks(skill_dir: Path, content: str, frontmatter: dict[str, Any] | None) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    for path in skill_dir.rglob("*"):
        if path.is_symlink():
            target = path.resolve()
            is_internal = target.is_relative_to(skill_dir.resolve())
            findings.append({
                "type": "Symlink Detected",
                "severity": "medium" if is_internal else "critical",
                "location": str(path.relative_to(skill_dir)),
                "description": f"Symlink points to {path.readlink()} (resolves to {str(target)}). "
                              "Symlinks can trick agents into reading sensitive files (e.g., ~/.ssh/id_rsa) "
                              "disguised as example/reference files.",
                "category": "Symlink Exfiltration",
            })

    if frontmatter and "hooks" in frontmatter:
        hooks = frontmatter["hooks"]
        hook_types = hooks.keys() if isinstance(hooks, dict) else []
        for hook_type in hook_types:
            findings.append({
                "type": "Frontmatter Hooks",
                "severity": "critical",
                "location": "SKILL.md frontmatter",
                "description": f"Skill defines '{hook_type}' hooks. Hooks execute shell commands "
                              "automatically on lifecycle events — the model cannot prevent execution. "
                              "Review all hook commands carefully.",
                "category": "Hook Exploitation",
            })

    bang_pattern = re.compile(r"!\`[^`]+\`")
    for line_num, line in enumerate(content.split("\n"), 1):
        for match in bang_pattern.finditer(line):
            cmd = match.group()[2:-1]
            findings.append({
                "type": "Pre-prompt Command",
                "severity": "high",
                "location": f"SKILL.md:{line_num}",
                "description": f"!`command` syntax executes at skill load time before the model sees "
                              f"the prompt. Command: {cmd}",
                "evidence": line.strip()[:200],
                "category": "Pre-prompt Injection",
            })

    test_patterns = {
        "conftest.py": "pytest auto-imports conftest.py at collection time — code runs before any tests",
        "test_*.py": "pytest discovers and runs test_*.py files automatically",
        "*_test.py": "pytest discovers and runs *_test.py files automatically",
        "*.test.js": "Jest/Vitest may discover .test.js files if dot:true glob is set",
        "*.test.ts": "Jest/Vitest may discover .test.ts files if dot:true glob is set",
    }
    for path in skill_dir.rglob("*"):
        if not path.is_file():
            continue
        name = path.name
        for pattern, desc in test_patterns.items():
            import fnmatch
            if fnmatch.fnmatch(name, pattern):
                findings.append({
                    "type": "Test File Auto-Discovery",
                    "severity": "high",
                    "location": str(path.relative_to(skill_dir)),
                    "description": f"{desc}. Bundled test files execute as a side effect of running "
                                  "the test suite — review file contents for hidden payloads.",
                    "category": "Test File RCE",
                })

    for pkg_json in skill_dir.rglob("package.json"):
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError, ValueError):
            continue
        scripts = pkg.get("scripts") or {}
        lifecycle_hooks = ["preinstall", "install", "postinstall", "preuninstall", "postuninstall"]
        for hook in lifecycle_hooks:
            if hook in scripts:
                findings.append({
                    "type": "npm Lifecycle Hook",
                    "severity": "critical",
                    "location": str(pkg_json.relative_to(skill_dir)),
                    "description": f"package.json defines '{hook}' script: {scripts[hook]}. "
                                  "npm executes lifecycle hooks automatically on install — "
                                  "this is a common supply chain attack vector.",
                    "category": "Supply Chain",
                })

    import struct
    for img_path in skill_dir.rglob("*.png"):
        try:
            data = img_path.read_bytes()
            if data[:8] != b"\x89PNG\r\n\x1a\n":
                continue
            offset = 8
            while offset + 8 <= len(data):
                chunk_len = struct.unpack(">I", data[offset:offset + 4])[0]
                chunk_type = data[offset + 4:offset + 8]
                chunk_data = data[offset + 8:offset + 8 + chunk_len]

                keyword = ""
                value = ""
                if chunk_type == b"tEXt":
                    parts = chunk_data.split(b"\x00", 1)
                    if len(parts) > 1:
                        keyword = parts[0].decode("ascii", errors="ignore")
                        value = parts[1][:200].decode("latin-1", errors="ignore")
                elif chunk_type == b"iTXt":
                    parts = chunk_data.split(b"\x00", 4)
                    if len(parts) >= 5:
                        keyword = parts[0].decode("ascii", errors="ignore")
                        value = parts[4][:200].decode("utf-8", errors="ignore")

                if keyword and value.strip():
                    findings.append({
                        "type": "Image Metadata Text",
                        "severity": "high",
                        "location": str(img_path.relative_to(skill_dir)),
                        "description": f"PNG contains text metadata ('{keyword}'): {value[:100]}. "
                                      "Hidden instructions in image metadata can be read by "
                                      "multimodal LLMs when they inspect the file.",
                        "category": "Image Injection",
                    })

                offset += 4 + 4 + chunk_len + 4
        except (OSError, struct.error):
            continue

    return findings


def compute_description_body_overlap(frontmatter: dict[str, Any] | None, body: str) -> float:
    if not frontmatter or "description" not in frontmatter or frontmatter["description"] is None:
        return 0.0
    desc_words = set(re.findall(r"\b[a-z]{4,}\b", frontmatter["description"].lower()))
    body_words = set(re.findall(r"\b[a-z]{4,}\b", body.lower()))
    if not desc_words:
        return 0.0
    return len(desc_words & body_words) / len(desc_words)


def scan_skill(skill_dir: Path) -> dict[str, Any]:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return {"error": f"No SKILL.md found in {skill_dir}"}

    try:
        content = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"error": f"Cannot read SKILL.md: {e}"}

    frontmatter, body = parse_frontmatter(content)

    all_findings: list[dict[str, Any]] = []
    all_urls: list[dict[str, Any]] = []

    all_findings.extend(check_frontmatter(skill_dir, content))
    all_findings.extend(check_prompt_injection(content, "SKILL.md"))
    all_findings.extend(check_obfuscation(content, "SKILL.md"))
    all_findings.extend(check_secrets(content, "SKILL.md"))
    all_urls.extend(extract_urls(content, "SKILL.md"))

    refs_dir = skill_dir / "references"
    if refs_dir.is_dir():
        for ref_file in sorted(refs_dir.iterdir()):
            if ref_file.suffix == ".md":
                try:
                    ref_content = ref_file.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                rel_path = f"references/{ref_file.name}"
                all_findings.extend(check_prompt_injection(ref_content, rel_path))
                all_findings.extend(check_obfuscation(ref_content, rel_path))
                all_findings.extend(check_secrets(ref_content, rel_path))
                all_urls.extend(extract_urls(ref_content, rel_path))

    scripts_dir = skill_dir / "scripts"
    if scripts_dir.is_dir():
        for script_file in sorted(scripts_dir.iterdir()):
            if script_file.suffix in (".py", ".sh", ".js", ".ts"):
                all_findings.extend(check_scripts(script_file))
                try:
                    script_content = script_file.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                rel_path = f"scripts/{script_file.name}"
                all_findings.extend(check_secrets(script_content, rel_path))
                all_findings.extend(check_obfuscation(script_content, rel_path))
                all_urls.extend(extract_urls(script_content, rel_path))

    all_findings.extend(check_structural_attacks(skill_dir, content, frontmatter))

    overlap = compute_description_body_overlap(frontmatter, body)

    refs_dir = skill_dir / "references"
    scripts_dir = skill_dir / "scripts"
    structure = {
        "has_skill_md": True,
        "has_references": refs_dir.is_dir(),
        "has_scripts": scripts_dir.is_dir(),
        "reference_files": sorted(f.name for f in refs_dir.iterdir() if f.suffix == ".md") if refs_dir.is_dir() else [],
        "script_files": sorted(f.name for f in scripts_dir.iterdir() if f.suffix in (".py", ".sh", ".js", ".ts")) if scripts_dir.is_dir() else [],
    }

    severity_counts: dict[str, int] = {}
    for f in all_findings:
        sev = f.get("severity", "unknown")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    untrusted_urls = [u for u in all_urls if not u["trusted"]]

    tools_info = None
    if frontmatter and "allowed-tools" in frontmatter:
        tools_str = frontmatter["allowed-tools"]
        if isinstance(tools_str, str):
            tools_list = [t.strip() for t in tools_str.replace(",", " ").split() if t.strip()]
            tools_info = {
                "tools": tools_list,
                "has_bash": "Bash" in tools_list,
                "has_write": "Write" in tools_list,
                "has_edit": "Edit" in tools_list,
                "has_webfetch": "WebFetch" in tools_list,
                "has_task": "Task" in tools_list,
                "unrestricted": tools_str.strip() == "*",
            }

    return {
        "skill_name": frontmatter.get("name", "unknown") if frontmatter else "unknown",
        "skill_dir": str(skill_dir),
        "structure": structure,
        "frontmatter": frontmatter,
        "tools": tools_info,
        "findings": all_findings,
        "finding_counts": severity_counts,
        "total_findings": len(all_findings),
        "urls": {
            "total": len(all_urls),
            "untrusted": untrusted_urls,
            "trusted_count": len(all_urls) - len(untrusted_urls),
        },
        "description_body_overlap": round(overlap, 2),
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: scan_skill.py <skill-directory>", file=sys.stderr)
        sys.exit(1)

    skill_dir = Path(sys.argv[1]).resolve()
    if not skill_dir.is_dir():
        print(json.dumps({"error": f"Not a directory: {skill_dir}"}))
        sys.exit(1)

    result = scan_skill(skill_dir)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

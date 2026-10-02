# SKILL.md Specification & Best Practices Guide

## 1. The Anatomy of a SKILL.md

The `SKILL.md` format standardizes how domain knowledge, operational runbooks, and workflow procedures are exposed to LLM agents.

### The 3 Levels of Progressive Disclosure

```text
Level 1: System Catalog (Frontmatter)
   │  • ~100 tokens
   │  • Loaded on startup into agent system prompt
   │  • Used by LLM routing engine to select the skill
   ▼
Level 2: Main Playbook (SKILL.md Body)
   │  • ~500 - 1500 tokens
   │  • Injected into context only when activated
   │  • Step-by-step instructions, workflows, gotchas
   ▼
Level 3: Deep Execution (Subdirectories)
      • Loaded selectively via tool calls (read_file / view_file / bash)
      • references/ (bulky manuals, API schemas)
      • scripts/ (reproducible deterministic logic)
      • assets/ (templates, mock data, configuration skeletons)
```

---

## 2. YAML Frontmatter Specification

Every `SKILL.md` **must** begin with a YAML frontmatter block:

```yaml
---
name: string               # Required: lowercase, hyphenated unique ID (e.g. data-migration-helper)
description: string        # Required: Detailed third-person explanation of what & when to trigger
tags: list[string]         # Optional: Categorization tags
license: string            # Optional: e.g. MIT, Apache-2.0
compatibility: string      # Optional: Environment constraints (e.g. "Requires Docker and Python 3.11+")
allowed-tools: list[string]# Optional: Tools permitted for this skill
metadata:                  # Optional: Versioning and author info
  author: string
  version: string
  last-updated: string
---
```

### Writing the Perfect `description`
The `description` field is the single most critical element for routing accuracy.
- **Include specific trigger phrases**: e.g., `"Use when the user asks to debug Kafka consumers, replay DLQ messages, or tune partitions..."`
- **Include negative constraints**: e.g., `"Do NOT use for general database migrations or non-Kafka message brokers."`
- **Avoid vague summaries**: Do not write `"A helper tool for Kafka"`. Write exactly what scenarios warrant its use.

---

## 3. Directory Layout Rules

```text
skills/<skill-name>/
├── SKILL.md
├── references/
│   ├── api-reference.md
│   └── troubleshooting.md
├── scripts/
│   ├── validate.py
│   └── run_pipeline.sh
└── assets/
    ├── template.json
    └── example_config.yaml
```

- **References**: Markdown files containing API endpoints, full schemas, migration steps, and edge-case documentation. Link them in `SKILL.md` using relative paths: `[Troubleshooting](references/troubleshooting.md)`.
- **Scripts**: Executable scripts (Python, Bash, Node) that automate deterministic multi-step operations (e.g., parsing, linting, formatting).
- **Assets**: Static templates and boilerplate configuration files that the agent can read and adapt.

---

## 4. Quality Guardrails Checklist for Skills

- [ ] `name` is unique, lowercase, and uses hyphens.
- [ ] `description` clearly specifies both **what** it does and **when** it triggers.
- [ ] No monolithic text: large code blocks or extensive manuals are split into `references/`.
- [ ] Verification steps are explicit (how to test/confirm correctness).
- [ ] Relative file links use standard markdown syntax.

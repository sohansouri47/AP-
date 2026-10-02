---
name: deep-agents
description: >-
  Architect, build, and operate Deep Agents and standard-compliant SKILL.md packages.
  Use this skill when designing autonomous AI agents, multi-step workflows, planning systems,
  subagent hierarchies, filesystem-backed agent memory, or when creating, optimizing, or
  structuring SKILL.md skills and agent playbooks according to the Agent Skills specification.
  Triggers include: 'deep agents', 'deep agent', 'skill.md', 'agent skills', 'subagent delegation',
  'hierarchical agents', 'agent planning', 'progressive disclosure', 'agent scratchpad'.
tags: [agents, deep-agents, skill-md, langgraph, architecture, autonomous]
---

# Deep Agents & SKILL.md Mastery Skill

This skill provides comprehensive instructions, architectural patterns, and practical guidelines for building **Deep Agents** (autonomous, long-horizon, memory-rich agents) and creating standardized **`SKILL.md`** skill packages.

---

## 1. Core Architecture of Deep Agents

Deep Agents move beyond simple single-turn tool calls to execute complex, multi-step, autonomous tasks through four primary layers:

```text
┌─────────────────────────────────────────────────────────────┐
│                       IDENTITY LAYER                        │
│   • SKILL.md Packages (Domain Expertise & Procedures)       │
│   • Constraints & Safety Guardrails                         │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                    ORCHESTRATION LAYER                      │
│   • Dynamic System Prompt (Skill Catalog / Level 1 Meta)    │
│   • Planner & State Machine (Milestones, Task Tracking)     │
│   • Thought-Action-Reflection Loop                          │
│   • Subagent Delegation Manager                             │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                      CAPABILITY LAYER                       │
│   • MCP (Model Context Protocol) Servers                    │
│   • Scratchpad / Filesystem State Persistence               │
│   • Custom Python/API Tools                                 │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                     EXTERNAL ENVIRONMENT                    │
│   • Codebases, Databases, APIs, Terminals, Web Endpoints    │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Five Pillars of Deep Agent Design

When implementing or operating Deep Agents (e.g. via LangChain Deep Agents, LangGraph, or Antigravity agents):

### 1. Milestone Planning & Task Decomposition
- **Decompose before acting**: Always break complex prompts into discrete, verifiable phases.
- **Explicit Plan Updates**: Maintain a dynamic plan/checklist and mark items complete as evidence is obtained.

### 2. Filesystem / Scratchpad State Persistence
- Avoid holding massive intermediate state in LLM token context.
- Offload drafting, logs, temporary datasets, and large schemas to files in a designated scratchpad directory.
- Re-read only specific line ranges or summary slices on demand.

### 3. Subagent Spawning & Delegation
- Isolate distinct subtasks into focused child agents (e.g., research, coding, validation).
- Provide the subagent with a concise prompt, clear stop condition, and expected return schema.
- Keep the parent context clean by receiving high-level summaries from subagents.

### 4. Progressive Disclosure (The 3-Level Rule)
- **Level 1 (Discovery)**: Frontmatter (name + description + triggers) loaded at startup (~100 tokens).
- **Level 2 (Activation)**: Main `SKILL.md` body loaded only when relevant to the task.
- **Level 3 (Execution)**: Bulky reference docs (`references/`), scripts (`scripts/`), and templates (`assets/`) loaded on-demand.

### 5. Self-Reflection and Quality Gate Verification
- Before declaring a task finished, execute a verification pass (linting, tests, schema checks, dry-run).
- Never report completion without tangible verification output.

---

## 3. Creating Standard `SKILL.md` Packages

When creating new skills or converting agent workflows into reusable skills, adhere to this structure:

```text
skills/<skill-name>/
├── SKILL.md              # Mandatory: Frontmatter + core playbook
├── references/           # Optional: In-depth technical docs, API schemas, guides
├── scripts/              # Optional: Deterministic helper scripts (Python, Bash, JS)
└── assets/               # Optional: Static templates, boilerplate configs, examples
```

### Frontmatter Standard Schema

```yaml
---
name: your-skill-name
description: >-
  Third-person description of what the skill does AND when the agent should trigger it.
  Include positive triggers (e.g., keywords, task types) and explicit negative boundaries
  (e.g., "Do NOT use for...").
tags: [tag1, tag2]
compatibility: "Python 3.10+, uv, Node 18+" # Optional requirements
---
```

### Main Body (`SKILL.md`) Rules
1. **Be Imperative & Actionable**: Provide step-by-step instructions with clear preconditions.
2. **Link to References**: Do not dump 1000 lines of documentation in `SKILL.md`. Use relative markdown links: `[API Details](references/api.md)`.
3. **Encapsulate Code in Scripts**: For repetitive multi-step terminal tasks, write helper scripts in `scripts/` instead of asking the LLM to hallucinate complex one-liners.
4. **Define Verification Steps**: State explicitly how the agent confirms each step succeeded.

---

## 4. References & Guides

- [SKILL.md Architecture & Spec Guide](references/skill-md-spec.md)
- [Deep Agent Implementation Patterns (LangChain/LangGraph)](references/deep-agent-patterns.md)
- [Standard Skill Template](assets/skill-template.md)

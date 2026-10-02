# Deep Agent Implementation Patterns

## 1. Overview of Deep Agents

A **Deep Agent** is an autonomous agent architecture designed to solve complex, non-trivial, multi-phase problems without derailing or losing context. It combines planning, externalized state/memory, subagent delegation, and reflection loops.

---

## 2. Core Patterns

### Pattern A: Plan-and-Execute with Dynamic Re-planning
1. **Initial Milestone Breakdown**: The agent creates an explicit task list or artifact representing the stages of the task.
2. **Step Execution**: The agent executes actions for the current milestone.
3. **Observation & Reflection**: The agent inspects tool results against the expected state.
4. **Plan Adaptation**: If obstacles arise or new information is discovered, the agent updates the remaining steps before continuing.

### Pattern B: Filesystem-Backed Scratchpad
- **Context Window Management**: LLM context windows are precious and prone to degradation when polluted with massive tool outputs.
- **Offloading**: When tool outputs (search dumps, API responses, large code files) exceed ~50 lines, save them to a `scratch/` file on disk.
- **Selective Retrieval**: Use grep or slice reading (`StartLine`/`EndLine`) to inspect only the required segments.

### Pattern C: Hierarchical Multi-Agent Teams (Supervisor + Subagents)
```text
                  ┌──────────────────────┐
                  │   Supervisor Agent   │
                  │  (Coordinates Plan)  │
                  └──────────┬───────────┘
                             │
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ Research Agent  │ │  Coding Agent   │ │ Validation Agent│
│  (Exploration)  │ │ (Implementation)│ │ (Tests & Audit) │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```
- **Supervisor**: Manages the overarching goal, synthesizes results, communicates with user.
- **Subagents**: Short-lived, focused context, isolated scratchpads, return structured summaries.

### Pattern D: LangGraph Deep Agents Framework
In Python with LangGraph / LangChain:
```python
from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Annotated, List
import operator

class DeepAgentState(TypedDict):
    plan: List[str]
    current_step: int
    scratchpad_path: str
    results: Annotated[List[dict], operator.add]
    final_output: str

# Define nodes: planner -> executor -> evaluator -> dynamic route
```

---

## 3. Best Practices for Deep Execution
1. **Always Verify**: Run tests, type checks, or linters before concluding.
2. **Never Assume File Integrity**: After writing or modifying files, view the modified lines or run a syntax check.
3. **Idempotent Operations**: Design tools and helper scripts to be safe when re-run.

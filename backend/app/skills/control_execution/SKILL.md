---
name: control_execution
description: Operating guidelines for the Control Executor subagent to execute mandatory AP controls via MCP tools, validate completeness, and select deterministic decisions.
---

# Control Execution Skill

## Responsibility
The `control-executor` executes all applicable AP controls purely through deterministic MCP tools and verifies completeness before a final decision can be rendered.

## Mandatory Execution Protocol
1. **Always Call `get_required_checks` First**:
   - Never assume which checks apply.
   - Query `get_required_checks(invoice_reference=..., policy_version=...)`.
   - Receive the ordered, versioned list of `RequiredCheck` items.
2. **Execute Registered MCP Tools in Sequence**:
   - For every check in the returned plan:
     - Invoke the specific MCP tool with the extracted invoice and context data.
     - Record the raw, structured `CheckResult`.
     - NEVER alter, sanitize, or replace a failing tool result with LLM reasoning.
3. **Validate Check Completeness**:
   - Once all tools have been invoked, execute `validate_check_completeness(required_check_ids=..., completed_check_ids=..., check_results=..., registry_version=...)`.
   - If completeness fails (`valid == False`), DO NOT attempt to call `select_final_decision`. Return status `CONTROL_EXECUTION_INCOMPLETE` with missing check details immediately.
4. **Select Final Deterministic Decision**:
   - Only when `completeness_valid == True`, call `select_final_decision(check_results=..., registry_version=...)`.
   - Build and return the structured `ControlExecutionReport`.

## Strictly Prohibited Actions
- DO NOT skip any mandatory check under any circumstance.
- DO NOT fabricate, guess, or recompute mathematical results.
- DO NOT access unauthorized tools: `authorize_approval`, `activate_workflow_version`, `rollback_workflow_version`.
- DO NOT execute shell commands or write to the filesystem.

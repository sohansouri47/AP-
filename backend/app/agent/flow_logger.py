"""Terminal Flow Logger with clear Agent, Subagent, and Tool identification.

Outputs structured, colorized logs so developers can see the complete
step-by-step lifecycle of invoice processing and workflow improvement.
"""

from __future__ import annotations

import os
import sys
import logging
from typing import Any

# Color codes for ANSI terminal output (disabled if not a TTY or NO_COLOR set)
USE_COLOR = sys.stdout.isatty() and not os.getenv("NO_COLOR")

RESET = "\033[0m" if USE_COLOR else ""
BOLD = "\033[1m" if USE_COLOR else ""
DIM = "\033[2m" if USE_COLOR else ""

CYAN = "\033[36m" if USE_COLOR else ""
MAGENTA = "\033[35m" if USE_COLOR else ""
BLUE = "\033[34m" if USE_COLOR else ""
GREEN = "\033[32m" if USE_COLOR else ""
YELLOW = "\033[33m" if USE_COLOR else ""
RED = "\033[31m" if USE_COLOR else ""

logger = logging.getLogger("ap_agent.flow")


class FlowLogger:
    """Provides formatted, real-time logging across agents, subagents, and tools."""

    @staticmethod
    def node_start(graph_name: str, node_name: str, stage: str, run_id: str) -> None:
        msg = f"{BOLD}{BLUE}[Graph: {graph_name}]{RESET} Node: {BOLD}{node_name}{RESET} | Stage: {stage} | RunID: {run_id}"
        print(msg)
        logger.info("[Graph: %s] Node: %s | Stage: %s | RunID: %s", graph_name, node_name, stage, run_id)

    @staticmethod
    def node_end(graph_name: str, node_name: str, status: str, next_step: str = "") -> None:
        arrow = f" -> Next: {next_step}" if next_step else ""
        msg = f"{BOLD}{BLUE}[Graph: {graph_name}]{RESET} Node {node_name} completed | Status: {GREEN}{status}{RESET}{arrow}"
        print(msg)
        logger.info("[Graph: %s] Node %s completed | Status: %s%s", graph_name, node_name, status, arrow)

    @staticmethod
    def agent_start(agent_name: str, method_name: str, details: str = "") -> None:
        detail_str = f" | {details}" if details else ""
        msg = f"{BOLD}{CYAN}[Agent: {agent_name}]{RESET} Method: {BOLD}{method_name}{RESET}{detail_str}"
        print(msg)
        logger.info("[Agent: %s] Method: %s%s", agent_name, method_name, detail_str)

    @staticmethod
    def subagent_start(subagent_name: str, method_name: str, task: str = "") -> None:
        task_str = f" | Task: {task}" if task else ""
        msg = f"{BOLD}{MAGENTA}[Subagent: {subagent_name}]{RESET} Method: {BOLD}{method_name}{RESET}{task_str}"
        print(msg)
        logger.info("[Subagent: %s] Method: %s%s", subagent_name, method_name, task_str)

    @staticmethod
    def subagent_end(subagent_name: str, status: str, summary: str = "") -> None:
        status_color = GREEN if "PASS" in status or "SUCCESS" in status or "RESOLVED" in status else YELLOW
        msg = f"{BOLD}{MAGENTA}[Subagent: {subagent_name}]{RESET} Finished | Status: {status_color}{status}{RESET} | {summary}"
        print(msg)
        logger.info("[Subagent: %s] Finished | Status: %s | %s", subagent_name, status, summary)

    @staticmethod
    def tool_call(
        caller: str,
        tool_name: str,
        status: str,
        details: str = "",
        duration_ms: float = 0.0,
    ) -> None:
        caller_tag = f"{DIM}(caller: {caller}){RESET} " if caller else ""
        status_color = GREEN if status == "PASSED" or status == "SUCCESS" else (YELLOW if status == "REQUIRES_INPUT" else RED)
        timing = f" {DIM}({duration_ms:.1f}ms){RESET}" if duration_ms > 0 else ""
        msg = f"  ├── {BOLD}{BLUE}[Tool: {tool_name}]{RESET} {caller_tag}Status: {status_color}{status}{RESET} | {details}{timing}"
        print(msg)
        logger.info("[Tool: %s] (caller: %s) Status: %s | %s", tool_name, caller, status, details)

    @staticmethod
    def gate(gate_name: str, status: str, details: str = "") -> None:
        color = GREEN if "PASS" in status or "VALID" in status or "APPROVE" in status else RED
        msg = f"{BOLD}{YELLOW}[Gate: {gate_name}]{RESET} Result: {color}{status}{RESET} | {details}"
        print(msg)
        logger.info("[Gate: %s] Result: %s | %s", gate_name, status, details)

    @staticmethod
    def interrupt(interrupt_type: str, role: str, question: str = "", allowed_actions: list[str] | None = None) -> None:
        actions = f" | Actions: {allowed_actions}" if allowed_actions else ""
        q_str = f" | Reason: '{question}'" if question else ""
        msg = (
            f"\n{BOLD}{YELLOW}⏸ [Interrupt: HumanGate]{RESET} Type: {BOLD}{interrupt_type}{RESET} "
            f"| Required Role: {CYAN}{role}{RESET}{q_str}{actions}\n"
        )
        print(msg)
        logger.info("[Interrupt: HumanGate] Type: %s | Role: %s | Question: %s", interrupt_type, role, question)

    @staticmethod
    def resume(user_id: str, role: str, action: str, revision: int = 1) -> None:
        msg = (
            f"\n{BOLD}{GREEN}▶ [Resume: HumanAction]{RESET} User: {user_id} | Role: {role} "
            f"| Action: {BOLD}{action}{RESET} (Decision Revision: {revision})\n"
        )
        print(msg)
        logger.info("[Resume: HumanAction] User: %s | Role: %s | Action: %s", user_id, role, action)

    @staticmethod
    def outcome(status: str, owner: str, explanation: str) -> None:
        color = GREEN if status == "READY_FOR_APPROVAL" or status == "APPROVED" else (YELLOW if status == "NEEDS_ATTENTION" else RED)
        msg = (
            f"{BOLD}{CYAN}[Outcome: AP Employee]{RESET} Status: {color}{status}{RESET} "
            f"| Owner: {BOLD}{owner}{RESET}\n"
            f"  └── Summary: {explanation}"
        )
        print(msg)
        logger.info("[Outcome: AP Employee] Status: %s | Owner: %s | Summary: %s", status, owner, explanation)


flow_logger = FlowLogger()

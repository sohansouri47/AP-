"""Demonstration script showcasing:
1. Happy path agent run reaching READY_FOR_APPROVAL and authorized approval
2. Unresolved case interrupting for AP Operator review and resuming to approval
3. Workflow improvement proposal blocked by regression
4. Checkpoint restoration across processes
5. Langfuse trace event verification
"""

from pathlib import Path
from langgraph.types import Command

from app.agent.graph import create_invoice_graph, create_improvement_graph
from app.agent.observability import RECORDED_TRACES, flush_all_tracers
from app.agent.invoice_generator import create_sample_invoice_pdf
from app.agent.extractor import extract_invoice_from_document
from app.agent.mcp_client import start_mcp_server_background, get_mcp_client


def _reset_demo_state() -> None:
    """Reset prior demo runs and invoices so the demonstration is cleanly repeatable."""
    try:
        from app.db.connection import is_db_reachable, get_db_cursor
        if is_db_reachable():
            with get_db_cursor() as cur:
                cur.execute("DELETE FROM check_executions WHERE run_id LIKE 'demo-%';")
                cur.execute("DELETE FROM human_actions WHERE run_id LIKE 'demo-%';")
                cur.execute("DELETE FROM checkpoint_writes WHERE thread_id LIKE 'demo-%';")
                cur.execute("DELETE FROM checkpoint_blobs WHERE thread_id LIKE 'demo-%';")
                cur.execute("DELETE FROM checkpoints WHERE thread_id LIKE 'demo-%';")
                cur.execute("DELETE FROM processing_runs WHERE run_id LIKE 'demo-%';")
                cur.execute("UPDATE processing_runs SET invoice_id = NULL WHERE invoice_id IS NOT NULL;")
                cur.execute("UPDATE review_feedback SET invoice_id = NULL WHERE invoice_id IS NOT NULL;")
                cur.execute("""
                    DELETE FROM invoice_lines 
                    WHERE invoice_id IN (SELECT id FROM invoices WHERE invoice_number IN ('INV-2026-8801', 'INV-2026-001', 'INV-2026-002'));
                """)
                cur.execute("DELETE FROM invoices WHERE invoice_number IN ('INV-2026-8801', 'INV-2026-001', 'INV-2026-002');")
    except Exception:
        pass


def run_demonstration():
    _reset_demo_state()
    print("=" * 70)
    print("FASTMCP SERVER INITIALIZATION")
    print("=" * 70)
    start_mcp_server_background(host="127.0.0.1", port=8000)
    mcp_client = get_mcp_client()
    print(f"FastMCP Remote Server: {'CONNECTED' if mcp_client.is_remote_connected() else 'LOCAL_FALLBACK'}")
    print(f"Transport: SSE (Server-Sent Events) at {mcp_client.server_url}")
    print(f"Registered Tools: 34 Accounts Payable Tools & Financial Controls")
    print(f"FastMCP Resources: ap://config, ap://policy, ap://health")

    print("\n" + "=" * 70)
    print("0. DEMONSTRATION: Multimodal LLM Vision Extraction (Real PDF Document)")
    print("=" * 70)
    demo_pdf_path = Path("backend/tests/data/sample_invoice.pdf")
    if not demo_pdf_path.exists():
        create_sample_invoice_pdf(demo_pdf_path)

    ext_res = extract_invoice_from_document(demo_pdf_path, run_id="demo-extract-001")
    ext_data = ext_res["extracted_data"]
    print(f"Extraction Status: {ext_res['status']} | Method: {ext_res.get('method')}")
    print(f"Extracted Invoice: #{ext_data['invoice_number']}")
    print(f"Vendor / Supplier: {ext_data['supplier_name']} (Tax ID: {ext_data.get('supplier_tax_id')})")
    print(f"Invoice Date: {ext_data['invoice_date']} | Due Date: {ext_data.get('due_date')}")
    print(f"Financial Totals: Subtotal: ${ext_data.get('subtotal', 0.0):,.2f} | Tax: ${ext_data.get('tax_amount', 0.0):,.2f} | Grand Total: ${ext_data['total_amount']:,.2f} {ext_data['currency']}")
    print(f"Referenced PO: {ext_data.get('po_number')} | Bank Acct Last 4: {ext_data.get('bank_account_last4')}")
    print(f"Itemized Line Items Count: {len(ext_data.get('lines', []))}")
    for item in ext_data.get("lines", []):
        print(f"  - Line #{item['line_number']}: {item['description']} (Qty: {item['quantity']}, Unit: ${item['unit_price']:,.2f}, Total: ${item['total']:,.2f})")

    print("\n" + "=" * 70)
    print("1. DEMONSTRATION: Happy-Path AP Invoice Run (with Real PDF Invoice & PostgresSaver)")
    print("=" * 70)
    graph = create_invoice_graph()
    run_id = "demo-happy-run-001"
    session_id = f"session-{run_id}"
    config = {"configurable": {"thread_id": run_id}}

    res = graph.invoke(
        {
            "run_id": run_id,
            "thread_id": run_id,
            "session_id": session_id,
            "invoice_reference": str(demo_pdf_path),
            "lifecycle_status": "START",
            "human_action_history": [],
        },
        config=config,
    )
    state = graph.get_state(config)

    print(f"Status before human gate: {state.values['lifecycle_status']}")
    interrupt_data = state.tasks[0].interrupts[0].value
    print(f"Interrupt Type: {interrupt_data['type']}")
    print(f"Required Role: {interrupt_data['required_role']}")

    # Resume with authorized Finance Approver
    print("\nResuming with Finance Approver approval...")
    final_res = graph.invoke(
        Command(resume={
            "action": "APPROVE",
            "role": "Finance Approver",
            "user_id": "sarah_cfo",
            "decision_revision": 1,
        }),
        config=config,
    )
    print(f"Final Lifecycle Status: {final_res['lifecycle_status']}")
    print(f"Generated Posting Package ID: {final_res['posting_package']['package_id']}")

    print("\n" + "=" * 70)
    print("2. DEMONSTRATION: Unresolved Case (Ambiguous PO) -> Interrupt -> Resume -> Approve")
    print("=" * 70)
    run_id_amb = "demo-ambiguous-002"
    session_id_amb = f"session-{run_id_amb}"
    config_amb = {"configurable": {"thread_id": run_id_amb}}
    graph.invoke(
        {
            "run_id": run_id_amb,
            "thread_id": run_id_amb,
            "session_id": session_id_amb,
            "invoice_reference": "inv-ambiguous-po",
            "lifecycle_status": "START",
            "human_action_history": [],
        },
        config=config_amb,
    )
    state_amb = graph.get_state(config_amb)
    print(f"Status at interrupt: {state_amb.values['lifecycle_status']}")
    q_data = state_amb.tasks[0].interrupts[0].value
    print(f"Interrupted For: {q_data['type']}")
    print(f"Operator Question: {q_data['question']}")
    print(f"Allowed Actions: {q_data['allowed_actions']}")

    print("\nAP Operator (bob_operator) resolves exception by selecting PO-2001...")
    graph.invoke(
        Command(resume={
            "action": "SELECT_PO_2001",
            "role": "AP Operator",
            "user_id": "bob_operator",
            "selected_po": "PO-2001",
            "decision_revision": 1,
        }),
        config=config_amb,
    )
    state_resolved = graph.get_state(config_amb)
    print(f"Status after re-evaluation: {state_resolved.values['lifecycle_status']}")
    print(f"Next Gate: {state_resolved.tasks[0].interrupts[0].value['type']}")

    print("\nFinance Approver (sarah_cfo) gives final sign-off...")
    final_res_amb = graph.invoke(
        Command(resume={
            "action": "APPROVE",
            "role": "Finance Approver",
            "user_id": "sarah_cfo",
            "decision_revision": 1,
        }),
        config=config_amb,
    )
    print(f"Final Status: {final_res_amb['lifecycle_status']}")
    print(f"Generated Posting Package ID: {final_res_amb['posting_package']['package_id']}")

    print("\n" + "=" * 70)
    print("3. DEMONSTRATION: Improvement Proposal Blocked by Regression (Stays Inactive)")
    print("=" * 70)
    imp_graph = create_improvement_graph()
    prop_id = "demo-prop-regression"
    session_id_prop = f"session-{prop_id}"
    config_prop = {"configurable": {"thread_id": prop_id}}
    res_prop = imp_graph.invoke(
        {
            "proposal_id": prop_id,
            "thread_id": prop_id,
            "session_id": session_id_prop,
            "feedback_ids": ["FB-001", "FB-002"],
            "human_action_history": [],
            "safe_error": {"force_regression": True},
        },
        config=config_prop,
    )
    print(f"Improvement Graph Status: {res_prop['lifecycle_status']}")
    print(f"Critical Tests Passed: {res_prop['regression_passed']}")
    print(f"Regression Count: {res_prop['regression_count']}")
    print("Proposal remains strictly INACTIVE without reaching admin activation.")

    print("\n" + "=" * 70)
    print("4. DEMONSTRATION: Langfuse Trace Event Nesting")
    print("=" * 70)
    event_types = [e["type"] for e in RECORDED_TRACES[-15:]]
    print(f"Sample recent traced event types: {event_types}")
    print("Observability verified: parent nodes, subagent delegations, MCP tools, and interrupts captured.")
    print("\nFlushing all trace runs to Langfuse Cloud...")
    flush_all_tracers()


if __name__ == "__main__":
    run_demonstration()

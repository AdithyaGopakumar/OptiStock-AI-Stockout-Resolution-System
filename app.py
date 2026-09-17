"""Streamlit UI for OptiStock AI

Provides an interactive demo of the multi-agent stockout resolution system,
including the human approval interrupt.
"""

import os
import sys
import json
from pathlib import Path

# Add project root to path so we can import from tools/domain
_project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(_project_root))

import streamlit as st
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from graph import build_graph
from state.state import make_initial_state
from config import DEFAULT_TARGET_COVER_DAYS


st.set_page_config(page_title="OptiStock AI Stockout Resolution", page_icon="📦", layout="wide")


@st.cache_resource
def get_graph():
    """Cache the graph instance (and its in-memory checkpointer) across runs."""
    return build_graph(checkpointer=MemorySaver())


def init_session():
    """Initialise Streamlit session state variables."""
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = None
    if "current_state" not in st.session_state:
        st.session_state.current_state = None
    if "is_paused" not in st.session_state:
        st.session_state.is_paused = False





def main():
    init_session()
    graph = get_graph()
    
    st.title("OptiStock AI — Stockout Resolution System")
    st.write("Demonstrates multi-agent orchestration with LangGraph and human-in-the-loop.")
    
    # Sidebar for inputs
    with st.sidebar:
        st.header("New Case")
        with st.form("new_case_form"):
            sku = st.text_input("SKU", value="AC-007")
            warehouse = st.text_input("Warehouse ID", value="DEL-01")
            target_days = st.number_input("Target Cover Days", value=DEFAULT_TARGET_COVER_DAYS, min_value=7, max_value=45)
            
            if st.form_submit_button("Start Investigation"):
                initial_state = make_initial_state(sku, warehouse, target_days)
                st.session_state.thread_id = initial_state["case_id"]
                
                config = {"configurable": {"thread_id": st.session_state.thread_id}}
                
                with st.spinner("Agents are investigating..."):
                    try:
                        # Invoke graph; it will run until it hits the interrupt or END
                        graph.invoke(initial_state, config=config)
                    except Exception as e:
                        st.error(f"Execution error: {str(e)}")
                    
                    # Check graph state — interrupt() returns normally,
                    # so we always need to inspect .next after invoke
                    current_graph_state = graph.get_state(config)
                    st.session_state.current_state = current_graph_state.values
                    
                    if current_graph_state.next:
                        # Graph is paused (e.g. at human_approval interrupt)
                        st.session_state.is_paused = True
                    else:
                        # Graph completed
                        st.session_state.is_paused = False
                        
                    st.session_state.just_finished_run = True

                st.rerun()

    # Main content area
    if not st.session_state.thread_id:
        st.info("👈 Enter SKU details in the sidebar and click 'Start Investigation'")
        return
        
    state = st.session_state.current_state
    if not state:
        return
        
    st.header(f"Case: {state.get('case_id')}")
    
    if st.session_state.pop("just_finished_run", False):
        if st.session_state.is_paused:
            st.markdown(
                """
                <style>
                div[data-testid="stToast"] {
                    background-color: #e0f2fe !important;
                    border-left: 5px solid #0284c7 !important;
                }
                div[data-testid="stToast"] * {
                    color: #0c4a6e !important;
                }
                </style>
                """,
                unsafe_allow_html=True
            )
            st.toast("⏸️ Workflow paused for human approval.", icon="⏳")
        else:
            st.markdown(
                """
                <style>
                div[data-testid="stToast"] {
                    background-color: #dcfce7 !important;
                    border-left: 5px solid #16a34a !important;
                }
                div[data-testid="stToast"] * {
                    color: #14532d !important;
                }
                </style>
                """,
                unsafe_allow_html=True
            )
            st.toast("✅ Workflow run complete!", icon="🎉")
            if state.get("outcome") == "PURCHASE_REQUEST_CREATED":
                st.balloons()
    
    # Hide interrupt UI from top level (moved into the tabs)
    if st.session_state.is_paused:
        st.warning("⚠️ Human Approval Required. See the Summary tab below.")
        st.divider()
        
    # Show final outcome if finished
    elif not state.get("next") and state.get("outcome"):
        outcome = state.get("outcome")
        if outcome == "PURCHASE_REQUEST_CREATED":
            st.success(f"Outcome: {outcome}")
        elif outcome in ("NO_ACTION", "AWAITING_APPROVAL"):
            st.info(f"Outcome: {outcome}")
        else:
            st.error(f"Outcome: {outcome}")
            if state.get("error_message"):
                st.write(f"**Error:** {state.get('error_message')}")
        
    # Show tabs with state details
    tab_summary, tab1, tab2, tab3, tab4 = st.tabs(
        ["📋 Summary", "🔍 Investigation", "🏭 Sourcing", "✅ Execution", "📜 Audit Log"]
    )

    # ── Summary tab — product-like reasoning & action view ──
    with tab_summary:
        st.subheader("Decision Flow")

        # Step 1: Input
        with st.expander("1️⃣  Request Received", expanded=True):
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("SKU", state.get("sku", "—"))
            col_b.metric("Warehouse", state.get("warehouse_id", "—"))
            col_c.metric("Target Cover", f"{state.get('target_cover_days', '—')} days")

        # Step 2: Investigation reasoning
        inv = state.get("investigation_result")
        if inv:
            inv_status = inv.get("status", "—")
            icon = "✅" if inv_status == "NO_ACTION" else ("⚠️" if inv_status == "AT_RISK" else "🚫")
            with st.expander(f"2️⃣  Investigation — {icon} {inv_status}", expanded=True):
                st.write(inv.get("reasoning", "No reasoning available."))
                col_a, col_b, col_c = st.columns(3)
                col_a.metric("Available Units", inv.get("available_units", "—"))
                col_b.metric("Cover Days", f"{inv.get('cover_days', 0):.1f}")
                col_c.metric("Daily Velocity", f"{inv.get('daily_velocity', 0):.1f} units/day")
                if inv.get("stale"):
                    st.error("⚠️ Inventory data is **stale** (older than 48 hours).")
                if inv.get("error_message"):
                    st.warning(inv["error_message"])

        # Step 3: Sourcing reasoning
        src = state.get("sourcing_result")
        if src:
            src_status = src.get("status", "—")
            icon = "✅" if src_status == "PROPOSAL_READY" else "🚫"
            with st.expander(f"3️⃣  Sourcing — {icon} {src_status}", expanded=True):
                st.write(src.get("reasoning", "No reasoning available."))
                if src.get("all_options_summary"):
                    st.markdown("**Available Options:**")
                    st.markdown(src['all_options_summary'].replace('$', r'\$'))
                if src.get("trade_off_explanation"):
                    trade_off = src['trade_off_explanation'].replace('`', '').replace('$', r'\$').strip()
                    st.markdown(f"**Trade-off:** {trade_off}")
                col_a, col_b, col_c = st.columns(3)
                
                vendor_id = src.get("recommended_vendor_id", "—")
                vendor_name = src.get("recommended_vendor_name", "")
                vendor_display = vendor_name if vendor_name else vendor_id
                col_a.metric("Recommended Vendor", vendor_display)
                col_b.metric("Total Cost", f"${src.get('total_cost', 0):,.2f}")
                col_c.metric("Budget Remaining", f"${src.get('budget_remaining', 0):,.2f}")
                if src.get("is_over_budget"):
                    st.error("💰 Proposed cost **exceeds** the remaining monthly budget.")
                if src.get("error_message"):
                    st.warning(src["error_message"])

        # Step 4: Review reasoning
        rev = state.get("review_result")
        if rev:
            rev_status = rev.get("status", "—")
            icon = "✅" if rev_status == "APPROVED_FOR_HUMAN" else ("🔄" if rev_status == "NEEDS_REVISION" else "🚫")
            with st.expander(f"4️⃣  Policy Review — {icon} {rev_status}", expanded=True):
                st.markdown(rev.get("reasoning", "No reasoning available."))
                if rev.get("policy_violations"):
                    st.error("**Policy Violations:**")
                    for v in rev["policy_violations"]:
                        st.write(f"  - {v}")

        # Step 5: Human Approval action
        approval = state.get("approval_decision")
        if approval:
            decision = approval.get("decision", "—")
            icon = "✅" if decision == "APPROVED" else "❌"
            with st.expander(f"5️⃣  Human Decision — {icon} {decision}", expanded=True):
                st.write(f"**Approver:** {approval.get('approver', '—')}")
                st.write(f"**Decision:** {decision}")
                if approval.get("comments"):
                    st.write(f"**Comments:** {approval['comments']}")
        elif st.session_state.is_paused:
            with st.expander("5️⃣  Human Decision — ⏳ Awaiting Your Input", expanded=True):
                approval_request = state.get("approval_request") or {}
                # The proposal is guaranteed to be fully populated inside the approval_request
                proposal = approval_request.get("proposal") or state.get("proposal") or {}
                review = state.get("review_result") or {}
                
                col1, col2 = st.columns(2)
                with col1:
                    st.write("**Proposal Details:**")
                    st.write(f"- **SKU:** {proposal.get('sku')}")
                    st.write(f"- **Warehouse:** {proposal.get('warehouse_id')}")
                    st.write(f"- **Vendor:** {proposal.get('recommended_vendor_id')}")
                    st.write(f"- **Quantity:** {proposal.get('quantity')}")
                    st.write(f"- **Total Cost:** ${proposal.get('total_cost', 0):.2f}")
                    
                with col2:
                    st.write("**Policy Review:**")
                    st.write(f"- **Passed Policy:** {proposal.get('policy_passed')}")
                    if proposal.get('policy_violations'):
                        st.error("Violations:")
                        for v in proposal.get('policy_violations', []):
                            st.write(f"  - {v}")
                
                # Reasoning comes from the review agent, structured specifically for the approver
                if review.get("recommendation_for_approver"):
                    st.success("**Agent Reasoning:**\n\n" + review['recommendation_for_approver'])
                else:
                    st.info(f"**Agent Reasoning:** {review.get('reasoning', 'No reasoning provided.')}")
                
                with st.form("approval_form"):
                    decision_radio = st.radio("Decision", ["APPROVED", "REJECTED"])
                    comments = st.text_area("Comments")
                    submitted = st.form_submit_button("Submit Decision")
                    
                    if submitted:
                        decision_payload = {
                            "decision": decision_radio,
                            "approver": "StreamlitUser",
                            "comments": comments,
                            "proposal_id": proposal.get("proposal_id", "")
                        }
                        
                        with st.spinner(f"Processing {decision_radio}..."):
                            config = {"configurable": {"thread_id": st.session_state.thread_id}}
                            try:
                                graph.invoke(Command(resume=decision_payload), config=config)
                            except Exception as e:
                                st.error(f"Resume error: {str(e)}")
                            
                            current_graph_state = graph.get_state(config)
                            st.session_state.current_state = current_graph_state.values
                            st.session_state.is_paused = bool(current_graph_state.next)
                            st.session_state.just_finished_run = True
                            st.rerun()

        # Step 6: Execution result
        pr = state.get("purchase_request")
        if pr:
            with st.expander("6️⃣  Execution — ✅ Purchase Request Created", expanded=True):
                st.write(f"**Request ID:** `{pr.get('request_id', '—')}`")
                st.write(f"**Status:** {pr.get('status', '—')}")
                st.write(f"**Idempotent Hit:** {'Yes (duplicate prevented)' if not pr.get('created') else 'No (new request)'}")
        elif state.get("outcome") == "BLOCKED" and state.get("revalidation_result"):
            reval = state["revalidation_result"]
            with st.expander("6️⃣  Execution — 🚫 Revalidation Failed", expanded=True):
                st.error("Data changed while waiting for approval. Purchase request was **not** created.")
                st.write(f"- Stock valid: {reval.get('stock_valid')}")
                st.write(f"- Offer valid: {reval.get('offer_valid')}")
                st.write(f"- Budget valid: {reval.get('budget_valid')}")

    # ── Investigation tab — raw JSON ──
    with tab1:
        inv_res = state.get("investigation_result")
        if inv_res:
            st.json(inv_res)
        else:
            st.write("No investigation result.")
            
    # ── Sourcing tab — raw JSON ──
    with tab2:
        src_res = state.get("sourcing_result")
        if src_res:
            st.json(src_res)
        else:
            st.write("No sourcing result.")
            
    # ── Execution tab — raw JSON ──
    with tab3:
        pr = state.get("purchase_request")
        if pr:
            st.json(pr)
        else:
            st.write("No purchase request.")
            
    # ── Audit Log tab ──
    with tab4:
        events = state.get("audit_events", [])
        if events:
            st.write(f"**{len(events)} events recorded**")
            for e in events:
                st.code(e)
        else:
            st.write("No audit events.")


if __name__ == "__main__":
    main()

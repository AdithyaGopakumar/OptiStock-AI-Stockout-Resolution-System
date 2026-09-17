"""Streamlit UI rendering components for OptiStock AI.

Pure rendering functions that take workflow state and render
Streamlit widgets. Keeps all display logic separate from
orchestration (graph invocation, session management).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import streamlit as st


# ============================================================================
# TOAST NOTIFICATIONS
# ============================================================================

def render_toast_notifications(state: Dict[str, Any], is_paused: bool) -> None:
    """Show a one-time toast after a graph run completes or pauses."""
    if is_paused:
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
            unsafe_allow_html=True,
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
            unsafe_allow_html=True,
        )
        st.toast("✅ Workflow run complete!", icon="🎉")
        if state.get("outcome") == "PURCHASE_REQUEST_CREATED":
            st.balloons()


# ============================================================================
# OUTCOME BANNER
# ============================================================================

def render_outcome_banner(state: Dict[str, Any], is_paused: bool) -> None:
    """Render the top-level status banner for the current case."""
    if is_paused:
        st.warning("⚠️ Human Approval Required. See the Summary tab below.")
        st.divider()
    elif state.get("outcome"):
        outcome = state["outcome"]
        if outcome == "PURCHASE_REQUEST_CREATED":
            st.success(f"Outcome: {outcome}")
        elif outcome in ("NO_ACTION", "AWAITING_APPROVAL"):
            st.info(f"Outcome: {outcome}")
        else:
            st.error(f"Outcome: {outcome}")
            if state.get("error_message"):
                st.write(f"**Error:** {state.get('error_message')}")


# ============================================================================
# SUMMARY TAB — DECISION FLOW
# ============================================================================

def _render_request_section(state: Dict[str, Any]) -> None:
    """Step 1: Request received."""
    with st.expander("1️⃣  Request Received", expanded=True):
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("SKU", state.get("sku", "—"))
        col_b.metric("Warehouse", state.get("warehouse_id", "—"))
        col_c.metric("Target Cover", f"{state.get('target_cover_days', '—')} days")


def _render_investigation_section(state: Dict[str, Any]) -> None:
    """Step 2: Investigation reasoning."""
    inv = state.get("investigation_result")
    if not inv:
        return

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


def _render_sourcing_section(state: Dict[str, Any]) -> None:
    """Step 3: Sourcing reasoning."""
    src = state.get("sourcing_result")
    if not src:
        return

    src_status = src.get("status", "—")
    icon = "✅" if src_status == "PROPOSAL_READY" else "🚫"
    with st.expander(f"3️⃣  Sourcing — {icon} {src_status}", expanded=True):
        st.write(src.get("reasoning", "No reasoning available."))
        if src.get("all_options_summary"):
            st.markdown("**Available Options:**")
            st.markdown(src["all_options_summary"].replace("$", r"\$"))
        if src.get("trade_off_explanation"):
            trade_off = src["trade_off_explanation"].replace("`", "").replace("$", r"\$").strip()
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


def _render_review_section(state: Dict[str, Any]) -> None:
    """Step 4: Policy review reasoning."""
    rev = state.get("review_result")
    if not rev:
        return

    rev_status = rev.get("status", "—")
    icon = "✅" if rev_status == "APPROVED_FOR_HUMAN" else ("🔄" if rev_status == "NEEDS_REVISION" else "🚫")
    with st.expander(f"4️⃣  Policy Review — {icon} {rev_status}", expanded=True):
        st.markdown(rev.get("reasoning", "No reasoning available."))
        if rev.get("policy_violations"):
            st.error("**Policy Violations:**")
            for v in rev["policy_violations"]:
                st.write(f"  - {v}")


def _render_approval_decision(state: Dict[str, Any]) -> None:
    """Step 5 (completed): Show the recorded approval/rejection."""
    approval = state.get("approval_decision")
    if not approval:
        return

    decision = approval.get("decision", "—")
    icon = "✅" if decision == "APPROVED" else "❌"
    with st.expander(f"5️⃣  Human Decision — {icon} {decision}", expanded=True):
        st.write(f"**Approver:** {approval.get('approver', '—')}")
        st.write(f"**Decision:** {decision}")
        if approval.get("comments"):
            st.write(f"**Comments:** {approval['comments']}")


def render_approval_form(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Step 5 (pending): Render the interactive approval form.

    Returns
    -------
    dict or None
        The approval decision payload if the form was submitted,
        ``None`` otherwise.
    """
    with st.expander("5️⃣  Human Decision — ⏳ Awaiting Your Input", expanded=True):
        approval_request = state.get("approval_request") or {}
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
            if proposal.get("policy_violations"):
                st.error("Violations:")
                for v in proposal.get("policy_violations", []):
                    st.write(f"  - {v}")

        # Reasoning from the review agent, structured for the approver
        if review.get("recommendation_for_approver"):
            st.success("**Agent Reasoning:**\n\n" + review["recommendation_for_approver"])
        else:
            st.info(f"**Agent Reasoning:** {review.get('reasoning', 'No reasoning provided.')}")

        with st.form("approval_form"):
            decision_radio = st.radio("Decision", ["APPROVED", "REJECTED"])
            comments = st.text_area("Comments")
            submitted = st.form_submit_button("Submit Decision")

            if submitted:
                return {
                    "decision": decision_radio,
                    "approver": "StreamlitUser",
                    "comments": comments,
                    "proposal_id": proposal.get("proposal_id", ""),
                }

    return None


def _render_execution_section(state: Dict[str, Any]) -> None:
    """Step 6: Execution result or revalidation failure."""
    pr = state.get("purchase_request")
    if pr:
        with st.expander("6️⃣  Execution — ✅ Purchase Request Created", expanded=True):
            st.write(f"**Request ID:** `{pr.get('request_id', '—')}`")
            st.write(f"**Status:** {pr.get('status', '—')}")
            st.write(
                f"**Idempotent Hit:** "
                f"{'Yes (duplicate prevented)' if not pr.get('created') else 'No (new request)'}"
            )
    elif state.get("outcome") == "BLOCKED" and state.get("revalidation_result"):
        reval = state["revalidation_result"]
        with st.expander("6️⃣  Execution — 🚫 Revalidation Failed", expanded=True):
            st.error("Data changed while waiting for approval. Purchase request was **not** created.")
            st.write(f"- Stock valid: {reval.get('stock_valid')}")
            st.write(f"- Offer valid: {reval.get('offer_valid')}")
            st.write(f"- Budget valid: {reval.get('budget_valid')}")


def render_summary_tab(state: Dict[str, Any], is_paused: bool) -> Optional[Dict[str, Any]]:
    """Render the full Summary tab with the decision flow.

    Returns
    -------
    dict or None
        Approval decision payload if the approval form was submitted,
        ``None`` otherwise.
    """
    st.subheader("Decision Flow")

    _render_request_section(state)
    _render_investigation_section(state)
    _render_sourcing_section(state)
    _render_review_section(state)

    # Step 5: Human approval — either show the completed decision or the form
    decision_payload = None
    if state.get("approval_decision"):
        _render_approval_decision(state)
    elif is_paused:
        decision_payload = render_approval_form(state)

    _render_execution_section(state)

    return decision_payload


# ============================================================================
# RAW DATA TABS
# ============================================================================

def render_investigation_tab(state: Dict[str, Any]) -> None:
    """Render the raw investigation JSON tab."""
    inv_res = state.get("investigation_result")
    if inv_res:
        st.json(inv_res)
    else:
        st.write("No investigation result.")


def render_sourcing_tab(state: Dict[str, Any]) -> None:
    """Render the raw sourcing JSON tab."""
    src_res = state.get("sourcing_result")
    if src_res:
        st.json(src_res)
    else:
        st.write("No sourcing result.")


def render_execution_tab(state: Dict[str, Any]) -> None:
    """Render the raw execution JSON tab."""
    pr = state.get("purchase_request")
    if pr:
        st.json(pr)
    else:
        st.write("No purchase request.")


def render_audit_tab(state: Dict[str, Any]) -> None:
    """Render the audit log tab."""
    events = state.get("audit_events", [])
    if events:
        st.write(f"**{len(events)} events recorded**")
        for e in events:
            st.code(e)
    else:
        st.write("No audit events.")

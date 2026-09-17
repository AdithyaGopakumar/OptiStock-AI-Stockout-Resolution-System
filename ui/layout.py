"""Streamlit UI layout and orchestration for OptiStock AI."""

import streamlit as st
from langgraph.types import Command

from state.state import make_initial_state
from config import DEFAULT_TARGET_COVER_DAYS
from ui.components import (
    render_toast_notifications,
    render_outcome_banner,
    render_summary_tab,
    render_investigation_tab,
    render_sourcing_tab,
    render_execution_tab,
    render_audit_tab,
)


def init_session():
    """Initialise Streamlit session state variables."""
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = None
    if "current_state" not in st.session_state:
        st.session_state.current_state = None
    if "is_paused" not in st.session_state:
        st.session_state.is_paused = False


def _invoke_and_sync(graph, input_data, config):
    """Run graph.invoke and sync the result back to session state."""
    try:
        graph.invoke(input_data, config=config)
    except Exception as e:
        st.error(f"Execution error: {str(e)}")

    current_graph_state = graph.get_state(config)
    st.session_state.current_state = current_graph_state.values
    st.session_state.is_paused = bool(current_graph_state.next)
    st.session_state.just_finished_run = True


def render_app(graph):
    """Render the main application UI."""
    init_session()

    st.title("OptiStock AI — Stockout Resolution System")
    st.write("Demonstrates multi-agent orchestration with LangGraph and human-in-the-loop.")

    # ── Sidebar: new case form ──
    with st.sidebar:
        st.header("New Case")
        with st.form("new_case_form"):
            sku = st.text_input("SKU", value="AC-007")
            warehouse = st.text_input("Warehouse ID", value="DEL-01")
            target_days = st.number_input(
                "Target Cover Days", value=DEFAULT_TARGET_COVER_DAYS, min_value=7, max_value=45
            )

            if st.form_submit_button("Start Investigation"):
                initial_state = make_initial_state(sku, warehouse, target_days)
                st.session_state.thread_id = initial_state["case_id"]
                config = {"configurable": {"thread_id": st.session_state.thread_id}}

                with st.spinner("Agents are investigating..."):
                    _invoke_and_sync(graph, initial_state, config)

                st.rerun()

    # ── Main content area ──
    if not st.session_state.thread_id:
        st.info("👈 Enter SKU details in the sidebar and click 'Start Investigation'")
        return

    state = st.session_state.current_state
    if not state:
        return

    st.header(f"Case: {state.get('case_id')}")

    # One-time toast after a run
    if st.session_state.pop("just_finished_run", False):
        render_toast_notifications(state, st.session_state.is_paused)

    # Top-level status banner
    render_outcome_banner(state, st.session_state.is_paused)

    # ── Tabbed content ──
    tab_summary, tab_inv, tab_src, tab_exec, tab_audit = st.tabs(
        ["📋 Summary", "🔍 Investigation", "🏭 Sourcing", "✅ Execution", "📜 Audit Log"]
    )

    with tab_summary:
        decision = render_summary_tab(state, st.session_state.is_paused)
        if decision is not None:
            # Human submitted an approval/rejection — resume the graph
            config = {"configurable": {"thread_id": st.session_state.thread_id}}
            with st.spinner(f"Processing {decision['decision']}..."):
                _invoke_and_sync(graph, Command(resume=decision), config)
            st.rerun()

    with tab_inv:
        render_investigation_tab(state)

    with tab_src:
        render_sourcing_tab(state)

    with tab_exec:
        render_execution_tab(state)

    with tab_audit:
        render_audit_tab(state)

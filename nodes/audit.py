"""Audit event helper (deterministic).

Wraps ``tools.execution.append_audit_event`` with convenience functions
so every node can log structured events consistently.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from tools.execution import append_audit_event
from state.state import OptiStockState


def log_audit_event(
    state: OptiStockState,
    actor: str,
    event_type: str,
    payload: Dict[str, Any],
) -> str:
    """Append an audit event and return the new event_id.

    Parameters
    ----------
    state : OptiStockState
        Current workflow state (supplies case_id and trace_id).
    actor : str
        Who emitted the event — e.g. ``"system"``, ``"agent:investigation"``,
        ``"human:reviewer"``.
    event_type : str
        Structured event type — e.g. ``"input_validated"``, ``"risk_assessed"``,
        ``"proposal_drafted"``, ``"approved"``, ``"purchase_created"``.
    payload : dict
        JSON-serialisable event body.  Must NOT contain secrets or
        private chain-of-thought.

    Returns
    -------
    str
        The generated event_id, or an empty string on failure.
    """
    result = append_audit_event(
        case_id=state["case_id"],
        trace_id=state["trace_id"],
        actor=actor,
        event_type=event_type,
        payload=payload,
    )
    return result.event_id if result.created else ""


def audit_node(
    state: OptiStockState,
    actor: str,
    event_type: str,
    payload: Dict[str, Any],
) -> dict:
    """Thin wrapper that logs an audit event and returns state updates.

    Returns a dict with the new event ID appended to ``audit_events``.
    """
    event_id = log_audit_event(state, actor, event_type, payload)
    current_events = list(state.get("audit_events", []))
    if event_id:
        current_events.append(event_id)
    return {"audit_events": current_events}

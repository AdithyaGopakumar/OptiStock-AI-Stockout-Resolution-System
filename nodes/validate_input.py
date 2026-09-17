"""Input validation node (deterministic).

Checks that all required request fields are present and within valid ranges
before any database queries are made.
"""

from __future__ import annotations

from state.state import OptiStockState
from config import TARGET_COVER_DAYS_MIN, TARGET_COVER_DAYS_MAX


def validate_input_node(state: OptiStockState) -> dict:
    """Validate incoming request fields.

    Returns state updates. Sets ``outcome`` to ``NEEDS_INFORMATION``
    if any required field is missing or out of range.
    """
    errors: list[str] = []

    sku = state.get("sku")
    warehouse_id = state.get("warehouse_id")
    target_cover_days = state.get("target_cover_days", 14)

    if not sku or not isinstance(sku, str) or sku.strip() == "":
        errors.append("'sku' is required but missing or empty.")

    if not warehouse_id or not isinstance(warehouse_id, str) or warehouse_id.strip() == "":
        errors.append("'warehouse_id' is required but missing or empty.")

    if not isinstance(target_cover_days, int):
        errors.append("'target_cover_days' must be an integer.")
    elif target_cover_days < TARGET_COVER_DAYS_MIN or target_cover_days > TARGET_COVER_DAYS_MAX:
        errors.append(
            f"'target_cover_days' must be between {TARGET_COVER_DAYS_MIN} "
            f"and {TARGET_COVER_DAYS_MAX}, got {target_cover_days}."
        )

    if errors:
        return {
            "outcome": "NEEDS_INFORMATION",
            "error_code": "INVALID_INPUT",
            "error_message": " ".join(errors),
        }

    # Normalise whitespace
    return {
        "sku": sku.strip(),
        "warehouse_id": warehouse_id.strip(),
        "target_cover_days": target_cover_days,
    }

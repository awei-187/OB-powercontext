"""Baseline order listing: supports pagination, not status filtering yet."""

from collections.abc import Sequence
from typing import Any


def list_orders(
    orders: Sequence[dict[str, Any]], *, page: int = 1, page_size: int = 2
) -> list[dict[str, Any]]:
    """Return one page in input order, without changing caller-owned records."""
    if type(page) is not int or page < 1:
        raise ValueError("page must be a positive integer")
    if type(page_size) is not int or page_size < 1:
        raise ValueError("page_size must be a positive integer")
    start = (page - 1) * page_size
    return [dict(order) for order in orders[start : start + page_size]]

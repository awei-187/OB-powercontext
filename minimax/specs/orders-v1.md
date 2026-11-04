# Order query specification

Specification ID: ORDERS-QUERY. Revision: 1.

## Existing behavior (must remain compatible)

- ORD-001: `list_orders(orders, *, page=1, page_size=2)` returns one page
  of records in their original input order.
- ORD-002: `page` and `page_size` must be strictly positive integers;
  booleans, floats, strings, zero and negatives raise `ValueError`.
- ORD-003: Empty inputs and pages beyond the end return an empty list.
- ORD-004: The function does not mutate the input. Returned dictionaries
  are copies of the corresponding records (no deep-copy requirement).

## Requested change

- ORD-005: Add the optional keyword-only parameter `status=None`.
  Omitting it, or passing `None`, preserves the original listing behavior.
- ORD-006: Valid non-null statuses are exactly `pending`, `paid`, and
  `cancelled`. Reject other values, including wrong case, whitespace,
  booleans and non-string values, with `ValueError`.
- ORD-007: Filter on exact `order['status']` equality **before** pagination.
  Preserve original order among matching records.
- ORD-008: A valid filter with no matching records returns an empty list.

## Sources

- Implementation: `sample_project/orders.py::list_orders`
- Compatibility tests: `tests/test_regression.py`
- Requested behavior tests: `tests/test_target.py`

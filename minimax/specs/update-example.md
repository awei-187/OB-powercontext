# Specification update scenario (not the initial effective specification)

After the first task is complete, create a revision 2 of `orders-v1.md`:

- Change the revision to 2.
- Replace ORD-006's valid status set with `pending`, `paid`, `cancelled`,
  and `refunded`.
- Keep the remaining requirements unchanged.

Re-import the changed specification under the same logical document identity.
Ask which statuses are supported. The assembled context must cite revision 2,
include `refunded`, and must not present revision 1 as the current requirement.
Keep the original acceptance tests unchanged for the initial code-change task.
This file is a scenario description, not an additional effective business rule.

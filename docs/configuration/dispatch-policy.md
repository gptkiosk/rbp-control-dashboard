# Dispatch pricing, memberships and spending limits

Every task and chat launch passes the shared dispatch gate immediately before the native process/adapter starts. It freezes and rechecks the exact model, target, price class and requested budget. A changed or revoked class, unpinned model or malformed launch snapshot is refused.

## Operator controls

**Agents → Billing & rates → Spending & limits** stores reviewed-price requirements, an optional per-run cap and an optional requirement for a native dollar boundary. These limits are off unless the operator enables them. Without a dollar boundary, a paid route bills the provider account/key; configure provider-side credit limits too. CLI/runtime fallback and account overage settings can also affect actual billing.

`MAC_CONTROL_DISPATCH_FREE_ONLY=true` restricts starts to reviewed free routes. In **Settings → Coordinator setup → Model recovery**, the operator may explicitly enable **Allow membership routes alongside free models**. This permits accounts configured as subscriptions while keeping paid API disabled until its separate toggle and request approval. Membership consumes shared account quota and may use provider-enabled overage; it does not include API billing. MCD ships Claude/Codex membership defaults; RCD requires its operator to configure account mode in Billing & rates.

An exact `MAC_CONTROL_DISPATCH_ROUTE_CLASSES` entry (`agent|target|model`: `free`, `subscription` or `paid`) takes precedence. Configured Hermes free routes and operator-reviewed project free routes provide bounded route evidence. A name, zero estimated cost or process success alone does not authorize arbitrary API spending. When **Require reviewed pricing** is enabled, unknown routes stop with `PRICE_UNKNOWN`.

The app freezes the chosen route at claim time. A provider’s native fallback behavior still depends on its runtime configuration and must be reviewed separately; do not infer an account-wide billing guarantee from a requested model or task budget.

## Recovery

[Model recovery](model-recovery.md) controls ordered alternatives and failure advice. Selecting a paid alternative does not authorize its use by itself: paid planning needs a separate request acknowledgment; paid execution routes need reviewed plan/task approval. Editing timeouts need explicit review of partial work. Automatic alternatives cannot alter workspace permissions, story scope, dependencies or human acceptance.

When a launch fails with `FREE_ONLY`, configure a permitted free route, or explicitly permit a configured membership route using the linked toggle. A paid API route remains refused until the paid-route toggle is enabled and the particular plan/task is approved. `PRICE_UNKNOWN` requires reviewing the exact route’s class. `BUDGET_EXCEEDED`/`BUDGET_UNENFORCED` requires reviewing the chosen cap and runtime boundary. No failure automatically widens permissions or increases a cap.

# Models & providers (route policy)

One policy decides which providers, runtimes, models and cost classes the app may use. It covers five features: the Coordinator, the planner, stories, chat and tasks. Every route menu lists only what the policy allows. Planning refuses a planner outside it. The dispatch gate checks it again immediately before a run starts, with `ROUTE_POLICY`, so narrowing the policy after a task was claimed stops that task.

Open it in **Settings → Models & providers**.

## Scopes: each one only narrows

| Scope | Where it is set | What it can do |
| --- | --- | --- |
| Installation (managed) | A JSON file named by `MAC_CONTROL_MANAGED_ROUTE_POLICY` | The outer limit. Nothing in the app can widen it. |
| App | Settings → Models & providers | Narrows the managed policy for the whole app. |
| Project | Project page → Routes → Change… → Narrow for this project | Narrows the app policy for one project. The default is **Same as app**. |

Inside one scope, a feature's own rule replaces that scope's general rule for that feature. For example, an app policy can allow paid API for the Coordinator only. Across scopes, every rule applies, so a project can never allow what the app removes, and the app can never allow what the installation removes.

## Cost classes

- **Membership**: a Claude, Codex or Grok Build account you are signed in to, set as Subscription in Agents → Billing & rates. It uses account quota, and any overage you enabled with the provider still applies.
- **Free**: a model the reviewed price class lists as free. Free endpoints are often slow, limited or unavailable.
- **Paid API**: bills your provider account per token. It is always the last resort. Each plan or task still needs paid-route approval, and the limits you turned on in Spending & limits still apply.

When the app chooses or retries a route, it tries membership first, then free, then paid API.

A route whose price nobody reviewed counts as **paid API** when a run starts. While planning and checking a plan, it is a warning only. Admission decides.

## Presets

- **Memberships (recommended)**: membership and free routes from any provider. No paid API.
- **Single provider…**: only one provider's models, for example xAI. Routes whose provider varies per request (`openrouter/free`, `openrouter/auto`) are hidden. The Coordinator (Hermes) reaches that provider's models through an API, so the preset can allow paid API for the Coordinator only.
- **Free only**: for trying the app. Expect timeouts and incomplete output.
- **Custom**: choose providers, runtimes and cost classes yourself.

With providers limited, **Also offer free models from any provider** adds specific free models (never a router alias) as a no-cost fallback.

## Prices to review

Models & providers lists the routes that the policy would allow, except that their price was never reviewed. Check the provider's price, then record it:

- **Paid API** can be recorded for any route.
- **Free** is offered only for a Hermes or OpenClaw model that is a free variant or that the cached OpenRouter list shows at no cost. A review cannot turn a billed route into a free one.
- Memberships are not set here. Set the account mode in Billing & rates.

A review applies to that exact runtime, target and model. **Clear** returns the route to "not reviewed". An exact `MAC_CONTROL_DISPATCH_ROUTE_CLASSES` entry in the installation settings takes precedence over a review made in the app. A task claimed before a review changed is refused with `PRICE_UNKNOWN` and can be retried.

## Installation-managed policy

A business installation can lock the whole app, for example to Grok Build only. Write the policy as JSON, owned by the service account and not writable by agents, then point `MAC_CONTROL_MANAGED_ROUTE_POLICY` at it:

```json
{
  "providers": ["xai"],
  "runtimes": ["grok", "hermes"],
  "cost": {"free": false, "membership": true, "paid": false},
  "features": {
    "coordinator": {"providers": ["xai"], "runtimes": ["hermes"], "cost": {"free": false, "membership": false, "paid": true}}
  },
  "defaults": {"stories": {"runtime": "grok", "model": "grok-build-0.1"}}
}
```

With a managed policy in force:

- Models & providers shows a banner, and the choices it removes are greyed.
- Agent tools, the Setup wizard and Agents → Billing & rates leave out the runtimes it removes, and they say which runtimes are hidden. Saved accounts and installed tools are kept.
- A file that is set but missing or invalid allows nothing (it fails closed). Models & providers names the problem.

## What happened to free-only

`MAC_CONTROL_DISPATCH_FREE_ONLY` and the two Model recovery switches (allow membership, allow paid) are retired. On the first start of this version the app writes its first app policy from them:

- Membership stays on unless you had switched it off.
- Paid API stays as the old setting left it. That is off on RCD, which was free-only by default. On MCD it is on, with approval per plan or task.

After that, the old setting is not read again. Model recovery shows the current cost classes and links here.

## When nothing is allowed

The route menus, the project route strip and the per-feature summary on Models & providers never leave a choice empty without a reason. They name the nearest route and what stops it, for example: "Nearest: Hermes · x-ai/grok-4.6: paid API is off (price not reviewed…)". The fix is usually a cost class or a price review on Models & providers.

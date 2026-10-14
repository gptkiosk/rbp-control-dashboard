"""Pi admission bound to an operator scope decision, never to billing estimates.

Only MCD selects a fallback. Runtime fallback stays disabled in every RunSpec.
The operator binds structured caps by (project id, approved revision); prose memory
is deliberately not interpreted as executable spending permission.
"""
from dataclasses import dataclass
from adapter_contract import AdapterError
from approval import resolve_workdir, current_branch, reasons_for
from openrouter_costs import amount


@dataclass(frozen=True)
class ScopeCaps:
    max_run_usd: float
    max_project_usd: float
    free_only: bool = True

    def __post_init__(self):
        if amount(self.max_run_usd) is None or amount(self.max_project_usd) is None:
            raise ValueError("Scope caps must be finite nonnegative USD amounts")
        if not self.free_only:
            raise ValueError("Paid Pi routes have not been authorized")


def admit(spec, caps, routes, *, project_spend=0.0, roots=(), approved=False, approval_prompt=None):
    route = spec['model_policy']['assigned']
    if not route.get('model') or not any(route['agent'] == r['agent'] and route['model'] == r['model'] for r in routes):
        raise AdapterError('MODEL_NOT_ALLOWED', 'Assignment is outside the approved story routes')
    if spec['model_policy'].get('allow_runtime_fallback') is not False:
        raise AdapterError('MODEL_NOT_ALLOWED', 'Runtime fallback must be disabled')
    workdir = resolve_workdir(spec['workspace']['path'], roots)
    if workdir is None:
        raise AdapterError('WORKSPACE_REJECTED', 'Workspace is outside the approved roots')
    if reasons_for(spec['prompt'] if approval_prompt is None else approval_prompt, spec['workspace']['mode'], current_branch(workdir)) and not approved:
        raise AdapterError('TOOL_DENIED', 'Operator approval is required before dispatch')
    cap = amount(spec['budget'].get('max_cost_usd'))
    spent = amount(project_spend)
    if cap is None or spent is None or spent > caps.max_project_usd:
        raise AdapterError('BUDGET_EXCEEDED', 'Missing cap or project budget exhausted')
    # $0 is a valid free-only cap, not a missing value. Never raise it to a default.
    spec['budget'].update(billing='free', max_cost_usd=min(cap, caps.max_run_usd, caps.max_project_usd - spent))
    spec['model_policy']['approved_fallback_routes'] = [dict(r) for r in routes if r != route]
    spec['model_policy']['require_model_report'] = True
    return spec

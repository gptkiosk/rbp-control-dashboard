"""An app-owned, editable setup plan: no provider call is needed to build its schema."""
from project_schemas import Node


def nodes(settings, choices, model):
    product = settings.product_short_name
    prefix = product.lower()
    result = []

    def story(key, title, description, scope, acceptance, *, human=False, edit=False, deps=()):
        result.append(Node(key=key, title=title, description=description, scope=scope, acceptance=acceptance,
            assignee='human' if human else 'hermes', model='' if human else model, mode='edit' if edit else 'read',
            depends_on=list(deps), work_kind='review' if human else 'ops', size='s', risk='medium',
            estimate_minutes=45, area='setup', route_reason='Hermes owns bootstrap work; the operator owns sign-in, permissions and final acceptance.',
            rationale='Built-in setup template. Review and edit before approving.', x=40, y=40+150*len(result)).model_dump())

    prior = []
    for platform in choices.platforms:
        inspect = 'inspect-' + platform
        story(inspect, f'Inspect {platform} readiness',
            f'Inspect {platform} executable availability, version, ability to start, configured model IDs and sign-in prerequisites. '
            'Read configuration structure only; never read or print credential values. Report present, missing and unverified items separately. '
            'Provide human actions as Markdown links: [Agent tools](/profile#agent-tools), [Credentials](/profile#credentials-profile), '
            '[Model recovery](/profile#route-recovery). Do not install software or invoke another agent/model.',
            f'Read-only inspection of {platform} on this host. No files, agent invocations, account, billing or permission changes.',
            'A readiness checklist identifies executable/version, model and sign-in state without secrets. Each unmet prerequisite names the exact app link and action.', deps=prior)
        gate = 'prerequisites-' + platform
        story(gate, f'Review {platform} prerequisites',
            f'Review the {platform} readiness handoff. Complete any required sign-in or model choice in '
            '[Agent tools](/profile#agent-tools) and [Credentials](/profile#credentials-profile). Review '
            '[route recovery](/profile#route-recovery) if a provider is failing. Confirm only the actions and permissions you intend to allow. '
            'If the platform is unavailable, record that it is excluded from this bootstrap rather than approving configuration of it.',
            f'Operator decision about {platform} prerequisites and permitted setup; no automatic credential, billing or permission changes.',
            'Record ready and approved for missing guidance, or excluded with its reason. Do not accept unresolved prerequisites as ready.', human=True, deps=[inspect])
        configure = 'configure-' + platform
        roles = ', '.join(choices.roles) or 'no role agents selected'
        names = ', '.join(f'{prefix}-oc-{role}' for role in choices.roles)
        story(configure, f'Prepare missing {platform} role guidance',
            f'Read the accepted {platform} readiness and prerequisite decisions. If excluded, report exclusion and make no changes. '
            f'For approved ready platforms, prepare only missing guidance for these selected roles: {roles}. '
            + (f'For OpenClaw, selected agent IDs are {names}. Each missing agent needs a focused SOUL.md, AGENTS.md, starting prompt and configured default model reference. '
                'Developer implements bounded project tasks; security reviews threats and changes independently; reviewer checks acceptance evidence when selected. '
                if platform == 'openclaw' else 'Prepare platform-appropriate role instructions and project handoff conventions. ')
            + 'Use this project workspace to stage missing files and an inventory first. Native registration or writes outside approved workspace permissions '
            'require an available scoped app tool and explicit task permission; otherwise leave a linked human action with exact apply steps. '
            'Reuse configured defaults and never invent model IDs. Report to Hermes using completed work, evidence, remaining blockers and next human action.',
            f'Only selected missing {platform} role guidance/agents. Never overwrite existing files or agents, alter credentials/billing, change models or widen permissions.',
            'Inventory lists created, preserved, staged-only and excluded items with paths and evidence. A staged artifact is not reported as an installed agent.', edit=True, deps=[gate])
        prior = [configure]

    story('shared-areas', 'Prepare shared project areas',
        f'Shared project memory requested: {choices.shared_project_memory}. Project workspaces requested: {choices.project_workspaces}. '
        'Create only requested missing directories and starter handoff notes inside this approved workspace. Document how projects share scoped memory, '
        'where outputs go, and how Hermes reads accepted handoffs. Preserve existing files. Disabled features receive no changes.',
        'Missing shared project memory and workspace starter files inside the approved workspace only; no global identity or credential changes.',
        'Requested areas exist with a file inventory and readable starter handoff. Existing files are preserved; disabled areas are recorded.', edit=True, deps=prior)
    story('verify-setup', 'Verify bootstrap readiness',
        'Review every accepted setup handoff and inspect the resulting non-secret files. Confirm agents are actually registered where claimed, '
        'guidance exists and model defaults refer to configured models. Do not launch a paid probe or worker. '
        'Summarize ready, excluded, staged-only and blocked platforms. Link every remaining human action to its app location. '
        'Recommend a small subsequent project using only verified routes.',
        'Read-only verification of the exact approved bootstrap artifacts and registration state. No repairs, paid calls or credential access.',
        'Readiness summary includes evidence per platform, preserved configurations, shared-area inventory and linked blockers. No unverified platform is declared ready.', deps=['shared-areas'])
    story('human-acceptance', 'Review setup and start a small project',
        'Review the verified readiness summary and remaining human actions. Visit [Agents](/agents), [Model recovery](/profile#route-recovery) '
        'and [Projects](/projects). Accept the bootstrap only for platforms proven ready; record exclusions and blockers. '
        'Then create a small project using a verified worker route to exercise the normal plan and handoff workflow.',
        'Operator acceptance of bootstrap evidence and selection of ready platforms for the next project.',
        'Operator records which platforms are ready, which remain excluded/blocked and the next validation project.', human=True, deps=['verify-setup'])
    return result

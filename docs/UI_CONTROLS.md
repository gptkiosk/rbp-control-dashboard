# Shared dropdowns

Single-value dropdowns use `apps/web/src/components/AppSelect.vue`, including agent/session/process
selection, usage periods, billing, new chats/tasks, task priorities/units/dependencies,
working directories and MCP requests. Editable model pickers use the same component and
allow arbitrary model IDs. Colors, dimensions and typography come from design tokens.
Task Filters and Lanes retain their checkbox menus and use the same glass surfaces, borders,
chevrons, typography and option highlights.

Pass `v-model` (or `:value` plus `@change`) and normal `<option>` slots. Use `data-label`
for a concise human name and `data-description` for an ID, branch or full path. Otherwise
option text separated by ` · ` becomes primary/secondary text automatically. Closed controls
truncate long text; open options wrap. `selectLabels.ts` keeps target/directory formatting
consistent without changing submitted IDs or paths.

The visible control follows the combobox/listbox pattern with keyboard focus on the control,
an active option, selected checks and disabled options. Arrow keys navigate, Home/End jump,
typing finds names, Enter/Space select and Escape closes the menu. Editable models filter
as you type and keep custom IDs. Tab, outside focus/click, scrolling the page and resize
close menus. Escape closes an open dropdown before its enclosing dialog.

A hidden native select retains typed option values, required validation and legacy change
events. Invalid fields focus the visible control. Popup menus use the browser top layer,
stay within viewport bounds and open above a control when needed. Menus remain descendants
of their dialog for focus and event handling; selecting never submits a form.

Web tests cover keyboard/disabled selection, typeahead, editable model IDs, label interaction,
required validation, dialog Escape and existing task/chat/billing/MCP payloads. Live checks
cover desktop/phone menu placement and formatted agent/target/directory options.

Dialogs share the same blue glass surface, input borders and gradient primary action through
`ModalShell.vue` and design tokens. New Chat groups Agent/Model on desktop, stacks fields on
phones and presents Read/Edit as selectable tiles backed by native keyboard-accessible radios.

# Shared dashboard surfaces

The shell, sidebar, metric tiles, charts, tables and placeholders share the blue glass
tokens in `tokens.css`. Common cards use `.card`; use `.table-scroll` around wide tables
so they scroll inside the content area. Services retain their labeled card layout on phones.
Existing agent and chat surfaces keep their stronger glass treatment.

`--card-glass`, `--nav-glass`, `--surface-border`, `--surface-radius` and
`--surface-shadow` define the common surfaces. Active navigation has both a border and
an inset indicator. Buttons and dropdowns share a minimum control height; primary actions
share the blue-to-cyan gradient. System fonts remain local; no font downloads are required.

The first keyboard stop is Skip to content, targeting the focusable main landmark. The
global reduced-motion rule suppresses animation and transitions. Common panels and
navigation use solid surfaces when reduced transparency is requested. Changes should be
reviewed at 1440px and 390px with bounded content and reachable dialog actions.

Mission Control's local CSS and bundled overview/agents/task screenshots informed the
dark surfaces, accent hierarchy and grouped information. MCD follows the operator's later
blue glass and vertical task-board direction. No new theme selector or Settings route is
introduced; billing settings and MCP remain their existing controls.


GitHub and Ops reports use the common glass surfaces and AppSelect dropdowns.
Repository cards select a detail pane with PRs/issues. Report rows and the phone selector
open the same report viewer. Long tables/code blocks scroll within the viewer; Markdown
lists, headings, links and blockquotes retain their formatting after Tailwind resets.
See OPS_PANELS.md for source limits and read-only behavior.

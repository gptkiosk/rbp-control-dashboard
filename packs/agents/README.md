# Starter role agents

The dashboard's Coordinator setup copies these files into the workspace of each OpenClaw role agent it creates (`<product>-oc-<role>`), then registers the agent with `openclaw agents add`. `{product}` is replaced with the product's short name (MCD or RCD).

A file that already exists in an agent workspace is never replaced. To change a running agent, edit its workspace copy; these files only seed new agents. Bump `VERSION` when the text changes.

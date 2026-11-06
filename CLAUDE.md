# {{app-name}}-backend

Ajna Cloud app backend — Python 3.12 Lambda on `ajna-cloud` SDK, IbexDB, Cognito.

Platform knowledge lives in the **`ajna` Claude Code plugin**. Do not restate it here.

```
/plugin marketplace add ajnacloud-ksj/ajna-claude-plugin
/plugin install ajna@ajna-claude-plugin
```

## This app

| | |
|---|---|
| Tenant | `{{tenant_id}}` (snake_case) |
| `APP_PREFIX` | `{{app-name}}` — **required**; unset means every user resolves to role `user` |
| Branch | `develop` → dev (`triviz.cloud`) · `main` → prod (`ajna.cloud`) |
| Siblings | `{{app-name}}-ui` · `{{app-name}}-plugins` |

## Where to look

| Task | Skill |
|---|---|
| Run it locally (`dev.sh`, local IbexDB) | `ajna-local-dev` |
| Add an endpoint, table, or entity | `ajna-build` |
| Something is broken | `ajna-debug` |
| Infra, config, SDK/base-image bump | `ajna-pulumi-deploy` |
| File an issue or PR | `ajna-workflow` |

## Non-negotiables

1. **Validate locally before pushing.** A push to `develop` deploys to dev. Run it,
   exercise the path you changed with a real Cognito JWT, and — if you touched roles or
   tables — exercise it as a non-super-admin too.
2. **All AWS changes go through `ajna-app-infra`** (Pulumi, applied by the
   `ajna-pulumi-runner` CodeBuild project). Never the console, never `aws ... update-*`
   against live infra. Read-only CLI is fine and encouraged.
3. **Builds and deploys run on CodeBuild**, never GitHub Actions.
4. **`AUTH_MODE=cognito` everywhere**, including local dev. Never `local`.

Full detail: the plugin's `shared/ground-rules.md`.

## Local gotcha worth knowing

The SDK is installed **inside the container**, not on your host — so type checkers need
`[tool.pyright] extraPaths` in `pyproject.toml` pointing at your SDK clone. That is
already configured; adjust the paths if your checkout layout differs.

<!--
Keep this file SHORT — it loads on every session, so every line is a permanent context
cost. Anything true of all Ajna apps belongs in the plugin. This file carries only what
is specific to THIS app.
-->

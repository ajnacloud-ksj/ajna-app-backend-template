# How we work

> Pointer, not a copy — the process is maintained in one place so it can never drift.

```
ticket → triage → PR against ticket → merge (dev auto-deploys) → Cut release (prod)
```

1. **Ticket first** — New issue → pick a type (Feature / Bug / Tech debt / Chore). The form
   applies the type label itself.
2. **PR against the ticket** — title `feat(scope): summary`, one type label (both CI-enforced),
   `Closes #N` in the description.
3. **Merge to `develop`** — dev deploys, the ticket closes, the board updates. All automatic.
4. **Release** — `ajna-app-infra` → Actions → **Cut release** → app name. Review and merge the
   promotion PR it opens; version, milestone roll, tag and notes are computed.

- One-page guide (shown on every new PR/issue): [org CONTRIBUTING](https://github.com/ajnacloud-ksj/.github/blob/main/CONTRIBUTING.md)
- Full rationale + automation reference: [`ajna-app-infra/docs/project-management-design.md`](https://github.com/ajnacloud-ksj/ajna-app-infra/blob/main/docs/project-management-design.md)

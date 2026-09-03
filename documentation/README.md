# Documentation

Working documents for the v1 rebuild of `aicounting-backend`: a Postgres-backed,
API-only Django project where a CPA firm is a first-class tenant.

| Document | What it holds |
|---|---|
| [00-current-state.md](00-current-state.md) | What the system does today, and the specific ways it is broken. The baseline. |
| [01-target-architecture.md](01-target-architecture.md) | Where it is going — package layout, tenancy model, config versioning, storage, auth. |
| [02-decisions.md](02-decisions.md) | Every call made and why, including the open ones marked ⚠️. |
| [03-api-v1-contract.md](03-api-v1-contract.md) | The `/api/v1/` surface. **This is the handoff to the React client.** |
| [04-execution-plan.md](04-execution-plan.md) | Phase-by-phase plan with verification steps. |

## Phase status

- [x] **0** — Documentation, `.gitignore` for the leaked secrets, branch
- [ ] **1** — Delete dead code, remove Document AI
- [ ] **2** — Postgres, local storage, API-only settings
- [ ] **3** — `v1/` package and the new schema
- [ ] **4** — Auth without SSO
- [ ] **5** — Config versioning replaces snapshots
- [ ] **6** — API v1 surface
- [ ] **7** — Rewire the extractor

Branch: `refactor/v1-multitenant`.

## Open questions

Answers change the schema, so they are worth resolving before Phase 3 lands.

1. **Should reviewers be scoped to a firm?** Today they are platform-level and
   see documents across every firm. Preserved as-is for now — see
   [02-decisions.md](02-decisions.md).
2. **Is the Django admin genuinely unwanted?** It is being removed along with the
   whole template layer. Reinstating it later means writing the admin classes
   fresh against the renamed models.

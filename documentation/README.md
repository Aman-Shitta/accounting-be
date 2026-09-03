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
- [x] **2** — Postgres, local storage, API-only settings
- [x] **3** — `v1/` package and the new schema
- [x] **4** — Auth without SSO
- [x] **5** — Config versioning replaces snapshots
- [ ] **6** — API v1 surface
- [ ] **7** — Rewire the extractor

Branch: `refactor/v1-multitenant`.

## Deviations from the plan

- **Azure AD SSO removal moved from Phase 2 to Phase 4.** `authentication/`,
  `user/accountant_views.py` and `user/admin_app/invite_views.py` all import
  `aicounting.msal_conf`, so deleting it in Phase 2 would have left the tree
  unimportable between commits. It goes with the auth rewrite in Phase 4, where
  its callers are replaced anyway. Azure *storage* removal happened in Phase 2
  as planned.

- **Phases 3 and 4 landed together.** Deleting the old apps required a
  replacement for `authentication/` to exist in the same commit, otherwise the
  tree would not import. The v1 models and the new auth stack ship as one
  change.

- **Phase 6 endpoints do not exist yet.** With the old apps gone, `/api/v1/`
  currently serves auth only. The resource endpoints land in Phase 6; the
  contract is already written in
  [03-api-v1-contract.md](03-api-v1-contract.md).

## Running it locally

```sh
docker compose up -d          # postgres + redis
cp .env.example .env          # fill in provider keys
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver
```

A local Postgres works just as well as the compose service — the settings read
`POSTGRES_*` from the environment either way.

## Open questions

Answers change the schema, so they are worth resolving before Phase 3 lands.

1. **Should reviewers be scoped to a firm?** Today they are platform-level and
   see documents across every firm. Preserved as-is for now — see
   [02-decisions.md](02-decisions.md).
2. **Is the Django admin genuinely unwanted?** It is being removed along with the
   whole template layer. Reinstating it later means writing the admin classes
   fresh against the renamed models.

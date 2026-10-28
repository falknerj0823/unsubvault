# Maintainer runbook

For people who maintain the project and its public repository.

## Continuous integration

`.github/workflows/ci.yml` runs on every push to `main` and every pull request, with read-only permissions and actions pinned by commit:

| Job | What it checks |
|---|---|
| `backend` | `check_catalog.py` (broker list valid), `gen_reference.py --check` (generated docs current), then the full test suite on a throwaway Postgres |
| `frontend` | `npm ci` and `npm run build` (type-checks the UI) |
| `compose` | `docker-compose.yml` is valid with `.env.example` |

Branch protection on `main` blocks force-pushes and deletion and requires these three jobs for pull requests. Owners can still push directly.

## Dependencies (Dependabot policy)

`.github/dependabot.yml`: monthly, grouped (one pull request per area), no major versions. **Python proposes patch releases only**, because minor releases of SQLAlchemy and the model SDKs broke the database migrations in CI.

- **Merge** a Dependabot pull request when all three CI jobs pass.
- **Close** one that fails; do not "fix forward" a broad group.
- **Upgrade minor or major versions by hand**, one at a time:
  1. new branch; change the pin in `backend/requirements.txt` (or `frontend/package.json` and the lockfile);
  2. `docker compose up --build -d`, then `docker compose exec backend python -m tests.run_all`;
  3. watch the first lines of `docker compose logs backend` for migration errors, and run through the manual smoke test in [testing.md](../testing.md);
  4. open a pull request, wait for CI, merge.
- Pick releases at least two weeks old, and keep transitive security pins (`starlette`, `httpcore`, `h11`) explicit.
- Upgrading Node (the frontend build image) or the Postgres major version is a separate, planned change; Postgres majors need a dump and restore.

## The broker catalog

`backend/app/data/brokers.json` is the hand-checked opt-out list. Brokers move their pages often.

- `python backend/scripts/check_catalog.py --links` requests every link and reports dead or redirected ones. Many broker sites answer 403 to automated checks; open those in a browser.
- Edit the entry (link, notes, sender domains), update `checked_at`, run the catalog check, and say in the pull request how you verified the link.
- Rules: https links to the broker's **own** page only; no affiliate or tracking parameters; no links inside notes; do not copy from a service that sells removal.

## The generated reference

`docs/reference.md` is generated from the code. After changing an API route, a database table, a setting, an audit event or `.env.example`:

```bash
docker compose cp .env.example backend:/.env.example
docker compose exec -T backend sh -c 'cd /app && python scripts/gen_reference.py' > docs/reference.md
```

CI fails if the committed file differs from what the code produces.

## Database migrations

Add a new Alembic file in `backend/alembic/versions/` (next number, `down_revision` set, a working `downgrade`). The `hardening` tests apply every migration down to nothing and back up, so a missing downgrade shows up in CI.

## Releasing

1. CI green on `main`; run the manual smoke test ([testing.md](../testing.md)).
2. Regenerate the reference, update the README if behaviour changed.
3. Tag the commit (`git tag -a vX.Y.Z -m "..."`, `git push --tags`) and write release notes: what changed, anything users must do (new `.env` values, a re-entered secret).
4. Dependabot opens its next pull requests on its own schedule.

## Incidents

**A secret was committed or shared.** Treat it as public the moment it left your machine. Rotate it first (rotation steps in [operations.md](operations.md#rotating-secrets); for provider secrets create a new one in the provider's console and delete the old). Only then deal with the repository.

**Sensitive data was committed to a repository that will be (or is) public.**
- A force-push does **not** reliably remove it: GitHub keeps a hidden `refs/pull/N/head` for every pull request forever, forks keep their own copies, and commits can stay reachable by hash for a while.
- For a repository that is still private: publish from a **fresh repository** containing a single clean commit, and archive the old one privately. This is what was done for the first public release.
- For one that is already public: rotate the secret, ask GitHub support to remove cached views and the pull-request refs, and assume the data was seen.
- Do not enable Dependabot on a private repository whose history you may later need to scrub.

**A vulnerability report arrives** (GitHub private vulnerability reporting is on). Reproduce it, fix it on a private branch, add a regression test to `backend/tests/hardening.py`, release, then publish the advisory.

**An audit found something.** Fix it with a test, and update [security-model.md](../security-model.md) if the claim it makes was wrong.

## Accounts and settings to keep

GitHub repository (branch protection, private vulnerability reporting, Dependabot), the Azure app registration used for testing (client secret expiry date), and `SECRET_KEY` for any install you want to keep readable.

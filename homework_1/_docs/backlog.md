# Backlog – ChoreFairness (Couple's Dashboard)

Source: `_docs/plan.md`
Current scaffold: project `config`, app `core` (`manage.py`, `config/settings.py`, `core/` exist, `core/models.py` empty, Django 6.1.1 via `uv`).
Note: `plan.md` names project `household` / app `chores`. Use existing `config` / `core` below to avoid re-scaffolding — mapping is `household`→`config`, `chores`→`core`.

Root command: `uv run manage.py runserver`
Sync command: `uv run manage.py makemigrations && uv run manage.py migrate`

## Tasks

### 1. Models in `core/models.py`
Define exactly per plan:
- `Chore`: `name` (CharField max 100), `default_owner` (CharField max 20, choices `you`/`partner`), `created_at` (auto_now_add).
- `LogEntry`: `chore` (FK Chore CASCADE), `owner` (CharField max 20, choices `you`/`partner`), `effort_rating` (Integer 1–10 via validators), `date` (DateField default `timezone.now`).
Accept: `uv run manage.py check` passes.

### 2. Admin in `core/admin.py`
Register both models with `list_display` (`Chore`: name, default_owner, created_at; `LogEntry`: chore, owner, effort_rating, date).
Accept: visible/editable in `/admin/`.

### 3. Migrations
Run `uv run manage.py makemigrations core && uv run manage.py migrate`.
Accept: `db.sqlite3` created, no pending migrations (`showmigrations` clean).

### 4. Forms in `core/forms.py`
- `LogEntryForm` (ModelForm: chore, owner, effort_rating) with `clean_effort_rating` rejecting blank/<1/>10.
- `ChoreForm` (ModelForm: name, default_owner).
Accept: invalid rating fails validation; empty chore list handled by view message.

### 5. Views + URLs
- `core/views.py`: `dashboard` (`/`), `log_list` (`/log/` GET list last 20 desc + POST add), `chore_list` (`/chores/` GET list + POST add/edit default_owner). All with `@require_http_methods(["GET","POST"])`, standard POST-redirects, no REST API.
- `core/urls.py` + include in `config/urls.py`.
- Dashboard logic: last 30 days grouped by date+owner, sum `effort_rating`, fill missing dates with 0, pass `dates` (YYYY-MM-DD) + `series` (`you`/`partner`); fairness = `abs(y-p)/max(y,p,1)*100` 2 decimals, or "No data yet" if both 0.
Accept: routes resolve; POST redirects; cascade delete Chore→LogEntry works.

### 6. Templates
- `core/templates/core/base.html` (Bootstrap 5 CDN).
- `dashboard.html`: Chart.js CDN line chart with 2 datasets + fairness % display (works empty).
- `log_list.html`: form on top (chore dropdown, owner dropdown, rating 1–10 number input, submit) + table of last 20; if no chores show "Add a chore first via /chores/".
- `chore_list.html`: add form at top + list with text input + owner dropdown edit.
Accept: matches plan Frontend section.

### 7. Verify + share
- Manual pass of plan Acceptance Criteria: `/` chart renders, `/chores/` add/edit works, `/log/` logging works, dashboard updates on refresh, fairness shows 2 decimals.
- Share: `uv run manage.py runserver 0.0.0.0:8000` + `ngrok http 8000`, send URL to partner (free tier ~2h session).
Accept: all 5 checkboxes in plan pass.

## Suggested order
1 → 2 → 3 → 4 → 5 → 6 → 7

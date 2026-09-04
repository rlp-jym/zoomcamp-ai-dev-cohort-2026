# plan.md – ChoreFairness (Couple's Dashboard)

## Project Context
- **User**: Couple/partners (high-trust, low-friction).
- **Primary goal**: Track perceived effort to prevent resentment, using trend lines over time.
- **Effort definition**: Subjective rating (1–10) per chore instance.
- **Assignment model**: Each chore has a default owner, but owners can swap (manual edit).
- **Fairness view**: Trend lines comparing cumulative effort over days/weeks.

## MVP Scope (Web Dashboard)
- **Chore list** with default owner field (editable).
- **Daily log** – record chore done + subjective effort rating.
- **Trend view** – line chart (30 days) showing each partner's cumulative effort.
- **Fairness indicator** – percentage difference displayed alongside trend.

## Tech Stack
- **Package manager**: `uv`.
- **Database**: SQLite (default Django `db.sqlite3`).
- **Backend**: Django (ORM, admin).
- **Frontend**: Django templates + Bootstrap 5 CDN + Chart.js CDN.
- **Root command**: `uv run manage.py runserver`
- **Sync command**: `uv run manage.py makemigrations && uv run manage.py migrate`

## Data Models (exact fields)
Create two models in `models.py`:

**Chore**
- `id` (AutoField)
- `name` (CharField, max_length=100)
- `default_owner` (CharField, max_length=20, choices=[('you','You'),('partner','Partner')])
- `created_at` (DateTimeField, auto_now_add=True)

**LogEntry**
- `id` (AutoField)
- `chore` (ForeignKey to Chore, on_delete=CASCADE)
- `owner` (CharField, max_length=20, choices=[('you','You'),('partner','Partner')]) – *who actually did it*
- `effort_rating` (IntegerField, min_value=1, max_value=10)
- `date` (DateField, default=timezone.now().date – *store only date, not time*)

**Admin**: Register both models with `list_display`.

## URLs & Views (exact routing)
- `/` → `dashboard` view (trends).
- `/log/` → `log_list` view (GET list + POST to add new entry). Single form on this page.
- `/chores/` → `chore_list` view (GET list + POST to add/edit default_owner).

**No REST API** – use standard Django POST redirects.

## Dashboard Logic (strict)
- Query last **30 days** of `LogEntry` grouped by `date` and `owner`.
- Sum `effort_rating` per owner per day.
- Pass two lists: `dates` (strings YYYY-MM-DD) and `series` = {'you': [daily sums], 'partner': [daily sums]}.
- Fill missing dates with `0`.
- **Fairness indicator**: `total_you` vs `total_partner`. If both 0, show "No data yet". Else, show `abs(total_you - total_partner) / max(total_you, total_partner, 1) * 100` as "% imbalance" with 2 decimals.

## Frontend (prescriptive)
- Base template `base.html` with Bootstrap 5 CDN.
- Chart: Chart.js CDN, line chart with two datasets.
- On `/log/`: table of last 20 entries (descending). Above it: dropdown for `chore`, dropdown for `owner`, number input (1–10) for `rating`, and submit button.
- On `/chores/`: list all chores with text input + dropdown to change default owner. Add chore form at top.

## Edge Cases (handle explicitly)
- Deleting a Chore cascades to LogEntry.
- `effort_rating` validation: reject if blank, <1, or >10 (form clean).
- If no chores exist, show "Add a chore first via /chores/" on `/log/`.
- Use `@require_http_methods(["GET", "POST"])` decorators.

## Implementation Order (strict sequence)
1. `uv run django-admin startproject household .`
2. Create app: `uv run python manage.py startapp chores`
3. Write `models.py` exactly as above.
4. Run `makemigrations` and `migrate`.
5. Write admin registration.
6. Write forms (ModelForm for LogEntry, ModelForm for Chore).
7. Write views (dashboard, log_list, chore_list).
8. Create templates (base.html, dashboard.html, log_list.html, chore_list.html).
9. Wire URLs (app urls + project urls).
10. Run server, test manually.

## Acceptance Criteria (stop when all pass)
- [ ] Visiting `/` shows a line chart (even if empty).
- [ ] Visiting `/chores/` allows adding a chore and changing its default owner.
- [ ] Visiting `/log/` allows logging a rating for any existing chore.
- [ ] After logging, the dashboard chart updates on refresh.
- [ ] The fairness percentage displays correctly with 2 decimal places.

## Sharing Instructions (for the user after build)
- Run server locally: `uv run manage.py runserver 0.0.0.0:8000`
- Download ngrok from https://ngrok.com (free, no signup required).
- Unzip and run: `./ngrok http 8000` (or `ngrok.exe http 8000` on Windows).
- Copy the public URL (e.g., `https://abc123.ngrok.io`) and send to partner.
- Both can open that URL simultaneously on any device to log chores and view trends.

**Note:** ngrok free tier session expires after 2 hours – restart it for longer demos.
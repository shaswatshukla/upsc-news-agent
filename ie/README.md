# Indian Express daily UPSC brief

This agent runs on GitHub Actions at 09:00 India time (03:30 UTC), independently of the PIB report. It requires no local PC or per-run approvals. GitHub can delay scheduled starts.

It reads official Indian Express RSS feeds for Explained, Editorials, Columns, India, Economy, World, and Science. It considers the past 48 hours so a morning run includes yesterday's news, selects up to 25 readable unseen articles, and sends a single Gemini batch to produce up to 12 concise UPSC items. Summaries are original study notes with source links; editorial opinions must be distinguished from reported facts. Stories explicitly marked subscription-only, teasers, and unreadable pages are skipped. No browser cookies or subscription bypass are used.

Email subject: `Daily Indian Express UPSC Brief - YYYY-MM-DD`. Includes an Overview, GS papers, syllabus topic, factual summary, Prelims pointers, Mains angle, and links in a PDF. No email is sent for an empty new/relevant batch.

Actions secrets: `GEMINI_API_KEY`, `EMAIL_SENDER` (or `SMTP_USER`), `EMAIL_APP_PASSWORD` (or `SMTP_PASSWORD`), `EMAIL_RECIPIENT` (or `EMAIL_TO`). Defaults to Gmail SSL SMTP on port 465 and `gemini-3.1-flash-lite`, a free-tier model. Set repository variable `IE_GEMINI_MODEL` to override it. Temporary 429/5xx Gemini failures are retried. Free-tier quotas and GitHub Actions included minutes still apply.

Processed article IDs are committed to `ie/seen_article_ids.json` (last 500). PDFs are retained as workflow artifacts for seven days. Do not put credentials in repository files. If SMTP succeeds but the history commit fails, retrying can repeat the email; inspect the run before retrying. Concurrent runs of this job are serialized.

The legacy Indian Express `src/` code remains for reference; the active workflow uses `ie/agent.py`. PIB continues separately through `.github/workflows/daily.yml`.

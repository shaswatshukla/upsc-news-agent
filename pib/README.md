# Daily PIB UPSC email

GitHub Actions runs `.github/workflows/daily.yml` at 03:30 UTC (09:00 Asia/Kolkata) daily, without a local PC or per-run approvals. GitHub may delay scheduled starts; email arrives after processing.

Uses official PIB RSS, Gemini, ReportLab, and Gmail SSL SMTP. Repository Actions secrets: `GEMINI_API_KEY`, `EMAIL_SENDER`, `EMAIL_APP_PASSWORD`, `EMAIL_RECIPIENT`. Existing `SMTP_USER`, `SMTP_PASSWORD`, and `EMAIL_TO` secrets are accepted as fallbacks. No secrets belong in source control. Optional variable `PIB_GEMINI_MODEL` selects a model; default is `gemini-flash-latest`. Gemini free-tier quotas and GitHub Actions included minutes apply; no paid service is enabled by this workflow.

The workflow commits `pib/seen_prids.json` after successful processing and stores PDFs as artifacts for 7 days. Empty batches or no relevant releases send no email. Failed runs do not mark fetched releases as processed. Concurrent runs are serialized. If an email sends but saving history fails, a retry can repeat that email: check the workflow logs before retrying.

View Actions for delivery status or use Run workflow to run manually. Disable the old Windows scheduled task after a successful cloud test to avoid duplicate local and cloud reports. The old Indian Express scheduled workflow has been replaced with PIB; its source files remain.

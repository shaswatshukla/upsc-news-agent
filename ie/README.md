# Daily Indian Express UPSC brief

Runs independently of PIB at 09:00 India time (03:30 UTC) using GitHub Actions. No local PC or per-run approvals. Scheduled starts may be delayed by GitHub.

The agent tries official Indian Express RSS feeds for Explained, Editorials, Columns, India, Economy, World, and Science, considering recent unseen stories from the past 48 hours. Publicly readable articles receive original concise UPSC notes. Subscription-only and incomplete stories are skipped.

**GitHub's servers currently receive HTTP 403 from Indian Express.** If all publisher feeds are unavailable, the agent uses Google's public News RSS for Indian Express headlines. This fallback does not fetch or bypass blocked or subscription-only articles. The email subject includes [Headlines], and the PDF prominently says HEADLINE-ONLY. Its factual summary is the supplied headline with an access limitation, its Prelims facts list is empty, and its Mains section contains suggested syllabus questions rather than claims about an unseen article. Links go through Google News to the publisher. Full-article access automatically resumes if publisher access becomes available.

Email subject: Daily Indian Express UPSC Brief - YYYY-MM-DD (with [Headlines] in fallback mode). Up to 25 readable articles or indexed headlines go into one Gemini batch; up to 12 relevant items are selected.

Actions secrets: GEMINI_API_KEY, EMAIL_SENDER (or SMTP_USER), EMAIL_APP_PASSWORD (or SMTP_PASSWORD), EMAIL_RECIPIENT (or EMAIL_TO). Gmail SSL SMTP on port 465. Default model gemini-3.1-flash-lite; variable IE_GEMINI_MODEL can override. Temporary 429/5xx Gemini failures are retried. Free-tier quotas and GitHub Actions included minutes apply.

Processed source identifiers and normalized headline identifiers are saved to ie/seen_article_ids.json, retaining the last 500 identifiers. PDFs are kept as workflow artifacts for 7 days. Empty new/relevant batches send no email. A history-save failure after SMTP success can cause a repeat email on retry; inspect logs before retrying.

The legacy src/ agent remains for reference. The active Indian Express workflow uses ie/agent.py. PIB continues through .github/workflows/daily.yml.

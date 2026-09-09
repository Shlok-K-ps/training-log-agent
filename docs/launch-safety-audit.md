# Launch safety audit — 2026-09-10

Repository: <https://github.com/Shlok-K-ps/training-log-agent>

This records the disposition of the eight findings raised against commit
`4373c13`. “Fixed” means covered by deterministic tests in this repository; it
does not mean the product has completed legal, clinical, anti-doping or security
review.

| Finding | Status | Resolution |
|---|---|---|
| OAuth state tamper alias | Fixed | Verification rejects non-canonical base64 encodings as well as invalid HMAC bytes. |
| Athlete can self-approve supplements | Fixed | Scheduling requires an exact operator-configured regimen, named approver and verified-batch marker; athlete fields cannot grant authority. Named 2026 WADA SARM terms are blocked as defense in depth. |
| Allergy category mismatch | Fixed | Recognized categories map to foods; unsupported categories stop the plan for manual review. |
| Saved places can fall back to plaintext | Fixed | Reads and writes fail closed without the encryption key; older plaintext rows migrate when a key is available. |
| Free Render plan cannot provide durable always-on operation | Open deployment choice | Production requires a paid always-on disk-backed service or external database and scheduler. No paid plan was selected automatically. |
| Self-reported targets described as approved | Fixed | Unreviewed targets are labelled athlete-reported; approval language requires a recorded professional source. |
| Injury flag did not block calendar booking | Fixed | An open flag blocks proposals and re-checks before confirmation, including stale codes. |
| Sensitive messages sent through a free model tier | Open launch blocker | Canonical address/OAuth/confirmation commands now stay local, and calendar titles are never requested. Other athlete messages still need a suitable production data-processing agreement. |

## Release gate

Do not call the deployment production-ready until both open items are resolved:

1. choose durable storage plus an always-on scheduler; and
2. use a parsing-provider account and contract appropriate for athlete health,
   nutrition and training data.

The code-level regression suite contains 245 offline tests.

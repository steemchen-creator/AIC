# Branch Protection Recommendations

Status: ADMIN_SETUP_REQUIRED. This PR does not change repository admin settings.

One-time administrator checklist:

- Protect main; require a PR; block direct pushes, force pushes and branch deletion.
- Require Governance baseline, Backend tests, Desktop build and
  AIC Development Governance Gate. Include any additional organization/repository checks.
- Require independent review; dismiss stale approvals after new commits; require
  approval of the latest push and resolution of blocking review discussions.
- Restrict bypass actors; do not grant the engineering bot a protection bypass.
- Protect automation/dev-state against force/deletion and non-orchestrator writers.
- Configure the aic-development-governance environment to allow trusted main only.
- Restrict its dedicated token/API secret to the trusted workflow and approved actors.
- Establish a Chairman escalation recipient/channel and token revocation procedure.

The deterministic architecture gate complements GitHub approval enforcement; neither
replaces the other. When settings cannot be read or enforced, automatic merge must
remain disabled. Enabling ordinary repository auto-merge is not required for the
expected-SHA squash API and is not performed by DEV-GOV-001.

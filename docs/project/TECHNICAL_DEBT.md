# Open Technical Debt Registry

Static deployment debt is listed here. Runtime Architecture Results append structured
`TechnicalDebtRegistry` entries in the state branch, keyed by immutable debt identity.
Required fields: debt_id, origin_spec, description, severity, blocking, target_phase, status.

| Debt ID | Origin | Description | Severity | Blocking | Target phase | Status |
|---|---|---|---|---|---|---|
| GOV-009-PROTECTION | SPEC-009 | Configure main protection, required approvals/checks and no bypass. | HIGH | No for reviewed SPEC-009 closeout; activation prerequisite for automation | Chairman setup | OPEN |
| DEV-GOV-BRIDGE-SETUP | DEV-GOV-001 | Authorize an external Work consumer or API credential/model and review principal. | MEDIUM | No for bootstrap implementation; blocks autonomous review delivery | Chairman setup | OPEN |
| DEV-GOV-DEPLOYMENT-SETUP | DEV-GOV-001 | Configure protected deployment environment, fingerprinted non-secret policy, identities and external activation switch after reviewed closeout. | MEDIUM | No for implementation review; activation prerequisite | Chairman setup | OPEN |
| DEV-GOV-ACTIONS-RUNTIME | DEV-GOV-001 | Upgrade GitHub actions that declare the deprecated Node 20 runtime. | LOW | No; GitHub currently forces Node 24 and all checks pass | Maintenance | OPEN |
| SPEC-010-INTRADAY | SPEC-010 | Add an approved intraday observation engine before treating `T` horizon as more than recorded holding intent. | LOW | No; V1 daily/PIT execution remains deterministic | Future market-data SPEC | OPEN |
| SPEC-010-TARGET-STATE | SPEC-010 | Add explicit consumed-target state for strategy-specific multi-stage partial exits. | LOW | No; V1 ordered target evaluation is deterministic | Future Trade Plan revision | OPEN |
| SPEC-010-OUTCOME-PROJECTION | SPEC-010 | Automate outcome monetary projection from authoritative portfolio/execution ledgers. | LOW | No; V1 requires explicit ledger-derived inputs and keeps P&L authority unchanged | Future reporting SPEC | OPEN |

These entries are implementation-reported limitations, not a claim that Architecture
Review has accepted DEV-GOV-001 with non-blocking debt. Unknown approval remains unknown.

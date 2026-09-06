# AI Budget and Delivery Guard

Defaults: 3 architecture-review rounds/work item, 5 architecture calls/work item,
2 new SPEC requests/day (UTC), 30-minute duplicate-event window. Values are
configuration, not investment policy.

A durable task identity and budget reservation precede any external delivery.
Concurrent writers compete on CAS; only the winner may call a model. Restart with
a RESERVED task does not resend an uncertain request. Known-unavailable bridges
release unused budget and remain WAITING; network ambiguity retains reservation.

Normal planned cycle is SPEC generation + review; only failed review requires FIX
and another round. Limits record reason codes and Chairman escalation. Ordinary
progress, CI polling, HEAD discovery, gate evaluation and closeout make no LLM call.

HTTP reads use at most three attempts by default with bounded backoff and explicit
timeout. Writes are not blindly retried. A failed external model call is blocked
after one attempt; operator reconciliation is required before another billable call.

Metrics include calls/spec, loops, duplicate calls avoided, limit hits, merge attempts,
failures and stage-duration intervals. Missing durations/costs remain unknown, not zero.

# ChatGPT / Codex Bridge

V1 supports MANUAL_BRIDGE, CHATGPT_WORK_EVENT_BRIDGE and OPENAI_API_BRIDGE.

Manual mode prepares durable structured requests and explicitly enters
WAITING_FOR_ARCHITECTURE_REVIEW_BRIDGE. It does not claim a ChatGPT review occurred.
The GitHub event adapter posts an idempotent task signal to a PR comment or issue.
An independently authorized Work consumer subscribes to that signal and reads the
immutable task/context; no undocumented Work API is invented.

The API adapter uses a bounded Responses request with a strict result schema,
store=false and explicit model configuration. No model or paid API key is implicitly
selected. Refusal, incomplete response, invalid schema, wrong work item or wrong SHA
fail closed. Structured output is not itself Chairman authority. API review ingestion
uses a distinct allowlisted architecture principal; next-SPEC proposals are archived,
not execution authorization. A separately reviewed, protected standard-work
standard_work_execution_authorization can delegate registration/publication to that
principal; the delivered policy has no such delegation. FIX responses are persisted
as immutable Markdown/JSON and become scoped engineering tasks.

Available API token usage is recorded in durable delivery events and metrics. Missing
usage/cost is unknown, never zero or an invented price. No automatic paid-call retry
occurs after an uncertain transport or crash outcome.

The engineering adapter creates a task artifact and GitHub issue/comment for SPEC_READY
or FIX_READY. The consumer reads project memory/current SPEC/FIX and creates code,
tests, docs, REVIEW and a Draft PR. It has no architecture-approval or merge authority.

Official interface references:
[OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[GitHub merge API](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request),
[Git reference updates](https://docs.github.com/en/rest/git/refs#update-a-reference).

## Operations

Protected workflow commands: initialize, register, event, attach-pr, review, ready,
merge, closeout, memory-update and reconcile. Payloads are schema-validated data;
GitHub actor supplies identity. Review ingestion requires ARCH_REVIEW_STARTED followed
by a SHA-bound result. Pipeline events/CI can reconcile without ordinary user forwarding.

No external Work subscription, OpenAI credential, live bot or auto-merge permission
is activated by this PR. See the Chairman setup checklist.

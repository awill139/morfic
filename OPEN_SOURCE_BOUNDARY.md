# Open-source / hosted boundary

## Open-source runtime

The public runtime contains the local data plane:

- desktop shell and Marketplace
- local app storage/lifecycle
- catalog acquisition and Git deployment
- container/host execution policy
- generated-app hosting
- surgical patch application
- validation, rollback, timeout/cancellation
- OpenAI/Anthropic provider clients
- community orchestration prompts
- Official-service API client and structured telemetry client

A community build can operate entirely with a user's own provider credentials.

## Private official orchestrator

The official service owns:

- managed model credentials and routing
- official task/prompt registry
- intent and repository planning
- generated-app architecture/blueprint planning
- modification impact planning
- repair intelligence
- tester authentication
- aggregate compatibility, execution and model-call telemetry

The service proposes decisions. The open runtime enforces them locally.

## Official BYOK boundary

Official BYOK does not send the user's OpenAI/Anthropic secret to Morfic. Planning remains hosted, while source-heavy calls execute locally using the public runtime/provider clients. The server receives only structured call metadata/outcomes by default: task, provider/model label, sizes, latency, environment, success/failure and bounded error information.

This means Official BYOK deliberately uses the open/community source-generation prompts for delegated source-heavy operations; proprietary hosted prompts remain server-side for hosted planning operations.

## Privacy defaults

Official mode does not send API keys, app database contents, arbitrary documents or local files. It does
send, by default, usage logs for each AI call and app event: task, provider/model, sizes, token counts,
latency, outcome, bounded error text, environment and a random install ID.

Two user-visible switches (AI Settings → Privacy) control this:

- **Share usage data** (default on). Off = no events and no per-call logs are sent.
- **Include prompt and response text** (default on; applies only while sharing is on). Adds excerpts of the
  prompts sent to and the responses received from the AI, redacted for common secret formats and capped at
  20,000 characters per side, redacted client-side before sending.

The backend additionally keeps content only when its operator enables `PS_CAPTURE_CONTENT`. Managed AI
requests are not telemetry: the hosted service necessarily receives them to answer, and the sharing switches
do not change that (they do control whether the service may retain the text).

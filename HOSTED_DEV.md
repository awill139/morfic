# Hosted-mode development

Run the private orchestrator at `http://127.0.0.1:8770`, then start the runtime and select **Official** in AI Settings.

## Managed

Choose **Included AI**, enter a configured tester invite code once, and save. All model calls use the private orchestrator.

## Official BYOK

Choose **Use my API key**, select OpenAI or Anthropic, and enter the corresponding key in its provider card. The invite/device token still authenticates planning and telemetry to the official orchestrator, while source-heavy generation/editing calls go directly to the selected provider.

The provider key remains local and is not included in `/v1/task`, `/v1/model-events`, or `/v1/events` requests.

Useful environment overrides:

- `MORFIC_OFFICIAL_URL`
- `MORFIC_OFFICIAL_AI_MODE=managed|byok`
- `MORFIC_OFFICIAL_BYOK_PROVIDER=openai|anthropic`

(The legacy `PERSONAL_SOFTWARE_*` spellings still work.)

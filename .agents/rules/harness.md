# Universal Agent Harness Directives
- Repository: `Job-Applications`
- Cognitive Engine: `fleet-rationalization/harness`
- CLI Entrypoint: `python3 -m harness.cli`
- Telemetry: Emits to DevEx-Intel (`docs/devex-metrics.json` & Kafka `devex.telemetry.tokens`)
- Zero-mock policy: Strictly enforced via ArchAdvisor.
- Token Economy: Run targeted grep/slices, offload review to local Ollama.

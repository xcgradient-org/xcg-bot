# ReflectionService

> God node · 28 connections · `/home/sterry/Desktop/xcgradient-org/xcg-bot/reflection.py`

## Connections by Relation

### calls
- [[main()]] `INFERRED`
- [[.test_extract_text_returns_first_non_empty_part()]] `INFERRED`
- [[.test_extract_text_supports_openai_chat_payload()]] `INFERRED`
- [[.test_verify_startup_accepts_installed_model()]] `INFERRED`
- [[.test_verify_startup_raises_if_model_missing()]] `INFERRED`
- [[.test_verify_startup_accepts_openai_compatible_model()]] `INFERRED`
- [[.test_generate_json_response_parses_json_payload()]] `INFERRED`
- [[.test_generate_json_response_extracts_json_from_chatty_model_output()]] `INFERRED`
- [[.test_generate_reflection_raises_on_empty_response()]] `INFERRED`
- [[.test_build_fallback_reflection_includes_tasks_and_notes()]] `INFERRED`

### contains
- [[reflection.py]] `EXTRACTED`

### method
- [[.generate_json_response()]] `EXTRACTED`
- [[.verify_startup()]] `EXTRACTED`
- [[.generate_reflection()]] `EXTRACTED`
- [[._model_request()]] `EXTRACTED`
- [[._extract_text()]] `EXTRACTED`
- [[._post_json()]] `EXTRACTED`
- [[._gemini_text()]] `EXTRACTED`
- [[._gemini_json()]] `EXTRACTED`
- [[._headers()]] `EXTRACTED`
- [[._get_json()]] `EXTRACTED`
- [[._ollama_request()]] `EXTRACTED`
- [[._openai_request()]] `EXTRACTED`
- [[.build_fallback_reflection()]] `EXTRACTED`
- [[._parse_json_text()]] `EXTRACTED`
- [[.__init__()]] `EXTRACTED`

### uses
- [[XCGradientOSBot]] `INFERRED`
- [[Settings]] `INFERRED`

---

*Part of the graphify knowledge wiki. See [[index]] to navigate.*
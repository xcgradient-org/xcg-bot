# Graph Report - xcg-bot  (2026-04-18)

## Corpus Check
- 10 files · ~12,492 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 245 nodes · 511 edges · 8 communities detected
- Extraction: 78% EXTRACTED · 22% INFERRED · 0% AMBIGUOUS · INFERRED: 113 edges (avg confidence: 0.79)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Notion - NotionService|Notion - NotionService]]
- [[_COMMUNITY_Log Command - log_command.py|Log Command - log_command.py]]
- [[_COMMUNITY_Test Xcg Bot - _finalize_log()|Test Xcg Bot - _finalize_log()]]
- [[_COMMUNITY_Reflection - ReflectionService|Reflection - ReflectionService]]
- [[_COMMUNITY_Task Command - task_command.py|Task Command - task_command.py]]
- [[_COMMUNITY_Main - XCGradientOSBot|Main - XCGradientOSBot]]
- [[_COMMUNITY_Meeting Command - meeting_command.py|Meeting Command - meeting_command.py]]
- [[_COMMUNITY_Meetings - meetings.py|Meetings - meetings.py]]

## God Nodes (most connected - your core abstractions)
1. `NotionService` - 60 edges
2. `ReflectionService` - 28 edges
3. `_finalize_log()` - 16 edges
4. `_format_message()` - 11 edges
5. `ReflectionServiceTests` - 10 edges
6. `NotionServiceTests` - 10 edges
7. `MeetingCommandTests` - 9 edges
8. `XCGradientOSBot` - 8 edges
9. `main()` - 7 edges
10. `_normalize_payload()` - 7 edges

## Surprising Connections (you probably didn't know these)
- `_build_state()` --calls--> `current_context()`  [INFERRED]
  /home/sterry/Desktop/xcgradient-org/xcg-bot/task_command.py → /home/sterry/Desktop/xcgradient-org/xcg-bot/log_command.py
- `Settings` --uses--> `NotionService`  [INFERRED]
  /home/sterry/Desktop/xcgradient-org/xcg-bot/main.py → /home/sterry/Desktop/xcgradient-org/xcg-bot/notion.py
- `Settings` --uses--> `ReflectionService`  [INFERRED]
  /home/sterry/Desktop/xcgradient-org/xcg-bot/main.py → /home/sterry/Desktop/xcgradient-org/xcg-bot/reflection.py
- `test_load_settings_uses_legacy_notion_env_names()` --calls--> `load_settings()`  [INFERRED]
  /home/sterry/Desktop/xcgradient-org/xcg-bot/tests/test_xcg_bot.py → /home/sterry/Desktop/xcgradient-org/xcg-bot/main.py
- `XCGradientOSBot` --uses--> `NotionService`  [INFERRED]
  /home/sterry/Desktop/xcgradient-org/xcg-bot/main.py → /home/sterry/Desktop/xcgradient-org/xcg-bot/notion.py

## Communities

### Community 0 - "Notion - NotionService"
Cohesion: 0.08
Nodes (5): NotionService, Query a data source directly by its pre-resolved ID, bypassing databases.retriev, Return the highest existing sequence number for project+role tasks, or 0 if none, NotionServiceTests, NotionTaskCreationTests

### Community 1 - "Log Command - log_command.py"
Cohesion: 0.1
Nodes (19): add_blocker(), back(), BlockerModal, BlockerRoleSelect, BlockerSelectionView, _build_review_message(), confirm(), current_context() (+11 more)

### Community 2 - "Test Xcg Bot - _finalize_log()"
Cohesion: 0.09
Nodes (16): UrgentBlockerModal, build_blocker_message(), _finalize_log(), _mention_for_role(), post_blocker(), rewrite_blocker_message(), skip_blocker(), compute_updated_streak() (+8 more)

### Community 3 - "Reflection - ReflectionService"
Cohesion: 0.15
Nodes (4): Call the local `gemini` CLI and return its text output., Call the Gemini CLI asking for JSON output and parse the result., ReflectionService, ReflectionServiceTests

### Community 4 - "Task Command - task_command.py"
Cohesion: 0.12
Nodes (14): _build_message(), _build_state(), _CancelCreateButton, _clean_description(), _ConfirmCreateButton, _explicit_task_count_requested(), _fallback_task_descriptions(), _normalize_task_descriptions() (+6 more)

### Community 5 - "Main - XCGradientOSBot"
Cohesion: 0.13
Nodes (13): register_blocker_command(), register_log_command(), configure_logging(), default_llm_settings(), load_environment(), load_settings(), main(), Settings (+5 more)

### Community 6 - "Meeting Command - meeting_command.py"
Cohesion: 0.16
Nodes (11): _build_confirmation(), _build_mentions(), _format_datetime(), MeetingModal, _normalize_attendees(), _normalize_date_iso(), _normalize_payload(), _title_suggestion() (+3 more)

### Community 7 - "Meetings - meetings.py"
Cohesion: 0.25
Nodes (17): _attendees(), _checkbox(), _date(), _format_datetime(), _format_message(), _location(), _meeting_datetime(), _meeting_type() (+9 more)

## Knowledge Gaps
- **4 isolated node(s):** `Query a data source directly by its pre-resolved ID, bypassing databases.retriev`, `Return the highest existing sequence number for project+role tasks, or 0 if none`, `Call the local `gemini` CLI and return its text output.`, `Call the Gemini CLI asking for JSON output and parse the result.`
  These have ≤1 connection - possible missing edges or undocumented components.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `NotionService` connect `Notion - NotionService` to `Test Xcg Bot - _finalize_log()`, `Main - XCGradientOSBot`?**
  _High betweenness centrality (0.352) - this node is a cross-community bridge._
- **Why does `_finalize_log()` connect `Test Xcg Bot - _finalize_log()` to `Notion - NotionService`, `Log Command - log_command.py`, `Reflection - ReflectionService`?**
  _High betweenness centrality (0.146) - this node is a cross-community bridge._
- **Why does `ReflectionService` connect `Reflection - ReflectionService` to `Main - XCGradientOSBot`?**
  _High betweenness centrality (0.140) - this node is a cross-community bridge._
- **Are the 15 inferred relationships involving `NotionService` (e.g. with `Settings` and `XCGradientOSBot`) actually correct?**
  _`NotionService` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `ReflectionService` (e.g. with `Settings` and `XCGradientOSBot`) actually correct?**
  _`ReflectionService` has 12 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `_finalize_log()` (e.g. with `.set_task_completion()` and `.query_remaining_tasks()`) actually correct?**
  _`_finalize_log()` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `_format_message()` (e.g. with `.on_submit()` and `.test_format_message_includes_notes_when_present()`) actually correct?**
  _`_format_message()` has 2 INFERRED edges - model-reasoned connections that need verification._
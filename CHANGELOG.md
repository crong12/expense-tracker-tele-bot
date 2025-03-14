# Changelog

All notable changes to the bot will be documented here.

<br/>

## 1.3.2 - 2025-03-14

### Fixed
- Date retrieval logic &ndash; actual dates parsed from relative dates by the LLM (e.g. today -> 2025-03-14) are now more accurate.

- Image captions provided by the user are now taken into account when processing image inputs. 


## 1.3.1 - 2025-03-12

### Changed
- Agent workflow &ndash; agent now able to respond to simple/ follow-up queries (that do not require access to database) directly. Refer to workflow graph for more details.

- Agent workhorse &ndash; no longer using `gemini-2.0-flash-lite` due to low rate limits (5 RPM is not sufficient for an agentic workflow that requires multiple LLM calls within a few seconds). Now using `gpt-4o-mini`!

### Fixed
- Cleaned up some unused dependencies in requirements.txt, although it's nowhere near clean enough.


## 1.3 - 2025-03-11

### Added
- AI agent workflow (using LangGraph) for LLM-powered expense analytics.

- LangSmith tracing for agent observability and evaluation.

### Fixed
- Incorrect expense-matching regex logic.


## 1.2 - 2025-03-08

### Added
- Expense deleting functionality.

- Multimodal input (parsing expense from image input).


## 1.1 - 2025-03-04

### Added
- Expense editing functionality.

### Fixed
- Incorrect fallback logic during `handle_confirmation` state.

- Other minor fixes (e.g. formatting).


## 1.0 - 2025-02-27

- Here we go!

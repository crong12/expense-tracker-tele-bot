# Changelog

All notable changes to the bot will be documented here.

<br/>

## 1.4 &ndash; 2025-04-21

### Added
- Option to export expenses for current month only or all expenses so far.

### Changed
- Formatting of parsed expense details &ndash; enforce 2 decimal places for amounts, and title case for category & descriptions. Simplifies/ shortens prompts as the LLM doesn't need to worry about formatting its output.
- Agent workhorse for final expense analysis output. Previously used `gpt-4o-mini`, but realised it was summing expenses wrongly! Now using `o4-mini`. Funny how a simple swap of letters can mean a world of difference in performance.

### Fixed
- Exported expenses now sorted by date.


## 1.3.4 &ndash; 2025-03-29

### Changed
- Output message from expense analysis (no longer hardcoding a "do you have any questions? Feel free to ask!" question at the end since the LLM already does that on its own).

### Fixed
- Bug in expense editing logic that caused the bot to be stuck in the expense editing state.


## 1.3.3 &ndash; 2025-03-14

### Changed
- Refactored to use Supabase instead of Google Cloud SQL for cost optimisation purposes (read: I am poor).


## 1.3.2 &ndash; 2025-03-14

### Fixed
- Date retrieval logic &ndash; actual dates parsed from relative dates by the LLM (e.g. today -> 2025-03-14) are now more accurate.

- Image captions provided by the user are now taken into account when processing image inputs. 


## 1.3.1 &ndash; 2025-03-12

### Changed
- Agent workflow &ndash; agent now able to respond to simple/ follow-up queries (that do not require access to database) directly. Refer to workflow graph for more details.

- Agent workhorse &ndash; no longer using `gemini-2.0-flash-lite` due to low rate limits (5 RPM is not sufficient for an agentic workflow that requires multiple LLM calls within a few seconds). Now using `gpt-4o-mini`!

### Fixed
- Cleaned up some unused dependencies in requirements.txt, although it's nowhere near clean enough.


## 1.3 &ndash; 2025-03-11

### Added
- AI agent workflow (using LangGraph) for LLM-powered expense analytics.

- LangSmith tracing for agent observability and evaluation.

### Fixed
- Incorrect expense-matching regex logic.


## 1.2 &ndash; 2025-03-08

### Added
- Expense deleting functionality.

- Multimodal input (parsing expense from image input).


## 1.1 &ndash; 2025-03-04

### Added
- Expense editing functionality.

### Fixed
- Incorrect fallback logic during `handle_confirmation` state.

- Other minor fixes (e.g. formatting).


## 1.0 &ndash; 2025-02-27

- Here we go!

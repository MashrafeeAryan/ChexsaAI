# ChexsaAI rebuild goals

Saved from the user's instructions on October 25, 2026.

## Purpose

Build an autonomous browser and desktop agent that completes tasks while using
fewer AI tokens. Token efficiency is a core requirement, not an optional addition.

Example request: "Hey Chexsa, please apply to IBM."
The intended behavior is to open Chrome, find the application, and fill it using
the user's supplied information. This is a target capability for the rebuild.

## Required token-saving features

1. **Send page changes instead of repeating the whole page.**
   Collect a starting observation, then track added elements, removed elements,
   and changed values or states after actions. Keep the complete page state
   locally and send the AI the changes with enough task context to understand
   them. Do not repeatedly send unchanged page content.

2. **Store and reuse skills in a database.**
   Save reusable solutions to completed workflows. When a similar task appears,
   retrieve a relevant skill instead of making the AI rediscover the entire
   solution. Check that the skill applies to the current page before using it.
   Saving task history alone does not implement reusable skills.

3. **Learn reusable workflows across users.**
   The longer-term goal is to collect skills from many users so the system can
   learn a wider range of tasks than a single user would encounter. Shared skills
   should describe reusable steps; personal form values are supplied separately
   when a workflow runs. A local skill database and shared skill collection are
   distinct features.

## How we will build it

- The user will guide the rebuild one step at a time.
- Keep the code simple and connect parts when they are needed.
- New filenames end with an underscore before the extension, such as cli_.py.
- Keep the rebuilt browser and desktop files; the old implementation is preserved in Git history.
- Use short, plain-English comments for function purposes and unclear code.
- Use small, focused local commits on feat/page-observations. Do not commit to main or push without a new request.
- Prefer local tests that do not call a model. Do not run live-model testing by
  default or consume API quota while explaining or reviewing files.
- Measure token usage and skill reuse so efficiency claims have evidence.
- Treat these as requirements to implement, not proof that the existing code
  already supports all of them.

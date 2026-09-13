# Frontend and integration plan

Owns `web/` and the browser-facing gateway API. The product should make logging and understanding the next step easy, while keeping evidence and safety details inspectable.

## Implemented in this improvement

Responsive cream/forest-green coaching workspace, coherent navigation, clear starter questions, labelled multiline composer, visible busy/error states, direct evidence links, answer route and token labels. The detector panel distinguishes skipped checks from numeric results. Focus styling, reduced-motion handling and small-screen reflow are included. Browser checks cover desktop and 375px mobile with mocked SSE responses.

Design decisions: local system fonts avoid a font download; CSS artwork is decorative rather than invented workout statistics; conversation statistics count actual answer routes in the current tab. The source panel is an explanation of retrieved material, not a claim of certainty.

## Next bounded work

1. Exercise the full four-service stack with an isolated Mongo database: register, authenticate, log sessions, inspect history, ask a question twice and compare token counts.
2. Add durable chat history with user-scoped storage and intentional retention controls; current turns are in React state.
3. Add password reset screens for the existing backend endpoints and surface actionable email-verification status.
4. Test loading, empty, error and quota states using actual service responses, plus keyboard navigation and landscape layouts.
5. Validate dashboard history and usage totals against database records rather than screenshots or fixtures.

## Follow-up prompt

> Read docs/improvement-plan.md and this file. Use the existing visual system to complete authenticated end-to-end product flows. Keep route/token labels truthful, evidence links accessible and errors recoverable. Use an isolated database and fake email transport in tests. Add durable user-scoped conversation history only with explicit retention and deletion behaviour. Do not replace recorded metrics with invented demo values. Distinguish mocked browser screenshots from live-stack validation.

Acceptance: starter submission works; failed streams release busy state; auth refresh retries at most once; evidence can be opened; mobile has no horizontal overflow; no API credentials are bundled into the web app.

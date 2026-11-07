# AI Customer Support Agent Test Plan

## Scope

This plan covers the Flask application, SQLite persistence, AI integration boundary, product-context logic, WooCommerce integration, escalation workflow, admin controls, and rendered admin pages.

Execution command:

```text
venv\\Scripts\\python.exe -m pytest -q
```

The automated tests use a temporary SQLite database per test and mock external AI/WooCommerce network calls. No production database or external API is used.

## Test Matrix

| # | Category | Coverage | Method | Expected result |
|---:|---|---|---|---|
| 1 | Application startup | Import and route registration | Automated | App imports and routes register without errors |
| 2 | Database initialization | Tables, migrations, user status columns | Automated | Fresh temporary database initializes successfully |
| 3 | User persistence | Guest creation and user lookup | Automated | Users are created and returned with admin/disabled fields |
| 4 | Authentication redirects | Anonymous page and API access | Automated | Page requests redirect; API requests return 401 |
| 5 | Disabled accounts | Disabled page and API behavior | Automated | Disabled users are cleared/rejected |
| 6 | Conversation persistence | Create, save, list, ownership | Automated | Messages remain attached to the correct user conversation |
| 7 | Daily usage limits | Increment, boundary, reset | Automated | 100 messages are allowed; the 101st is blocked |
| 8 | Empty chat input | Blank and whitespace messages | Automated | Request returns HTTP 400 without an AI call |
| 9 | AI service contract | Empty input, missing key, success/failure contract | Automated | Service returns `(success, message)` consistently |
| 10 | AI error handling | AI failure response and event logging | Automated | Chat returns 502 and records an error log |
| 11 | Product matching | Name/SKU overlap and no match | Automated | Matching is deterministic and bounded |
| 12 | Product context | No store, specific match, catalog, no match | Automated | Context mode and verified facts are correct |
| 13 | WooCommerce connection | URL/API response handling | Automated with mocks | Success, auth, timeout, and malformed responses are handled |
| 14 | Pre-AI escalation | Human, refund, payment, complaint/order signals | Automated | Handoff bypasses AI and quota |
| 15 | Post-AI escalation | AI uncertainty response | Automated | Conversation is marked escalated after a successful response |
| 16 | WhatsApp webhook | Message receipt and processing | Not Applicable - Not Yet Built | No webhook route exists in the current project |
| 17 | WhatsApp reply delivery | Outbound reply behavior | Not Applicable - Not Yet Built | No webhook/message-processing implementation exists |
| 18 | Escalation management | List, resolve, unresolved count | Automated | Owner can resolve their escalation; status is updated |
| 19 | Admin controls | Admin authorization, user status, logs, stats | Automated | Admin pages work; non-admins receive 403 |
| 20 | Mobile responsiveness | Layout at mobile viewport widths | Manual | Check navigation, tables, cards, and forms at 320px/375px widths |

## Manual Case: Mobile Responsiveness

1. Start the application and sign in as an admin.
2. Open the dashboard, users, user detail, logs, conversations, and integrations pages.
3. Test at 320px and 375px viewport widths using browser device emulation.
4. Confirm that no content requires horizontal scrolling, table content remains readable, buttons remain reachable, and the sidebar/navigation does not cover page content.
5. Record screenshots for any overflow, clipped text, or overlapping controls.

## Exit Criteria

- All automated tests pass.
- No test uses the production database or live external APIs.
- The two unimplemented WhatsApp categories remain explicitly excluded.
- Mobile behavior is manually reviewed and recorded before release.

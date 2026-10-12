---
name: reference_telegram_bot_allowed_chats
description: HA telegram_bot CTAs need the chat in allowed_chat_ids subentry + the :/data callback gotcha
metadata: 
  node_type: memory
  type: reference
  originSessionId: e7d16cb9-570e-4eac-9f5d-de2623f1c56a
---

HomeAutomationSetup Telegram CTA gotchas (found wiring the climate-cta blueprint, the first real button-CTA consumer):

- **Allowed chats:** HA's `telegram_bot` integration ("Solomon Smart Home", UI config entry) refuses to send unless the chat is registered as an `allowed_chat_ids` **subentry** (Settings → Devices & Services → Telegram bot → add chat → `chat_id`). Error otherwise: `Invalid chat IDs: <id>. Please configure the chat IDs`. This is separate from Grafana, which posts to `api.telegram.org` **directly** with the bot token + chat id from `/home/yossi/homeassistant/.env` (no allowed-list gate). Same bot + group for both.
- **Token lives in two places:** `.env` (`TELEGRAM_BOT_TOKEN`, for Grafana) AND the HA `telegram_bot` config entry `api_key` (in `.storage/core.config_entries`, UI-managed). Rotating means updating both.
- **Inline-button callback leading slash:** the `"text:/data"` `inline_keyboard` shorthand makes HA set `callback_data = "/" + data`, so the `telegram_callback` event arrives as `/CONFIRM_<ctx>`. Match the `/`-prefixed value in `wait_for_trigger` + conditions, else it never matches and the script hangs to timeout. Fixed in `telegram_confirmable.yaml`.

Related: [[feedback_no_secret_echo]], [[project_home_automation_arch]].

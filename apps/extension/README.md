# Satish browser extension

The same Satish app as the Telegram Mini App, packaged for Chrome, Edge and
Brave (Manifest V3, opens in the side panel).

## Build

```
SATISH_API=https://satish.rogan.live SATISH_BOT=YourBotUsername bun run build:extension
```

Output: `apps/extension/dist/` and `apps/extension/satish-extension.zip`.

## Try it

1. Open `chrome://extensions`, turn on Developer mode.
2. Load unpacked, pick `apps/extension/dist` (or drag the zip in).
3. Click the Satish icon. It shows a code; send `/link CODE` to the bot.

## What it does

- Wallet (Bitcoin + Lightning) and Satish AI, same account and TK as Telegram.
  The wallet stays on each device: restore it with your 12 words.
- Right-click a page: "Ask Satish AI about this page". Right-click selected
  text: "Ask Satish AI about ...".
- Right-click a `lightning:` or `bitcoin:` link, or a selected invoice or
  address: "Pay with Satish".

## Permissions

`sidePanel`, `contextMenus`, `storage`, `activeTab`, `scripting` and the
Satish API. No content scripts: a page is read only when you choose
"Ask Satish AI about this page" on it.

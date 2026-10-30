# Satish browser extension

The same Satish app as the Telegram Mini App, packaged for Chrome, Edge and
Brave (Manifest V3, opens in the side panel).

## Build

```
SATISH_API=https://satish.rogan.live SATISH_BOT=YourBotUsername bun run build:extension
```

Output: `apps/extension/dist/` and `apps/extension/satish-extension.zip`.

## Try it

1. Unzip `satish-extension.zip` into a folder (Chrome can't load a .zip directly).
2. Open `chrome://extensions`, turn on Developer mode, click **Load unpacked** and pick that folder.
3. Click the Satish icon. It shows a code; send `/link CODE` to the bot.

## What it does

- The wallet (Bitcoin + Lightning), plus Satish AI, the first app built on Satish payments. Same account and TK as on Telegram.
  The wallet stays on each device: restore it with your 12 words.
- Right-click a page: "Ask Satish AI about this page". Right-click selected
  text: "Ask Satish AI about ...".
- Right-click a `lightning:` or `bitcoin:` link, or a selected invoice or
  address: "Pay with Satish".

## Permissions

`sidePanel`, `contextMenus`, `storage`, `activeTab`, `scripting` and the
Satish API. No content scripts: a page is read only when you choose
"Ask Satish AI about this page" on it.

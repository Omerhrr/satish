// Satish browser extension: background service worker.
// - The toolbar button opens Satish in the side panel.
// - Right-click menus hand work to the app through chrome.storage.session:
//   "Ask Satish AI about this page / selection" and "Pay with Satish" for
//   lightning:/bitcoin: links or a selected invoice/address.
// No content scripts and no access to pages you don't act on: page text is
// read only after you click the menu (activeTab).

const PENDING = "satish_pending";
const PAYABLE = /^(lightning:|bitcoin:|lnbc|lntb|lntbs|lnbcrt|lnurl|bc1|tb1)/i;

chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: "ask-page", title: "Ask Satish AI about this page", contexts: ["page"] });
    chrome.contextMenus.create({ id: "ask-selection", title: "Ask Satish AI about \"%s\"", contexts: ["selection"] });
    chrome.contextMenus.create({
      id: "pay-link",
      title: "Pay with Satish",
      contexts: ["link"],
      targetUrlPatterns: ["lightning:*", "bitcoin:*", "LIGHTNING:*", "BITCOIN:*"],
    });
    chrome.contextMenus.create({ id: "pay-selection", title: "Pay this with Satish", contexts: ["selection"] });
  });
});

async function hand(tab, action) {
  // Open the panel first: it must happen inside the click (user gesture).
  const opening = tab && tab.windowId !== undefined ? chrome.sidePanel.open({ windowId: tab.windowId }).catch(() => {}) : null;
  await chrome.storage.session.set({ [PENDING]: { ...action, at: Date.now() } });
  await opening;
}

async function pageText(tabId) {
  try {
    const [res] = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => {
        const t = (document.body && document.body.innerText) || "";
        return t.replace(/\s+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim().slice(0, 2600);
      },
    });
    return (res && res.result) || "";
  } catch {
    return ""; // chrome:// pages and the Web Store can't be read
  }
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "pay-link") return void hand(tab, { type: "pay", uri: info.linkUrl || "" });
  if (info.menuItemId === "pay-selection") {
    const sel = (info.selectionText || "").trim().replace(/\s+/g, "");
    if (!PAYABLE.test(sel)) return void hand(tab, { type: "ask", text: `What is this, and is it a valid payment request? ${sel.slice(0, 500)}` });
    return void hand(tab, { type: "pay", uri: sel });
  }
  if (info.menuItemId === "ask-selection") {
    const sel = (info.selectionText || "").trim().slice(0, 3000);
    const src = tab && tab.url ? `\n\n(From ${tab.title || ""} ${tab.url})` : "";
    return void hand(tab, { type: "ask", text: `Explain and research this: "${sel}"${src}` });
  }
  if (info.menuItemId === "ask-page" && tab) {
    // Open the panel synchronously in the gesture, then read the page.
    chrome.sidePanel.open({ windowId: tab.windowId }).catch(() => {});
    pageText(tab.id).then((text) =>
      chrome.storage.session.set({
        [PENDING]: {
          type: "ask",
          text: `Summarise this page and check its key claims against other sources: ${tab.title || ""} ${tab.url || ""}${text ? "\n\nPage excerpt:\n" + text : ""}`.slice(0, 3900),
          at: Date.now(),
        },
      }),
    );
  }
});

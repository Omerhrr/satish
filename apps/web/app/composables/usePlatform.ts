/**
 * Where Satish is running: the Telegram Mini App or the browser extension.
 * Pages ask this instead of poking at Telegram or chrome.* directly.
 */

export type Platform = "telegram" | "extension";

/** Background/context-menu requests handed to the app (extension only). */
export type PendingAction = { type: "ask"; text: string; at: number } | { type: "pay"; uri: string; at: number };

const PENDING_KEY = "satish_pending";

function chromeApi(): any {
  return (globalThis as any).chrome;
}

export function usePlatform() {
  const config = useRuntimeConfig();
  const platform = ((config.public.platform as string) || "telegram") as Platform;
  const isExtension = platform === "extension";

  /** Take (and clear) a request the extension's background left for the app. */
  async function takePending(): Promise<PendingAction | null> {
    const c = chromeApi();
    if (!isExtension || !c?.storage?.session) return null;
    const got = await c.storage.session.get(PENDING_KEY);
    const p = got?.[PENDING_KEY] as PendingAction | undefined;
    if (!p) return null;
    await c.storage.session.remove(PENDING_KEY);
    return Date.now() - p.at < 5 * 60_000 ? p : null;
  }

  function onPending(cb: () => void): () => void {
    const c = chromeApi();
    if (!isExtension || !c?.storage?.onChanged) return () => {};
    const fn = (changes: Record<string, unknown>, area: string) => {
      if (area === "session" && changes[PENDING_KEY]) cb();
    };
    c.storage.onChanged.addListener(fn);
    return () => c.storage.onChanged.removeListener(fn);
  }

  function openExternal(url: string) {
    const tg = (window as any).Telegram?.WebApp;
    if (!isExtension && tg?.openLink) return tg.openLink(url);
    const c = chromeApi();
    if (isExtension && c?.tabs?.create) return c.tabs.create({ url });
    window.open(url, "_blank", "noopener");
  }

  return { platform, isExtension, takePending, onPending, openExternal };
}

/**
 * Lightning wallet state for the screens. Opened with the wallet password
 * (it uses the same 12 words), once per app session: the words are decrypted
 * only to start the Lightning wallet and are not kept by this code.
 */
import type { SdkEvent } from "@breeztech/breez-sdk-spark";
import { LightningError, LightningWallet, type LnNetwork, type LnPayment, type SdkModule } from "~/lib/lightning";

const st = reactive({
  open: false,
  opening: false,
  balance: null as number | null,
  cachedBalance: null as number | null,
  payments: [] as LnPayment[],
  deposits: [] as { txid: string; vout: number; amount: number; problem: string }[],
  address: null as string | null,
  error: "",
  flash: "",
  loaded: false,
  publish: "idle" as "idle" | "working" | "ok" | "error" | "nousername",
  publishError: "",
});

let wallet: LightningWallet | null = null;
let flashTimer: ReturnType<typeof setTimeout> | null = null;

function uid(): string {
  return String((window as any).Telegram?.WebApp?.initDataUnsafe?.user?.id ?? "local");
}

async function loadSdk(): Promise<SdkModule> {
  // Tests can inject a stand-in; the real ~12 MB module loads only when needed.
  const fake = (window as any).__satishLnSdk as SdkModule | undefined;
  if (fake) return fake;
  return (await import("@breeztech/breez-sdk-spark/web")) as unknown as SdkModule;
}

export function useLightning() {
  const config = useRuntimeConfig();
  const wal = useWallet(); // captured now: composables can't be called after an await
  const onchainNet = config.public.bitcoinNetwork === "mainnet" ? "mainnet" : "testnet";
  const network = ((config.public.lightningNetwork as string) || (onchainNet === "mainnet" ? "mainnet" : "regtest")) as LnNetwork;
  const apiKey = (config.public.breezApiKey as string) || "";
  const available = network !== "mainnet" || !!apiKey;
  const cacheKey = `xp_ln_balance_v1_${network}_${uid()}`;
  // Moving between savings (on-chain) and Lightning only works when both are on the same Bitcoin network.
  const canMove = network === "mainnet" && onchainNet === "mainnet";

  if (!st.loaded) {
    try {
      const raw = localStorage.getItem(cacheKey);
      st.cachedBalance = raw ? Number(raw) : null;
    } catch {
      /* ignore */
    }
    st.loaded = true;
  }

  function flash(msg: string) {
    st.flash = msg;
    if (flashTimer) clearTimeout(flashTimer);
    flashTimer = setTimeout(() => (st.flash = ""), 6000);
  }

  function onEvent(e: SdkEvent) {
    if (e.type === "paymentSucceeded" && e.payment.paymentType === "receive") {
      flash(`⚡ Received ${Number(e.payment.amount).toLocaleString()} sats`);
    }
    if (e.type === "paymentFailed") flash("A Lightning payment failed. Nothing was sent.");
    if (e.type === "claimedDeposits") flash("Your deposit arrived in your Lightning balance.");
    if (["synced", "paymentSucceeded", "paymentFailed", "claimedDeposits", "unclaimedDeposits", "newDeposits"].includes(e.type)) {
      void refresh();
    }
  }

  /** Start Lightning from the unlocked wallet session (no second password). */
  async function open() {
    if (st.open || st.opening) return;
    const phrase = wal.sessionPhraseOrNull();
    if (!phrase) {
      st.error = "Unlock Satish first.";
      return;
    }
    st.opening = true;
    st.error = "";
    try {
      wallet = new LightningWallet(await loadSdk(), network, apiKey, uid());
      await wallet.connect(phrase, onEvent);
      st.open = true;
      await refresh();
      void publish();
    } catch (e) {
      wallet = null;
      st.error = e instanceof LightningError || e instanceof Error ? e.message : "Couldn't open Lightning.";
    } finally {
      st.opening = false;
    }
  }

  /** Let people pay my @username on Lightning. Retried on every sync until it works. */
  let publishing: Promise<void> | null = null;
  function publish(): Promise<void> {
    if (publishing) return publishing;
    publishing = (async () => {
      if (!wallet?.connected) return;
      st.publish = "working";
      st.publishError = "";
      try {
        const ok = await wal.publishLightning(network, await wallet.sparkAddress());
        st.publish = ok ? "ok" : "nousername";
      } catch (e) {
        st.publish = "error";
        st.publishError = e instanceof Error ? e.message : "Couldn't set up your username for Lightning.";
      }
    })().finally(() => (publishing = null));
    return publishing;
  }

  /** One password unlocks both wallets. Throws WrongPassword. */
  async function unlockAll(password: string) {
    await wal.unlock(password);
    if (available) void open();
  }

  async function refresh() {
    if (!wallet?.connected) return;
    try {
      const [balance, payments, deposits, address] = await Promise.all([
        wallet.balance(),
        wallet.payments(),
        wallet.unclaimedDeposits().catch(() => []),
        wallet.lightningAddress().catch(() => null),
      ]);
      if (st.publish !== "ok" && st.publish !== "working") void publish();
      st.balance = balance;
      st.payments = payments;
      st.deposits = deposits;
      st.address = address;
      st.cachedBalance = balance;
      try {
        localStorage.setItem(cacheKey, String(balance));
      } catch {
        /* ignore */
      }
    } catch (e) {
      st.error = e instanceof Error ? e.message : "Couldn't update Lightning.";
    }
  }

  async function close() {
    await wallet?.disconnect();
    wallet = null;
    st.open = false;
    st.balance = null;
    st.payments = [];
  }

  async function forget() {
    await close();
    st.cachedBalance = null;
    try {
      localStorage.removeItem(cacheKey);
    } catch {
      /* ignore */
    }
  }

  function need(): LightningWallet {
    if (!wallet?.connected) throw new LightningError("Open your Lightning wallet first.");
    return wallet;
  }

  return {
    st, network, available, canMove, open, unlockAll, refresh, close, forget, flash, publish,
    invoice: (amount: number | undefined, description: string) => need().invoice(amount, description),
    /** Every payment (for the CSV), not just the recent ones shown. */
    allPayments: () => need().payments(5000),
    sparkAddress: () => need().sparkAddress(),
    depositAddress: () => need().depositAddress(),
    parse: (text: string) => need().parse(text),
    prepare: (text: string, amount?: number) => need().prepare(text, amount),
    send: async (...a: Parameters<LightningWallet["send"]>) => {
      const p = await need().send(...a);
      void refresh();
      return p;
    },
    claimDeposit: async (txid: string, vout: number) => {
      await need().claimDeposit(txid, vout);
      await refresh();
    },
    registerAddress: async (username: string) => {
      st.address = await need().registerLightningAddress(username);
      return st.address;
    },
    addressSupported: network === "mainnet",
  };
}

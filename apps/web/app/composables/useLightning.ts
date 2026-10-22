/**
 * Lightning wallet state for the screens. Opened with the wallet password
 * (it uses the same 12 words), once per app session: the words are decrypted
 * only to start the Lightning wallet and are not kept by this code.
 */
import type { SdkEvent } from "@breeztech/breez-sdk-spark";
import { LightningError, LightningWallet, type LnNetwork, type LnPayment, type SdkModule } from "~/lib/lightning";
import { WrongPassword } from "~/lib/wallet-core";

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

  async function open(password: string) {
    if (st.open) return;
    st.opening = true;
    st.error = "";
    try {
      const phrase = await useWallet().revealPhrase(password);
      wallet = new LightningWallet(await loadSdk(), network, apiKey, uid());
      await wallet.connect(phrase, onEvent);
      st.open = true;
      await refresh();
    } catch (e) {
      wallet = null;
      st.error = e instanceof LightningError ? e.message : e instanceof WrongPassword ? "Wrong password." : e instanceof Error ? e.message : "Couldn't open Lightning.";
      throw e;
    } finally {
      st.opening = false;
    }
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
    st, network, available, canMove, open, refresh, close, forget, flash,
    invoice: (amount: number | undefined, description: string) => need().invoice(amount, description),
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

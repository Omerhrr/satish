/**
 * Lightning wallet, on the user's phone, using the Breez SDK (Spark).
 *
 * - Same 12 words as the on-chain wallet: one backup covers both, and the
 *   funds can also be restored in other Breez SDK (Spark) wallets.
 * - Keys stay on the device. Spark's signing operators co-sign transfers but
 *   can't move funds alone, and the user can always exit to the Bitcoin
 *   blockchain on their own (unilateral exit).
 * - The SDK (a ~12 MB WebAssembly module) is only loaded when the user opens
 *   Lightning, so the rest of the app stays fast.
 *
 * Pure TypeScript with no Vue imports: the SDK module is injected so this can
 * be unit-tested with a fake.
 */

import type {
  BreezSdk, Config, InputType, Network, Payment, PrepareSendPaymentResponse, SdkEvent,
} from "@breeztech/breez-sdk-spark";

export type LnNetwork = Network; // "mainnet" | "regtest" | "signet"

/** The part of the SDK module we use (real module or a test fake). */
export interface SdkModule {
  default?: () => Promise<unknown>;
  defaultConfig(network: Network): Config;
  connect(req: { config: Config; seed: { type: "mnemonic"; mnemonic: string; passphrase?: string }; storageDir: string }): Promise<BreezSdk>;
}

export class LightningError extends Error {}

export interface LnPayment {
  id: string;
  direction: "send" | "receive";
  status: "completed" | "pending" | "failed";
  amount: number;
  fee: number;
  time: number; // unix seconds
  kind: "lightning" | "spark" | "deposit" | "withdraw" | "other";
  description: string;
}

/** Lightning history as CSV (a spreadsheet can open it). */
export function lightningCsv(payments: LnPayment[]): string {
  const esc = (v: string | number) => {
    const t = String(v);
    return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
  };
  const rows = [["date", "direction", "type", "status", "amount_sats", "fee_sats", "net_sats", "description", "payment_id"]];
  for (const p of payments) {
    const net = p.direction === "receive" ? p.amount : -(p.amount + p.fee);
    rows.push([
      p.time ? new Date(p.time * 1000).toISOString() : "",
      p.direction === "receive" ? "received" : "sent",
      p.kind, p.status, String(p.amount), String(p.fee), String(net), p.description, p.id,
    ]);
  }
  return rows.map((r) => r.map(esc).join(",")).join("\r\n") + "\r\n";
}

export function toLnPayment(p: Payment): LnPayment {
  const d = p.details;
  let description = "";
  if (d?.type === "lightning") description = d.description ?? d.lnurlPayInfo?.lnAddress ?? "";
  const kind = (["lightning", "spark", "deposit", "withdraw"] as const).find((k) => k === p.method) ?? "other";
  return {
    id: p.id,
    direction: p.paymentType,
    status: p.status,
    amount: Number(p.amount),
    fee: Number(p.fees),
    time: p.timestamp,
    kind,
    description,
  };
}

/** What the user pasted or scanned, in plain words. */
export type SendTarget =
  | { kind: "invoice"; amount?: number; description: string; expired: boolean }
  | { kind: "lightningAddress"; address: string; min: number; max: number }
  | { kind: "lnurl"; min: number; max: number; domain: string }
  | { kind: "spark"; address: string }
  | { kind: "bitcoin"; address: string; amount?: number };

export function describeInput(input: InputType, nowSecs = Math.floor(Date.now() / 1000)): SendTarget {
  switch (input.type) {
    case "bolt11Invoice": {
      const msat = input.amountMsat;
      const exp = input.timestamp + input.expiry;
      return {
        kind: "invoice",
        amount: msat ? Math.ceil(Number(msat) / 1000) : undefined,
        description: input.description ?? "",
        expired: exp < nowSecs,
      };
    }
    case "lightningAddress":
      return {
        kind: "lightningAddress",
        address: input.address,
        min: Math.ceil(input.payRequest.minSendable / 1000),
        max: Math.floor(input.payRequest.maxSendable / 1000),
      };
    case "lnurlPay":
      return { kind: "lnurl", min: Math.ceil(input.minSendable / 1000), max: Math.floor(input.maxSendable / 1000), domain: input.domain };
    case "sparkAddress":
      return { kind: "spark", address: input.address };
    case "bitcoinAddress":
      return { kind: "bitcoin", address: input.address };
    case "bip21": {
      // Unified QR codes carry an on-chain address and often a Lightning invoice: prefer Lightning.
      const ln = input.paymentMethods.find((m) => m.type === "bolt11Invoice" || m.type === "sparkAddress");
      if (ln) return describeInput(ln, nowSecs);
      const onchain = input.paymentMethods.find((m) => m.type === "bitcoinAddress");
      if (!onchain || onchain.type !== "bitcoinAddress") throw new LightningError("That payment code has nothing Satish can pay.");
      return { kind: "bitcoin", address: onchain.address, amount: input.amountSat ? Number(input.amountSat) : undefined };
    }
    default:
      throw new LightningError("Satish can't pay this kind of code yet. Use a Lightning invoice, a Lightning address or a Spark address.");
  }
}

export interface FeeQuote {
  fee: number; // sats the sender pays on top
  amount: number; // sats the receiver gets
}

export function feeOf(prep: PrepareSendPaymentResponse): FeeQuote {
  const m = prep.paymentMethod;
  const amount = Number(prep.amount);
  switch (m.type) {
    case "bolt11Invoice":
      return { amount, fee: m.sparkTransferFeeSats ?? m.lightningFeeSats };
    case "sparkAddress":
    case "sparkInvoice":
      return { amount, fee: Number(m.fee) };
    case "bitcoinAddress":
      return { amount, fee: m.feeQuote.speedMedium.userFeeSat + m.feeQuote.speedMedium.l1BroadcastFeeSat };
    default:
      return { amount, fee: 0 };
  }
}

export class LightningWallet {
  private sdk: BreezSdk | null = null;
  private listenerId: string | null = null;
  constructor(
    private mod: SdkModule,
    private network: LnNetwork,
    private apiKey: string,
    private storageId: string,
  ) {}

  get connected() {
    return !!this.sdk;
  }

  get lightningAddressSupported() {
    return this.network === "mainnet";
  }

  async connect(phrase: string, onEvent?: (e: SdkEvent) => void): Promise<void> {
    if (this.sdk) return;
    if (this.network === "mainnet" && !this.apiKey) {
      throw new LightningError("Lightning isn't set up on this server yet (missing Breez API key).");
    }
    if (this.mod.default) await this.mod.default();
    const config = this.mod.defaultConfig(this.network);
    if (this.apiKey) config.apiKey = this.apiKey;
    try {
      this.sdk = await this.mod.connect({
        config,
        seed: { type: "mnemonic", mnemonic: phrase },
        storageDir: `satish-ln-${this.network}-${this.storageId}`,
      });
    } catch (e) {
      throw new LightningError(`Couldn't open your Lightning wallet. Check your connection and try again. (${e instanceof Error ? e.message : String(e)})`);
    }
    if (onEvent) this.listenerId = await this.sdk.addEventListener({ onEvent });
  }

  private need(): BreezSdk {
    if (!this.sdk) throw new LightningError("Open your Lightning wallet first.");
    return this.sdk;
  }

  async balance(sync = false): Promise<number> {
    return (await this.need().getInfo({ ensureSynced: sync })).balanceSats;
  }

  async payments(limit = 30): Promise<LnPayment[]> {
    const r = await this.need().listPayments({ limit, sortAscending: false });
    return r.payments.map(toLnPayment);
  }

  /** A Lightning invoice anyone can pay from any Lightning wallet. */
  async invoice(amountSats: number | undefined, description: string): Promise<{ request: string; fee: number }> {
    if (amountSats !== undefined && (!Number.isInteger(amountSats) || amountSats <= 0)) {
      throw new LightningError("Enter the amount in whole sats.");
    }
    const r = await this.need().receivePayment({
      paymentMethod: { type: "bolt11Invoice", description: description || "Satish", amountSats, expirySecs: 3600 },
    });
    return { request: r.paymentRequest, fee: Number(r.fee) };
  }

  /** Reusable Spark address: instant, free transfers between Spark wallets. */
  async sparkAddress(): Promise<string> {
    return (await this.need().receivePayment({ paymentMethod: { type: "sparkAddress" } })).paymentRequest;
  }

  /** A Bitcoin address that tops up the Lightning balance (on-chain deposit). */
  async depositAddress(): Promise<string> {
    return (await this.need().receivePayment({ paymentMethod: { type: "bitcoinAddress" } })).paymentRequest;
  }

  async parse(text: string): Promise<SendTarget> {
    const t = text.trim().replace(/^lightning:/i, "");
    if (!t) throw new LightningError("Paste or scan a Lightning invoice or address.");
    let input: InputType;
    try {
      input = await this.need().parse(t);
    } catch {
      throw new LightningError("That doesn't look like a Lightning invoice or address.");
    }
    const target = describeInput(input);
    if (target.kind === "invoice" && target.expired) throw new LightningError("This invoice has expired. Ask for a new one.");
    return target;
  }

  async prepare(text: string, amountSats?: number): Promise<{ prep: PrepareSendPaymentResponse; quote: FeeQuote }> {
    const prep = await this.need().prepareSendPayment({
      paymentRequest: { type: "input", input: text.trim().replace(/^lightning:/i, "") },
      amount: amountSats !== undefined ? BigInt(amountSats) : undefined,
    } as Parameters<BreezSdk["prepareSendPayment"]>[0]);
    return { prep, quote: feeOf(prep) };
  }

  async send(prep: PrepareSendPaymentResponse, idempotencyKey: string): Promise<LnPayment> {
    const m = prep.paymentMethod;
    const options =
      m.type === "bolt11Invoice"
        ? ({ type: "bolt11Invoice", preferSpark: true, completionTimeoutSecs: 20 } as const)
        : m.type === "bitcoinAddress"
          ? ({ type: "bitcoinAddress", confirmationSpeed: "medium" } as const)
          : undefined;
    // Breez reuses the idempotency key as a Spark transfer id, which must be a
    // plain UUID. On-chain withdrawals (Lightning -> a bitcoin address) failed
    // with "Invalid TransferId format" when one was passed, so they go without;
    // the review screen's single-tap button is what prevents a double send.
    const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(idempotencyKey);
    const key = m.type === "bitcoinAddress" || !uuid ? undefined : idempotencyKey;
    let r;
    try {
      r = await this.need().sendPayment({ prepareResponse: prep, options, ...(key ? { idempotencyKey: key } : {}) });
    } catch (e) {
      if (/TransferId/i.test(String((e as Error)?.message ?? e)))
        throw new LightningError("Lightning couldn't start this payment. Check your Lightning history before trying again.");
      throw e;
    }
    const p = toLnPayment(r.payment);
    if (p.status === "failed") throw new LightningError("The payment failed. Nothing was sent.");
    return p;
  }

  async unclaimedDeposits(): Promise<{ txid: string; vout: number; amount: number; problem: string }[]> {
    const r = await this.need().listUnclaimedDeposits({});
    return r.deposits.map((d) => ({
      txid: d.txid,
      vout: d.vout,
      amount: d.amountSats,
      problem: !d.isMature
        ? "Waiting for confirmations."
        : d.claimError?.type === "maxDepositClaimFeeExceeded"
          ? `Network fees are high right now (${d.claimError.requiredFeeSats} sats to bring it in).`
          : d.claimError?.type === "generic"
            ? d.claimError.message
            : "",
    }));
  }

  async claimDeposit(txid: string, vout: number): Promise<void> {
    await this.need().claimDeposit({ txid, vout, maxFee: { type: "networkRecommended", leewaySatPerVbyte: 1 } });
  }

  async lightningAddress(): Promise<string | null> {
    if (!this.lightningAddressSupported) return null;
    return (await this.need().getLightningAddress())?.lightningAddress ?? null;
  }

  async registerLightningAddress(username: string): Promise<string> {
    if (!this.lightningAddressSupported) throw new LightningError("Lightning addresses only work on the real Bitcoin network.");
    const sdk = this.need();
    const free = await sdk.checkLightningAddressAvailable({ username });
    if (!free) throw new LightningError(`${username} is already taken as a Lightning address.`);
    return (await sdk.registerLightningAddress({ username, description: `Pay ${username} on Satish` })).lightningAddress;
  }

  async disconnect(): Promise<void> {
    const sdk = this.sdk;
    this.sdk = null;
    if (!sdk) return;
    if (this.listenerId) await sdk.removeEventListener(this.listenerId).catch(() => undefined);
    this.listenerId = null;
    await sdk.disconnect().catch(() => undefined);
  }
}

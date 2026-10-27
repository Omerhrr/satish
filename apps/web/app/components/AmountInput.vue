<template>
  <div class="amount-input">
    <div class="row">
      <input
        :value="typed"
        inputmode="decimal"
        :placeholder="unit === 'sats' ? placeholder : '0'"
        :disabled="disabled"
        :aria-label="label || 'Amount'"
        @input="onInput(($event.target as HTMLInputElement).value)"
      />
      <select :value="unit" aria-label="Currency" :disabled="disabled" @change="setUnit(($event.target as HTMLSelectElement).value)">
        <option value="sats">sats</option>
        <option v-for="c in currencies" :key="c" :value="c">{{ c }}</option>
      </select>
    </div>
    <p v-if="hint" class="small dim hint">{{ hint }}</p>
  </div>
</template>

<script setup lang="ts">
/**
 * Amount field that always produces sats (v-model, as a string like the old
 * inputs) but lets people type in sats or any currency: "₦5,000" becomes the
 * sats it's worth right now, shown underneath.
 */
const props = withDefaults(defineProps<{ modelValue: string; placeholder?: string; disabled?: boolean; label?: string }>(), {
  placeholder: "e.g. 10000",
  disabled: false,
  label: "",
});
const emit = defineEmits<{ "update:modelValue": [string] }>();
const { toSats, fiat, format, currency, setCurrency, currencies, testnet } = usePrice();

const unit = ref<string>("sats");
const typed = ref(props.modelValue);

function clean(v: string): number {
  return Number(String(v).replace(/[,\s₦$€£]/g, ""));
}

function onInput(v: string) {
  typed.value = v;
  if (unit.value === "sats") return emit("update:modelValue", v.replace(/[^\d]/g, ""));
  const n = clean(v);
  const sats = v.trim() && Number.isFinite(n) ? toSats(n, unit.value) : null;
  emit("update:modelValue", sats === null ? "" : String(sats));
}

function setUnit(u: string) {
  const sats = clean(props.modelValue);
  unit.value = u;
  if (u !== "sats") setCurrency(u);
  // Keep the amount, re-expressed in the new unit.
  if (props.modelValue && Number.isFinite(sats)) {
    if (u === "sats") typed.value = String(sats);
    else {
      const per = toSats(1, u);
      typed.value = per ? String(Math.round((sats / per) * 100) / 100) : "";
    }
  }
}

// Changed from outside (e.g. a payment request filled it in): show in sats.
watch(
  () => props.modelValue,
  (v) => {
    if (unit.value === "sats" && v !== typed.value) typed.value = v;
    if (unit.value !== "sats" && !v && typed.value && !clean(typed.value)) typed.value = "";
  },
);

const hint = computed(() => {
  const sats = clean(props.modelValue);
  if (!props.modelValue || !Number.isFinite(sats) || !sats) return "";
  const tn = testnet ? " (test coins)" : "";
  if (unit.value === "sats") return fiat(sats) ? fiat(sats) + tn : "";
  return `= ${sats.toLocaleString()} sats${tn}`;
});

onMounted(() => {
  // Start in the user's money when they've used it before.
  try {
    if (localStorage.getItem("satish_amount_unit") === "fiat" && currencies.value.includes(currency.value)) unit.value = currency.value;
  } catch {
    /* ignore */
  }
});
watch(unit, (u) => {
  try {
    localStorage.setItem("satish_amount_unit", u === "sats" ? "sats" : "fiat");
  } catch {
    /* ignore */
  }
});
void format;
</script>

<style scoped>
.amount-input .row { display: flex; gap: 6px; }
.amount-input input { flex: 1; min-width: 0; padding: 10px 12px; border-radius: 10px; border: 1px solid var(--border, rgba(148, 163, 184, 0.35)); background: var(--bg-elev, transparent); color: var(--text, inherit); font-size: 16px; }
.amount-input select {
  flex: none;
  padding: 0 8px;
  border-radius: 10px;
  border: 1px solid var(--border, rgba(148, 163, 184, 0.35));
  background: var(--bg-elev, transparent);
  color: inherit;
  font-size: 14px;
}
.hint { margin: 4px 0 0; }
</style>

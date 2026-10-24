"""Spend ledger: every paid external call is counted here and refused past its cap.
Worst-case accounting: every call is priced at list rate, as if the free tier were already used up."""
import json, pathlib, threading, time

LEDGER = pathlib.Path(__file__).parent / "spend.json"
_lock = threading.Lock()

# list prices, USD, checked Oct 23 2026
PRICE = {
    "google_root_tile": 6.00 / 1000, "google_tile": 0.0, "google_geocode": 5.00 / 1000, "google_streetview": 7.00 / 1000,
    "anthropic_in": {"claude-opus-5-5": 4.0e-6, "claude-sonnet-5-5": 2.0e-6, "claude-haiku-5-5": 0.10e-6},
    "anthropic_out": {"claude-opus-5-5": 20.0e-6, "claude-sonnet-5-5": 10.0e-6, "claude-haiku-5-5": 0.50e-6},
    "anthropic_cache_write": 1.25, "anthropic_cache_read": 0.10,  # multipliers on input price
}
CAPS = {"google": 5.00, "anthropic": 10.00}            # USD sub-caps set by the user on Oct 24 ~12:45 (Anthropic $10, Google Maps $5)
COUNT_CAPS = {"google_root_tile": 300, "google_geocode": 400, "google_streetview": 200}  # hard counts, all inside free tiers

class SpendCapExceeded(RuntimeError): pass

def _load():
    if LEDGER.exists(): return json.loads(LEDGER.read_text())
    return {"usd": {"google": 0.0, "anthropic": 0.0}, "counts": {}, "tokens": {}, "events": []}

def _save(d):
    tmp = LEDGER.with_suffix(".tmp"); tmp.write_text(json.dumps(d, indent=1)); tmp.replace(LEDGER)   # atomic

def status():
    d = _load(); return {"usd": d["usd"], "counts": d["counts"], "tokens": d["tokens"], "caps": CAPS, "count_caps": COUNT_CAPS}

def check(bucket, est_usd=0.0, count_key=None, n=1):
    """Raise before a call if it would cross a cap."""
    with _lock: d = _load()
    if d["usd"][bucket] + est_usd > CAPS[bucket]:
        raise SpendCapExceeded(f"{bucket}: ${d['usd'][bucket]:.3f} + ${est_usd:.3f} would exceed cap ${CAPS[bucket]:.2f}")
    if count_key and count_key in COUNT_CAPS and d["counts"].get(count_key, 0) + n > COUNT_CAPS[count_key]:
        raise SpendCapExceeded(f"{count_key}: {d['counts'].get(count_key, 0)} + {n} would exceed count cap {COUNT_CAPS[count_key]}")

_lock = threading.RLock()
def charge(bucket, usd, count_key=None, n=1, note="", tokens=None):
    with _lock:
        d = _load()
        d["usd"][bucket] = round(d["usd"][bucket] + usd, 6)
        if count_key: d["counts"][count_key] = d["counts"].get(count_key, 0) + n
        if tokens:
            for k, v in tokens.items(): d["tokens"][k] = d["tokens"].get(k, 0) + v
        d["events"].append({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "bucket": bucket, "usd": round(usd, 6), "key": count_key, "n": n, "note": note})
        d["events"] = d["events"][-500:]
        _save(d)

_tile_batch = [0]
def google_call(kind, n=1, note=""):
    """kind in google_root_tile | google_tile | google_geocode | google_streetview. Checks then charges, under one lock.
    Free child-tile requests are batched (flushed every 50) to keep the ledger file quiet."""
    usd = PRICE[kind] * n
    with _lock:
        if kind == "google_tile":
            _tile_batch[0] += n
            if _tile_batch[0] >= 50: charge("google", 0.0, count_key=kind, n=_tile_batch[0], note="batched child tiles"); _tile_batch[0] = 0
            return
        check("google", usd, count_key=kind, n=n)
        charge("google", usd, count_key=kind, n=n, note=note)

def anthropic_estimate(model, input_tokens, max_output_tokens):
    return PRICE["anthropic_in"][model] * input_tokens + PRICE["anthropic_out"][model] * max_output_tokens

def anthropic_charge(model, usage, note=""):
    pin, pout = PRICE["anthropic_in"][model], PRICE["anthropic_out"][model]
    usd = (pin * usage.input_tokens + pin * PRICE["anthropic_cache_write"] * (usage.cache_creation_input_tokens or 0)
           + pin * PRICE["anthropic_cache_read"] * (usage.cache_read_input_tokens or 0) + pout * usage.output_tokens)
    charge("anthropic", usd, count_key="anthropic_calls", note=f"{model} {note}",
           tokens={"in": usage.input_tokens, "out": usage.output_tokens, "cache_read": usage.cache_read_input_tokens or 0, "cache_write": usage.cache_creation_input_tokens or 0})
    return usd

if __name__ == "__main__":
    print(json.dumps(status(), indent=1))

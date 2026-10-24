"""Card rail behind one adapter interface: intent -> tokenise -> authenticate (3-D Secure) -> authorize -> capture.
`SandboxCardAdapter` is a faithful mock (test card numbers only, nothing stored, deterministic ids). To plug in Visa's
hackathon sandbox or Cybersource: implement the same five methods in a new adapter and select it with CARD_ADAPTER=visa.
Keys that would be needed for a real sandbox (none present): merchant id, API key id/secret (Cybersource REST uses
HTTP-signature auth), 3DS/Payer Authentication org credentials, optional network token provisioning credentials."""
import hashlib, os, time, uuid

TEST_CARDS = {"4242424242424242": "visa", "4000000000003220": "visa (3DS challenge)", "5555555555554444": "mastercard"}

class SandboxCardAdapter:
    name = "sandbox card rail (mock; swap for Visa / Cybersource sandbox)"
    def create_intent(self, amount_usd: float, currency: str, order_id: str, meta: dict):
        return {"intent_id": "pi_" + uuid.uuid4().hex[:16], "amount": round(amount_usd, 2), "currency": currency, "order_id": order_id, "status": "requires_payment_method", "created": time.time()}
    def tokenise(self, intent, pan: str, exp: str):
        if pan not in TEST_CARDS: raise ValueError("only published test card numbers are accepted in the sandbox")
        token = "tok_" + hashlib.sha256((pan + exp + intent["intent_id"]).encode()).hexdigest()[:20]
        return {"token": token, "brand": TEST_CARDS[pan].split(" ")[0], "last4": pan[-4:], "pan_stored": False}
    def authenticate_3ds(self, intent, token):
        challenge = token["last4"] == "3220"
        return {"3ds_version": "2.2.0", "challenge": challenge, "status": "authenticated", "eci": "05" if challenge else "07", "cavv": "sandbox-" + token["token"][-8:]}
    def authorize(self, intent, token, auth3ds):
        return {"auth_id": "auth_" + uuid.uuid4().hex[:12], "status": "authorized", "amount": intent["amount"], "approval_code": hashlib.md5(intent["intent_id"].encode()).hexdigest()[:6].upper(), "captured": False}
    def capture(self, intent, auth):
        return {"capture_id": "cap_" + uuid.uuid4().hex[:12], "status": "captured", "amount": auth["amount"], "captured_at": time.time()}

def adapter():
    kind = os.environ.get("CARD_ADAPTER", "sandbox")
    if kind == "sandbox": return SandboxCardAdapter()
    raise RuntimeError(f"card adapter '{kind}' not implemented: add a class with create_intent/tokenise/authenticate_3ds/authorize/capture")

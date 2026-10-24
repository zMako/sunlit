"""Claude wrapper: key from .env, pre-call cost estimate via count_tokens, ledger charge from real usage, cap enforced."""
import base64, pathlib, anthropic
from dotenv import dotenv_values
import spend

ENV = dotenv_values(pathlib.Path(__file__).parent.parent / ".env")
DEV_MODEL, FINAL_MODEL = "claude-haiku-5-5", "claude-opus-5-5"
_client = None
def client():
    global _client
    if _client is None: _client = anthropic.Anthropic(api_key=ENV["ANTHROPIC_API_KEY"])
    return _client

def image_block(path):
    p = pathlib.Path(path); mt = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return {"type": "image", "source": {"type": "base64", "media_type": mt, "data": base64.standard_b64encode(p.read_bytes()).decode()}}

def ask(system, content, model=DEV_MODEL, max_tokens=2000, note="", effort="medium"):
    """content: list of content blocks (text/image). Returns (text, usd). Refuses if the worst case would cross the cap."""
    c = client(); messages = [{"role": "user", "content": content}]
    n_in = c.messages.count_tokens(model=model, system=system, messages=messages).input_tokens
    est = spend.anthropic_estimate(model, n_in, max_tokens)
    spend.check("anthropic", est)
    kwargs = dict(model=model, max_tokens=max_tokens, system=system, messages=messages, cache_control={"type": "ephemeral"},
                  output_config={"effort": effort})
    if model == FINAL_MODEL: kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    r = (c.beta.messages.create(**kwargs) if model == FINAL_MODEL else c.messages.create(**kwargs))
    usd = spend.anthropic_charge(model, r.usage, note=note)
    if r.stop_reason == "refusal": return "", usd
    return "".join(b.text for b in r.content if b.type == "text"), usd

if __name__ == "__main__":
    text, usd = ask("Answer in one word.", [{"type": "text", "text": "What colour is the sky at noon?"}], max_tokens=16, note="phase0 smoke")
    print(repr(text), f"${usd:.6f}", spend.status()["usd"])

"""extract.py - batch invoice and receipt extractor (Amazon Bedrock Converse API, eu-west-2).

Usage:
  python3 extract.py samples --model nova-lite                 # JSON in the reply text (default)
  python3 extract.py samples --model nova-pro
  python3 extract.py samples --model nova-lite --mode tool     # forced tool call; falls back to text if it fails
  python3 extract.py samples --model nova-lite --simulate-throttle 2   # practise the backoff path

Writes: out/<model>-<mode>/<file>.json, results.csv and run.log
"""
import argparse
import csv
import json
import logging
import random
import re
import time
from datetime import date
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

REGION = "eu-west-2"
# USD per 1,000 tokens, eu-west-2 on-demand Standard tier (AWS Price List API, 14 Oct 2026). Re-check before use.
MODELS = {
    "nova-lite": dict(id="amazon.nova-lite-v1:0", price_in=0.000084, price_out=0.000336),
    "nova-pro": dict(id="amazon.nova-pro-v1:0", price_in=0.00113, price_out=0.00452),
}
RETRYABLE = {"ThrottlingException", "ServiceUnavailableException", "ModelNotReadyException",
             "InternalServerException", "ModelTimeoutException"}
MAX_ATTEMPTS = 5            # per call, for throttling and other temporary errors
MAX_IMAGE_BYTES = 3_750_000  # Converse limit per image
MAX_DOC_BYTES = 4_500_000    # Converse limit per document
MONEY_TOL = 0.02             # pennies of rounding we accept
VAT_TOL = 0.05               # per-line VAT rounding can add up to a few pence

SCHEMA = {
    "type": "object",
    "properties": {
        "doc_type": {"type": "string", "enum": ["invoice", "receipt"]},
        "supplier_name": {"type": "string", "description": "Business that issued the document"},
        "supplier_vat_number": {"type": "string", "description": "UK VAT number as printed; empty string if none"},
        "invoice_number": {"type": "string", "description": "Invoice or receipt number"},
        "invoice_date": {"type": "string", "description": "Issue date as YYYY-MM-DD. UK documents write dates day first."},
        "due_date": {"type": "string", "description": "Payment due date as YYYY-MM-DD; empty string if none"},
        "currency": {"type": "string", "description": "ISO code, e.g. GBP"},
        "prices_include_vat": {"type": "boolean",
                               "description": "true if line amounts already include VAT (typical till receipt)"},
        "line_items": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "quantity": {"type": "number"},
                "unit_price": {"type": "number"},
                "vat_rate": {"type": "number", "description": "VAT percent for this line: 20, 5 or 0"},
                "line_total": {"type": "number", "description": "Amount printed for the line"}},
            "required": ["description", "quantity", "unit_price", "vat_rate", "line_total"]}},
        "subtotal": {"type": "number", "description": "Amount excluding VAT (the net amount). If it is not printed, use total minus vat_total"},
        "vat_total": {"type": "number", "description": "Total VAT as printed; 0 if no VAT is shown"},
        "total": {"type": "number", "description": "Amount paid or due, including VAT (the TOTAL line)"},
    },
    "required": ["doc_type", "supplier_name", "supplier_vat_number", "invoice_number", "invoice_date",
                 "due_date", "currency", "prices_include_vat", "line_items", "subtotal", "vat_total", "total"],
}
TOOL_NAME = "record_document"
SYSTEM = ("You extract data from UK invoices and till receipts for a finance team. "
          "Copy values exactly as printed. Never invent or correct numbers: if the document's own figures "
          "do not add up, still report what is printed. Dates on UK documents are day-first. "
          "Use an empty string for a text field that is not on the document.")
INSTRUCTION = f"Extract the fields of this document by calling the {TOOL_NAME} tool."
DATE_RULE = ("Dates on these UK documents are written day first (DD/MM/YYYY or DD/MM/YY): 05/03/2026 means "
             "5 March 2026, so write 2026-03-05, and 11/04/26 means 11 April 2026, so write 2026-04-11.")
TEXT_FORMAT = ("Reply with one JSON object only, no other text, no markdown fences, matching this JSON schema: "
               + json.dumps(SCHEMA))

log = logging.getLogger("extract")


class ToolFailed(Exception):
    """The model was asked to call the tool but returned no usable tool call."""


# ------------------------------------------------------------------ calling Bedrock
def content_block(path):
    data = path.read_bytes()
    ext = path.suffix.lower().lstrip(".")
    if ext == "pdf":
        if len(data) > MAX_DOC_BYTES:
            raise ValueError(f"PDF is {len(data)} bytes; the Converse limit is 4.5 MB")
        return {"document": {"format": "pdf", "name": "document", "source": {"bytes": data}}}
    if ext in ("png", "jpg", "jpeg"):
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError(f"image is {len(data)} bytes; the Converse limit is 3.75 MB")
        return {"image": {"format": "png" if ext == "png" else "jpeg", "source": {"bytes": data}}}
    raise ValueError(f"unsupported file type .{ext}")


class BadOutput(ValueError):
    """The model answered, but the reply could not be read. Keeps the usage so the cost is still counted."""
    def __init__(self, msg, usage, latency, raw):
        super().__init__(msg)
        self.usage, self.latency, self.raw = usage, latency, raw


def call_model(client, model, path, mode, feedback=None, throttle_budget=None):
    """One Converse call with exponential backoff on temporary errors. Returns (data, usage, latency_ms)."""
    text = INSTRUCTION if mode == "tool" else "Extract the fields of this document."
    if feedback:
        text += "\n\n" + feedback
    text += "\n\n" + DATE_RULE              # a worked example works better than "day first" alone
    if mode == "text":
        text += "\n\n" + TEXT_FORMAT        # the format rule goes at the END of the user message
    req = dict(modelId=model["id"], system=[{"text": SYSTEM}],
               messages=[{"role": "user", "content": [content_block(path), {"text": text}]}],
               inferenceConfig={"maxTokens": 2000, "temperature": 0})   # 0 = the same answer every time
    if mode == "tool":
        req["toolConfig"] = {"tools": [{"toolSpec": {"name": TOOL_NAME,
                                                     "description": "Record the extracted invoice or receipt fields.",
                                                     "inputSchema": {"json": SCHEMA}}}],
                             "toolChoice": {"tool": {"name": TOOL_NAME}}}
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            if throttle_budget and throttle_budget[0] > 0:      # --simulate-throttle
                throttle_budget[0] -= 1
                raise ClientError({"Error": {"Code": "ThrottlingException", "Message": "simulated"}}, "Converse")
            start = time.time()
            resp = client.converse(**req)
            latency = int((time.time() - start) * 1000)
            try:
                return parse_response(resp, mode), resp["usage"], latency
            except (ValueError, json.JSONDecodeError) as e:
                raw = "".join(b.get("text", "") for b in resp["output"]["message"]["content"])
                raise BadOutput(str(e), resp["usage"], latency, raw) from e
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code not in RETRYABLE or attempt == MAX_ATTEMPTS:
                raise
            wait = min(20, 2 ** attempt) + random.uniform(0, 1)     # 2, 4, 8, 16 s (+ jitter)
            log.warning("%s: %s on attempt %d, waiting %.1f s", path.name, code, attempt, wait)
            time.sleep(wait)


def parse_response(resp, mode):
    blocks = resp["output"]["message"]["content"]
    if mode == "tool":
        for b in blocks:
            if "toolUse" in b:
                return b["toolUse"]["input"]
        raise ToolFailed(f"no tool call (stopReason={resp.get('stopReason')})")
    text = "".join(b.get("text", "") for b in blocks)
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.S)      # Nova may add its reasoning
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the reply: " + text[:200])
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("the reply is JSON but not an object")
    return data


# ------------------------------------------------------------------ validation in code
def parse_date(value, field, errors, past_only=True):
    if not value:
        return None
    try:
        d = date.fromisoformat(str(value))
    except ValueError:
        errors.append(f"{field} '{value}' is not a YYYY-MM-DD date")
        return None
    if past_only and d > date.today():
        errors.append(f"{field} {d} is in the future")
    if d.year < 2000:
        errors.append(f"{field} {d} is before 2000")
    return d


def validate(x):
    """Return a list of human-readable problems; an empty list means the extraction passed."""
    errors = []
    for f in SCHEMA["required"]:
        if f not in x:
            errors.append(f"missing field {f}")
    if errors:
        return errors
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    for f in ("subtotal", "vat_total", "total"):
        if not num(x[f]):
            errors.append(f"{f} must be a number, got {x[f]!r}")
    if not isinstance(x["line_items"], list) or not x["line_items"]:
        errors.append("line_items must be a non-empty list")
    if errors:
        return errors
    issued = parse_date(x["invoice_date"], "invoice_date", errors)
    due = parse_date(x["due_date"], "due_date", errors, past_only=False)
    if issued and due and due < issued:
        errors.append(f"due_date {due} is before invoice_date {issued}")
    vat_no = x.get("supplier_vat_number")
    if vat_no and not re.fullmatch(r"GB(\d{9}|\d{12})", vat_no.replace(" ", "").upper()):
        errors.append(f"supplier_vat_number '{vat_no}' is not GB + 9 or 12 digits")
    lines_sum, vat_calc = 0.0, 0.0
    for i, li in enumerate(x["line_items"], 1):
        if not all(num(li.get(k)) for k in ("quantity", "unit_price", "vat_rate", "line_total")):
            errors.append(f"line {i}: quantity, unit_price, vat_rate and line_total must be numbers")
            continue
        if abs(li["quantity"] * li["unit_price"] - li["line_total"]) > MONEY_TOL:
            errors.append(f"line {i}: {li['quantity']} x {li['unit_price']} != line_total {li['line_total']}")
        if li["vat_rate"] not in (0, 5, 20):
            errors.append(f"line {i}: vat_rate {li['vat_rate']} is not a UK rate (0, 5, 20)")
        lines_sum += li["line_total"]
        r = li["vat_rate"]
        vat_calc += li["line_total"] * r / (100 + r) if x["prices_include_vat"] else li["line_total"] * r / 100
    target, name = (x["total"], "total") if x["prices_include_vat"] else (x["subtotal"], "subtotal")
    if abs(lines_sum - target) > MONEY_TOL:
        errors.append(f"line totals add up to {lines_sum:.2f} but {name} is {target:.2f}")
    if abs(x["subtotal"] + x["vat_total"] - x["total"]) > MONEY_TOL:
        errors.append(f"subtotal {x['subtotal']:.2f} + vat_total {x['vat_total']:.2f} != total {x['total']:.2f}")
    if abs(vat_calc - x["vat_total"]) > VAT_TOL:
        errors.append(f"VAT from the line rates is {vat_calc:.2f} but vat_total is {x['vat_total']:.2f}")
    return errors


# ------------------------------------------------------------------ one document, whole batch
def process(client, model, path, mode, throttle_budget):
    content_block(path)                     # size/type check first: raises ValueError -> status "error"
    usage_in = usage_out = latency = 0
    data, errors, attempts = None, [], 0
    feedback, best = None, None
    for attempts in (1, 2):                 # first try + ONE retry with the validation errors
        try:
            data, usage, ms = call_model(client, model, path, mode, feedback, throttle_budget)
            usage_in += usage["inputTokens"]; usage_out += usage["outputTokens"]; latency += ms
            for k in ("supplier_vat_number", "due_date"):      # Nova tool schemas have no null type
                if data.get(k) in ("", "null", "None"):
                    data[k] = None
            errors = validate(data)
        except (ToolFailed, ClientError) as e:
            code = getattr(e, "response", {}).get("Error", {}).get("Code", "ToolFailed")
            if mode != "tool" or code not in ("ToolFailed", "ModelErrorException"):
                raise
            log.warning("%s: tool call failed (%s: %s); switching to text mode", path.name, code, e)
            mode, errors = "text", [f"tool call failed: {code}"]
            continue
        except BadOutput as e:                                # bad/missing JSON counts as a validation failure
            usage_in += e.usage["inputTokens"]; usage_out += e.usage["outputTokens"]; latency += e.latency
            errors = [f"could not read the model output as JSON ({e}); it began: {e.raw.strip()[:160]!r}"]
            data = None
        if data is not None and (best is None or len(errors) < len(best[1])):
            best = (data, errors)               # keep the answer with the fewest problems (first one on a tie)
        if not errors:
            break
        log.info("%s: attempt %d failed validation: %s", path.name, attempts, "; ".join(errors))
        feedback = ("Your previous extraction failed these checks:\n- " + "\n- ".join(errors) +
                    "\nPrevious output: " + json.dumps(data) +
                    "\nLook at the document again and correct any field you misread. If the document itself "
                    "prints figures that do not add up, keep the printed figures.")
    if errors and best:
        data, errors = best
    status = "ok" if not errors else "needs_review"
    cost = usage_in / 1000 * model["price_in"] + usage_out / 1000 * model["price_out"]
    meta = dict(file=path.name, model=model["id"], mode=mode, status=status, attempts=attempts, errors=errors,
                input_tokens=usage_in, output_tokens=usage_out, cost_usd=round(cost, 6), latency_ms=latency)
    return data, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--model", choices=MODELS, default="nova-lite")
    ap.add_argument("--mode", choices=["text", "tool"], default="text")
    ap.add_argument("--simulate-throttle", type=int, default=0, help="fake N ThrottlingExceptions to test backoff")
    args = ap.parse_args()
    model = MODELS[args.model]
    out = Path("out") / f"{args.model}-{args.mode}"
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(out / "run.log"), logging.StreamHandler()])
    # The SDK's own retries are switched off so that every retry is ours and appears in the log.
    client = boto3.client("bedrock-runtime", region_name=REGION,
                          config=Config(retries={"total_max_attempts": 1, "mode": "standard"}, read_timeout=120))
    files = sorted(p for p in Path(args.folder).iterdir() if p.suffix.lower() in (".pdf", ".png", ".jpg", ".jpeg"))
    log.info("model %s, mode %s, %d files", model["id"], args.mode, len(files))
    budget = [args.simulate_throttle]
    rows = []
    for path in files:
        try:
            data, meta = process(client, model, path, args.mode, budget)
        except (ClientError, ValueError) as e:            # access denied, file too big, out of retries...
            log.error("%s: %s", path.name, e)
            data, meta = None, dict(file=path.name, model=model["id"], mode=args.mode, status="error",
                                    attempts=0, errors=[str(e)], input_tokens=0, output_tokens=0,
                                    cost_usd=0, latency_ms=0)
        (out / (path.stem + ".json")).write_text(json.dumps({"extraction": data, "meta": meta}, indent=2))
        d = data or {}
        rows.append({"file": path.name, "status": meta["status"], "attempts": meta["attempts"],
                     "supplier_name": d.get("supplier_name"), "invoice_number": d.get("invoice_number"),
                     "invoice_date": d.get("invoice_date"), "subtotal": d.get("subtotal"),
                     "vat_total": d.get("vat_total"), "total": d.get("total"), "currency": d.get("currency"),
                     "line_items": len(d.get("line_items") or []), "input_tokens": meta["input_tokens"],
                     "output_tokens": meta["output_tokens"], "cost_usd": meta["cost_usd"],
                     "latency_ms": meta["latency_ms"], "errors": " | ".join(meta["errors"])})
        log.info("%s: %s after %d attempt(s), %d in / %d out tokens, $%.6f",
                 path.name, meta["status"], meta["attempts"], meta["input_tokens"], meta["output_tokens"],
                 meta["cost_usd"])
    with open(out / "results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    total = sum(r["cost_usd"] for r in rows)
    log.info("done: %d ok, %d needs_review, %d error; total $%.6f ($%.6f per document)",
             sum(r["status"] == "ok" for r in rows), sum(r["status"] == "needs_review" for r in rows),
             sum(r["status"] == "error" for r in rows), total, total / len(rows))


if __name__ == "__main__":
    main()

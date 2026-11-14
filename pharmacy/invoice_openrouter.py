"""Invoice reading through OpenRouter (OpenAI-compatible API), e.g. free vision models.

Same contract as the Claude path: returns an InvoiceResult with data in the same JSON schema.
"""
import base64
import json
import os
import re
from pathlib import Path

import openai

from .invoice import MEDIA_TYPES, InvoiceResult

BASE_URL = "https://openrouter.ai/api/v1"


def _client():
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set in .env")
    return openai.OpenAI(base_url=BASE_URL, api_key=key, max_retries=4, timeout=180)


def _parse_json(text: str):
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise json.JSONDecodeError("no JSON object", text, 0)
    return json.loads(text[start:end + 1])


def _normalise(data: dict, catalog_names) -> dict:
    """Free models don't always follow the schema exactly; coerce to the shape the checker expects."""
    allowed = set(catalog_names)
    lines = []
    for l in data.get("lines") or []:
        if not isinstance(l, dict):
            continue
        match = str(l.get("catalog_match") or "NONE")
        try:
            qty = int(float(str(l.get("qty") or 0).replace(",", "")))
        except ValueError:
            qty = 0
        lines.append({
            "product_name": str(l.get("product_name") or ""),
            "catalog_match": match if match in allowed else "NONE",
            "batch_no": str(l.get("batch_no") or ""),
            "expiry": str(l.get("expiry") or ""),
            "qty": qty,
            "unit_price": str(l.get("unit_price") or ""),
        })
    return {
        "supplier_name": str(data.get("supplier_name") or ""),
        "invoice_number": str(data.get("invoice_number") or ""),
        "invoice_date": str(data.get("invoice_date") or ""),
        "lines": lines,
        "total": str(data.get("total") or ""),
        "suspicious_text": bool(data.get("suspicious_text")),
        "notes": str(data.get("notes") or ""),
    }


def read_invoice_openrouter(path: Path, catalog_names, system: str, schema: dict, model: str) -> InvoiceResult:
    media_type = MEDIA_TYPES.get(path.suffix.lower())
    if media_type is None or media_type == "application/pdf":
        return InvoiceResult(data={}, model=model, error="With OpenRouter, upload a photo (JPG/PNG), not a PDF.")
    b64 = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    prompt = ("Catalog products:\n" + "\n".join(f"- {n}" for n in catalog_names)
              + "\n\nExtract every line item from this invoice. Reply with only a JSON object matching this schema:\n"
              + json.dumps(schema))
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}},
            {"type": "text", "text": prompt},
        ]},
    ]
    try:
        client = _client()
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages, temperature=0,
                response_format={"type": "json_schema",
                                 "json_schema": {"name": "invoice", "strict": True, "schema": schema}},
            )
        except openai.BadRequestError:
            # Some free models reject strict schemas; fall back to plain JSON mode.
            resp = client.chat.completions.create(
                model=model, messages=messages, temperature=0, response_format={"type": "json_object"},
            )
    except RuntimeError as e:
        return InvoiceResult(data={}, model=model, error=str(e))
    except openai.RateLimitError:
        return InvoiceResult(data={}, model=model, error="OpenRouter rate limit hit (free models are limited). Wait a minute and retry.")
    except openai.APIStatusError as e:
        return InvoiceResult(data={}, model=model, error=f"OpenRouter error {e.status_code}: {e.message}")
    except openai.APIConnectionError:
        return InvoiceResult(data={}, model=model, error="Network error: could not reach OpenRouter.")

    usage = resp.usage
    in_tok = getattr(usage, "prompt_tokens", 0) or 0
    out_tok = getattr(usage, "completion_tokens", 0) or 0
    choice = resp.choices[0] if resp.choices else None
    text = choice.message.content if choice and choice.message else ""
    try:
        data = _normalise(_parse_json(text), catalog_names)
    except (json.JSONDecodeError, AttributeError):
        return InvoiceResult(data={}, input_tokens=in_tok, output_tokens=out_tok, model=model,
                             error="Model did not return valid JSON.")
    # Free models: $0. Paid OpenRouter models would need their own price here.
    return InvoiceResult(data=data, input_tokens=in_tok, output_tokens=out_tok, cost_usd=0.0, model=model)

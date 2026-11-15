"""AI compares a small, deterministic shortlist; original documents are never deleted."""
import json
import re

import httpx
from sqlalchemy import select

from scout.models import Document, Item
from scout.prompts import load_prompt


def shortlist(db, item, raw, now):
    # Coarse retrieval is only candidate selection, never the merge decision.
    title = re.sub(r"[^\w\u4e00-\u9fff]", "", item.title.lower())
    grams = {title[i:i+3] for i in range(max(0, len(title)-2))}
    numbers = set(re.findall(r"[A-Za-z]{1,12}[-/]?\d[\w/-]{5,}", raw))
    rows = db.execute(select(Item, Document).join(Document, Item.document_id == Document.id).where(
        Item.id != item.id, Item.is_demo.is_(False), Item.quality_status == "active",
        Item.information_kind.in_(("opportunity", "demand")), Item.created_at >= now-30*86400,
        Item.ai_review["decision"].as_string() == "buyer_demand",
    ).order_by(Item.created_at.desc()).limit(400)).all()
    ranked = []
    for other, doc in rows:
        candidate = re.sub(r"[^\w\u4e00-\u9fff]", "", other.title.lower())
        other_grams = {candidate[i:i+3] for i in range(max(0, len(candidate)-2))}
        common = grams & other_grams
        score = len(common) / max(1, len(grams | other_grams))
        same_number = bool(numbers & set(re.findall(r"[A-Za-z]{1,12}[-/]?\d[\w/-]{5,}", doc.raw_content)))
        if same_number or other.url == item.url or (len(common) >= 3 and score >= .12):
            ranked.append((score + int(same_number) + int(other.url == item.url), other, doc))
    ranked.sort(key=lambda row: row[0], reverse=True)
    return [{"id": other.id, "title": other.title, "body": doc.raw_content,
             "published_at": other.published_at} for _, other, doc in ranked[:5]]


def compare(title, raw, candidates, config, client=None):
    if not candidates:
        return {"relation": "distinct", "target_id": None, "reason": "未检索到相近候选"}
    # Don't discard context to force a cheap approval/merge.
    if len(raw) > 16000 or sum(len(c["body"]) for c in candidates) > 40000:
        return {"relation": "uncertain", "target_id": None, "reason": "候选原文过长，需核实"}
    body = {"model": config.deepseek_model, "thinking": {"type": "disabled"},
            "stream": False, "max_tokens": 800, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": load_prompt("semantic-dedupe")}, {"role": "user", "content": json.dumps(
                {"new": {"title": title, "body": raw}, "candidates": candidates}, ensure_ascii=False)}]}
    def request(c):
        response = c.post("https://api.deepseek.com/chat/completions", json=body,
                          headers={"Authorization": "Bearer "+config.deepseek_api_key})
        response.raise_for_status()
        result = json.loads(response.json()["choices"][0]["message"]["content"])
        if not isinstance(result, dict) or result.get("relation") not in {"duplicate", "update", "distinct", "uncertain"}:
            raise ValueError("invalid_dedupe_response")
        if not isinstance(result.get("reason"), str):
            raise ValueError("invalid_dedupe_reason")
        target = next((c for c in candidates if c["id"] == result.get("target_id")), None)
        if result["relation"] in {"duplicate", "update"}:
            if not target:
                raise ValueError("invalid_dedupe_target")
            for key, source in (("evidence_new", raw), ("evidence_existing", target["body"])):
                quote = result.get(key)
                if not isinstance(quote, str) or len(quote.strip()) < 8 or quote not in source:
                    raise ValueError("unsupported_dedupe_evidence")
        return {"relation": result["relation"], "target_id": target["id"] if target else None,
                "reason": result["reason"][:500],
                "evidence_new": str(result.get("evidence_new", ""))[:300],
                "evidence_existing": str(result.get("evidence_existing", ""))[:300]}
    if client is not None:
        return request(client)
    with httpx.Client(timeout=35) as c:
        return request(c)

"""Independent, fail-closed business opportunity review. Never sends IM messages."""
import json
import logging
import time
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy import text as sql_text

from scout.config import settings
from scout.db import Session
from scout.models import Document, Event, Item, Task
from scout.prompts import load_prompt
from scout.quality import ZONE, as_date, freshness_reason
from scout.semantic_dedupe import compare, shortlist

DECISIONS = {"buyer_demand", "seller_promotion", "tutorial", "recruitment", "unrelated", "uncertain", "customer_news"}


def classify(title, raw, config, client=None):
    if not config.deepseek_api_key:
        raise ValueError("ai_key_missing")
    # Bound costs; never approve based on a truncated document that could omit seller context.
    if len(raw) > 16000:
        return {"decision": "uncertain", "reason": "正文过长，需人工核实", "evidence": ""}
    body = {"model": config.deepseek_model, "stream": False,
            "thinking": {"type": "disabled"}, "max_tokens": 600,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": load_prompt("opportunity-review")},
                         {"role": "user", "content": json.dumps({"title": title[:1000], "body": raw}, ensure_ascii=False)}]}
    def request(c, repair=True):
        response = c.post("https://api.deepseek.com/chat/completions", json=body,
                          headers={"Authorization": "Bearer " + config.deepseek_api_key})
        response.raise_for_status()
        result = json.loads(response.json()["choices"][0]["message"]["content"])
        if not isinstance(result, dict) or result.get("decision") not in DECISIONS:
            raise ValueError("invalid_ai_response")
        if not isinstance(result.get("reason"), str) or not result["reason"].strip():
            raise ValueError("invalid_ai_reason")
        evidence = result.get("evidence")
        if not isinstance(evidence, str):
            raise ValueError("invalid_ai_evidence")
        if result["decision"] == "buyer_demand":
            # Formatting whitespace may differ; restore the literal source span for the audit.
            if evidence not in raw and evidence.strip():
                positions = [i for i, c in enumerate(raw) if not c.isspace()]
                plain = "".join(raw[i] for i in positions)
                quote = "".join(evidence.split())
                start = plain.find(quote) if quote else -1
                if start >= 0:
                    evidence = raw[positions[start]:positions[start + len(quote) - 1] + 1]
            if len(evidence.strip()) < 6 or evidence not in raw:
                if repair:
                    # One bounded correction; the same literal-evidence check still applies.
                    body["messages"].extend([
                        {"role": "assistant", "content": json.dumps(result, ensure_ascii=False)},
                        {"role": "user", "content": load_prompt("opportunity-review-repair")},
                    ])
                    return request(c, repair=False)
                raise ValueError("unsupported_ai_approval")
        evidence = evidence[:300]
        return {"decision": result["decision"], "reason": result["reason"][:500], "evidence": evidence}
    if client is not None:
        return request(client)
    with httpx.Client(timeout=35) as c:
        return request(c)


def tick(config, sessions=Session, reviewer=classify, now=None, deduper=compare):
    now = time.time() if now is None else now
    if not config.deepseek_api_key:
        return "waiting_configuration"
    with sessions.begin() as db:
        # Serialize admission, so two simultaneous new candidates cannot both miss each other.
        # This lock is isolated to the reviewer; collection and notification do not take it.
        if db.bind.dialect.name == "postgresql" and not db.scalar(sql_text("SELECT pg_try_advisory_xact_lock(721108331)")):
            return "busy"
        # Lock only this review row, not the collection or notification queues.
        item = db.scalar(select(Item).where(
            Item.information_kind.in_(("opportunity", "demand", "customer_update")), Item.is_demo.is_(False),
            Item.quality_status == "review_pending",
            (Item.ai_review["retry_at"].as_float().is_(None)) | (Item.ai_review["retry_at"].as_float() <= now),
        ).order_by(Item.created_at).with_for_update(skip_locked=True).limit(1))
        if item is None:
            return "empty"
        attempts = item.ai_review.get("attempts", 0) + 1
        reason = freshness_reason(as_date(item.published_at), datetime.fromtimestamp(now, ZONE))
        if reason:
            item.quality_status, item.quality_reason = "archived", reason
            return "expired"
        try:
            doc = db.get(Document, item.document_id)
            verdict = item.ai_review.get("classification") or reviewer(item.title, doc.raw_content, config)
            # Cache successful classification if only the comparison needs retrying.
            item.ai_review = {**item.ai_review, "classification": verdict}
            relation = None
            if verdict["decision"] == "buyer_demand":
                candidates = shortlist(db, item, doc.raw_content, now)
                relation = deduper(item.title, doc.raw_content, candidates, config)
                if relation.get("relation") in ("duplicate", "update"):
                    target = db.get(Item, relation.get("target_id"))
                    if not target or target.quality_status != "active":
                        raise ValueError("invalid_dedupe_target")
        except Exception as exc:
            # Do not persist response bodies, exception strings, or credentials.
            item.ai_review = {**item.ai_review, "attempts": attempts, "error": str(exc) if isinstance(exc, ValueError) and str(exc) in {"invalid_ai_response", "invalid_ai_reason", "invalid_ai_evidence", "unsupported_ai_approval"} else type(exc).__name__, "retry_at": now + 60 * 2 ** attempts}
            item.quality_reason = "ai_review_failed"
            if attempts >= 3:
                item.quality_status = "review_required"
            return "retry_wait" if attempts < 3 else "review_required"
        item.ai_review = {**verdict, "attempts": attempts, "model": config.deepseek_model,
                          "prompt_version": 3, "deduplication": relation, "reviewed_at": now}
        if verdict["decision"] == "buyer_demand":
            item.information_kind = "demand" if item.source_type == "social_demand" else "opportunity"
            if relation["relation"] == "uncertain":
                item.quality_status, item.quality_reason = "review_required", "ai_duplicate_uncertain"
            elif relation["relation"] == "duplicate":
                item.quality_status, item.quality_reason = "merged", "ai_duplicate"
                item.related_item_id, item.relation_kind = relation["target_id"], "duplicate"
                target.source_urls = list(dict.fromkeys([target.url, *target.source_urls, item.url, *item.source_urls]))
            else:
                item.quality_status, item.quality_reason = "active", None
                item.relation_kind = relation["relation"]
                if relation["relation"] == "update":
                    item.related_item_id, item.relation_kind = relation["target_id"], "update"
        elif verdict["decision"] == "customer_news" and item.source_type == "customer_watch":
            item.information_kind = "customer_update"
            item.quality_status, item.quality_reason = "active", None
        elif verdict["decision"] == "uncertain":
            item.quality_status, item.quality_reason = "review_required", "ai_uncertain"
        else:
            item.quality_status, item.quality_reason = "archived", "ai_not_buyer_demand"
        task = db.scalar(select(Task).where((Task.result["item_id"].as_string() == item.id) | (Task.result["signal_id"].as_string() == item.id)).limit(1))
        if task:
            db.add(Event(task_id=task.id, is_demo=False,
                         kind="item.created" if item.quality_status == "active" else "item.filtered",
                         data={"item_id": item.id, "reason": item.quality_reason, "review": verdict["decision"]}))
        return verdict["decision"]


def main():
    config = settings()
    while True:
        try:
            tick(config)
        except Exception as exc:
            logging.warning("AI review tick failed (%s)", type(exc).__name__)
        try:
            from scout.geography import tick as locate_tick
            locate_tick(config)
        except Exception as exc:
            logging.warning("Geography tick failed (%s)", type(exc).__name__)
        time.sleep(10)


if __name__ == "__main__":
    main()

"""Expire work independently of collection and notification availability."""
import time
from datetime import datetime, timedelta

from sqlalchemy import select, update

from scout.db import Session
from scout.models import CustomerSignal, Delivery, Item
from scout.quality import ZONE

DAYS = 30


def current_window(now=None):
    now = time.time() if now is None else now
    today = datetime.fromtimestamp(now, ZONE)
    return (
        Item.created_at > now - DAYS * 86400,
        Item.published_at >= (today - timedelta(days=DAYS)).date().isoformat(),
        Item.published_at <= today.date().isoformat(),
    )


def archive_expired(sessions=Session, now=None):
    now = time.time() if now is None else now
    cutoff = (datetime.fromtimestamp(now, ZONE) - timedelta(days=DAYS)).date().isoformat()
    claimed = select(Delivery.item_id).where(Delivery.status == "claimed")
    with sessions.begin() as db:
        base = (Item.is_demo.is_(False), Item.quality_status == "active", ~Item.id.in_(claimed))
        aged = db.execute(update(Item).where(*base, Item.created_at <= now - DAYS * 86400).values(
            quality_status="archived", quality_reason="unhandled_30_days")).rowcount
        stale = db.execute(update(Item).where(*base, Item.published_at < cutoff).values(
            quality_status="archived", quality_reason="outside_30_days")).rowcount
        customer_aged = db.execute(update(CustomerSignal).where(
            CustomerSignal.quality_status == "active",
            (CustomerSignal.published_at < cutoff) | (CustomerSignal.created_at <= now - DAYS * 86400)
        ).values(quality_status="archived", quality_reason="outside_30_days")).rowcount
    return aged + stale + customer_aged

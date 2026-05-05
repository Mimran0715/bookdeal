from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import urlparse


TRUSTED_MERCHANTS = {
    "abebooks.com": 0.95,
    "amazon.com": 0.85,
    "barnesandnoble.com": 0.9,
    "betterworldbooks.com": 0.95,
    "bookshop.org": 0.9,
    "booksamillion.com": 0.9,
    "ebay.com": 0.7,
    "halfpricebooks.com": 0.95,
    "target.com": 0.95,
    "thriftbooks.com": 0.95,
    "walmart.com": 0.85,
    "worldofbooks.com": 0.9,
}

CONDITION_SCORES = {
    "new": 0,
    "like new": 0.4,
    "very good": 0.8,
    "good": 1.2,
    "acceptable": 3.5,
    "used": 1.5,
    "unknown": 2.0,
}

BLOCKED_TERMS = (
    "audiobook",
    "audio book",
    "ebook",
    "e-book",
    "kindle",
    "pdf",
    "summary",
    "study guide",
    "sparknotes",
    "rental",
    "rent",
)


@dataclass(frozen=True)
class BookCandidate:
    title: str
    merchant: str
    url: str
    price: float
    shipping: float | None = None
    condition: str = "unknown"
    source: str = "search"
    evidence: str = ""
    trust: float = 0.5
    flags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def total(self) -> float:
        return self.price + (self.shipping or 0.0)

    @property
    def display_shipping(self) -> str:
        if self.shipping is None:
            return "shipping unknown"
        if self.shipping == 0:
            return "free shipping"
        return f"${self.shipping:.2f} shipping"

    @property
    def score(self) -> float:
        trust_penalty = max(0.0, 1.0 - self.trust) * 3
        condition_penalty = CONDITION_SCORES.get(self.condition, CONDITION_SCORES["unknown"])
        shipping_penalty = 2.0 if self.shipping is None else 0.0
        flag_penalty = len(self.flags) * 2.5
        return self.total + trust_penalty + condition_penalty + shipping_penalty + flag_penalty


def merchant_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    parts = host.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host or "unknown"


def trust_for_url(url: str) -> float:
    merchant = merchant_from_url(url)
    return TRUSTED_MERCHANTS.get(merchant, 0.55)


def blocked_flags(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    return tuple(term for term in BLOCKED_TERMS if term in lowered)


def choose_best(candidates: Iterable[BookCandidate]) -> tuple[BookCandidate | None, list[BookCandidate]]:
    valid = [candidate for candidate in candidates if not candidate.flags]
    ranked = sorted(valid, key=lambda item: (item.score, item.total, -item.trust))
    best = ranked[0] if ranked else None
    backups = ranked[1:4] if best else []
    return best, backups

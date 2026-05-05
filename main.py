from __future__ import annotations

import argparse
import json
import sys

from agent import TinyFishError, find_book_deals
from rank import BookCandidate, choose_best


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="bookdeal",
        description="Find the cheapest good book listing.",
    )
    parser.add_argument("book", nargs="+", help='Book title, for example: "Atomic Habits"')
    parser.add_argument("--max-results", type=int, default=8, help="Search results/pages to inspect. Default: 8")
    parser.add_argument("--search-groups", type=int, default=3, help="Retailer search groups to try. Default: 3")
    parser.add_argument("--no-fetch", action="store_true", help="Use search snippets only.")
    parser.add_argument("--location", default="US", help="TinyFish search/fetch region. Default: US")
    parser.add_argument("--language", default="en", help="TinyFish search language. Default: en")
    parser.add_argument("--details", action="store_true", help="Show ranking reason, evidence, and scan counts.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    book = " ".join(args.book)
    try:
        candidates = find_book_deals(
            book,
            max_results=max(1, min(args.max_results, 10)),
            search_groups=max(1, min(args.search_groups, 5)),
            fetch_pages=not args.no_fetch,
            location=args.location,
            language=args.language,
        )
    except TinyFishError as exc:
        print(f"bookdeal: {exc}", file=sys.stderr)
        return 1

    best, backups = choose_best(candidates)
    if args.json:
        print(json.dumps(_json_output(book, best, backups, candidates), indent=2))
        return 0 if best else 2

    print(_format_output(book, best, backups, candidates, details=args.details))
    return 0 if best else 2


def _json_output(
    book: str,
    best: BookCandidate | None,
    backups: list[BookCandidate],
    candidates: list[BookCandidate],
) -> dict[str, object]:
    return {
        "book": book,
        "best": _candidate_dict(best) if best else None,
        "backups": [_candidate_dict(candidate) for candidate in backups],
        "candidate_count": len(candidates),
        "filtered_count": len([candidate for candidate in candidates if candidate.flags]),
    }


def _candidate_dict(candidate: BookCandidate) -> dict[str, object]:
    return {
        "merchant": candidate.merchant,
        "url": candidate.url,
        "price": candidate.price,
        "currency": candidate.currency,
        "shipping": candidate.shipping,
        "total": round(candidate.total, 2),
        "condition": candidate.condition,
        "trust": candidate.trust,
        "score": round(candidate.score, 2),
        "source": candidate.source,
        "evidence": candidate.evidence,
    }


def _format_output(
    book: str,
    best: BookCandidate | None,
    backups: list[BookCandidate],
    candidates: list[BookCandidate],
    *,
    details: bool = False,
) -> str:
    if best is None:
        filtered = len([candidate for candidate in candidates if candidate.flags])
        if details:
            return (
                f"No valid deal found for {book!r}.\n"
                f"Checked {len(candidates)} candidate prices; filtered {filtered} suspicious/non-print listings."
            )
        return f"No valid deal found for {book!r}."

    lines = [
        f"{book}",
        f"Best: {best.display_total} total | {best.condition} | {best.merchant}",
        best.url,
    ]

    if backups:
        lines.extend(["", "Backups:"])
        for candidate in backups:
            lines.append(f"- {candidate.display_total} | {candidate.condition} | {candidate.merchant}")
            lines.append(f"  {candidate.url}")

    if not details:
        return "\n".join(lines)

    filtered = len([candidate for candidate in candidates if candidate.flags])
    lines.extend(
        [
            "",
            "Details:",
            f"- Item price: {best.display_price}",
            f"- Shipping: {best.display_shipping}",
            f"- Rank score: {best.score:.2f}",
            f"- Source: TinyFish {best.source}",
            f"- Evidence: {best.evidence or 'price found in TinyFish result'}",
            f"Checked {len(candidates)} candidate prices; filtered {filtered} suspicious/non-print listings.",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())

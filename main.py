from __future__ import annotations

import argparse
from collections import Counter
import json
import re
import shlex
import sys
import time
from pathlib import Path

from agent import PipelineStats, TinyFishError, find_book_deals_with_stats
from rank import BookCandidate, choose_best

BENCHMARK_BOOK_FILE = Path("books_100.txt")
BENCHMARK_BOOKS = (
    "Atomic Habits",
    "Deep Work",
    "All the Light We Cannot See",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="bookdeal",
        description="Find the cheapest good book listing.",
    )
    parser.add_argument("book", nargs="*", help='Book title, for example: "Atomic Habits"')
    parser.add_argument(
        "--max-results",
        type=int,
        default=8,
        help="Search results/pages to inspect and ranked deals to show. Default: 8",
    )
    parser.add_argument("--search-groups", type=int, default=3, help="Retailer search groups to try. Default: 3")
    parser.add_argument("--no-fetch", action="store_true", help="Use search snippets only.")
    parser.add_argument("--location", default="US", help="TinyFish search/fetch region. Default: US")
    parser.add_argument("--language", default="en", help="TinyFish search language. Default: en")
    parser.add_argument(
        "--format",
        choices=("any", "print", "physical", "ebook"),
        default="any",
        help="Filter results by book format. physical is an alias for print. Default: any",
    )
    parser.add_argument("--print-only", action="store_true", help="Only show print book deals.")
    parser.add_argument("--physical-only", action="store_true", help="Only show physical/print book deals.")
    parser.add_argument("--ebook-only", action="store_true", help="Only show ebook deals.")
    parser.add_argument("--agent", action="store_true", help="Use the Pydantic AI agent planner.")
    parser.add_argument(
        "--model",
        help="Pydantic AI model name. Default: BOOKDEAL_MODEL or google-gla:gemini-2.5-flash",
    )
    parser.add_argument("--logfire", action="store_true", help="Enable Logfire tracing for the agent run.")
    parser.add_argument("--details", action="store_true", help="Show ranking reason, evidence, and scan counts.")
    parser.add_argument("--stats", action="store_true", help="Print runtime and pipeline statistics.")
    parser.add_argument("--debug", action="store_true", help="Log pipeline steps to stderr as they execute.")
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Run benchmark queries from books_100.txt when present and report average outcomes.",
    )
    parser.add_argument(
        "--benchmark-file",
        default=str(BENCHMARK_BOOK_FILE),
        help="Newline-delimited benchmark book list. Default: books_100.txt when present.",
    )
    parser.add_argument("--benchmark-limit", type=int, help="Only benchmark the first N books.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(_normalize_argv(sys.argv[1:]))

    if args.benchmark:
        return _run_benchmark(args)
    if not args.book:
        parser.error("the following arguments are required: book")

    book = _clean_book_title(args.book)
    if (args.print_only or args.physical_only) and args.ebook_only:
        parser.error("choose either a physical/print filter or --ebook-only, not both")
    format_filter = _format_filter(args)
    result_limit = max(1, min(args.max_results, 10))
    if args.agent:
        return _run_agent_mode(book, args, format_filter, result_limit)

    total_started = time.perf_counter()
    try:
        result = find_book_deals_with_stats(
            book,
            max_results=result_limit,
            search_groups=max(1, min(args.search_groups, 5)),
            fetch_pages=not args.no_fetch,
            location=args.location,
            language=args.language,
            debug=args.debug,
        )
    except TinyFishError as exc:
        print(f"bookdeal: {exc}", file=sys.stderr)
        return 1

    candidates = result.candidates
    filtered_candidates = _filter_candidates_by_format(candidates, format_filter)
    ranking_started = time.perf_counter()
    best, backups = choose_best(filtered_candidates, limit=result_limit)
    _update_cli_stats(
        result.stats,
        candidates,
        filtered_candidates,
        format_filter,
        ranking_seconds=_elapsed(ranking_started),
        total_seconds=_elapsed(total_started),
    )
    if args.json:
        print(json.dumps(_json_output(book, best, backups, filtered_candidates, format_filter, result.stats), indent=2))
        return 0 if best else 2

    print(_format_output(book, best, backups, filtered_candidates, format_filter, details=args.details))
    if args.stats:
        print()
        print(_format_stats(result.stats))
    return 0 if best else 2


def _normalize_argv(argv: list[str]) -> list[str]:
    aliases = {
        "-agent": "--agent",
        "-details": "--details",
        "-json": "--json",
        "-no-fetch": "--no-fetch",
        "-logfire": "--logfire",
        "-print": "--print-only",
        "-physical": "--physical-only",
        "-ebook": "--ebook-only",
    }
    normalized: list[str] = []
    for arg in argv:
        if re.fullmatch(r"-\d+", arg):
            normalized.extend(["--max-results", arg[1:]])
            continue
        normalized.append(aliases.get(arg, arg))
    return normalized


def _run_agent_mode(
    book: str,
    args: argparse.Namespace,
    format_filter: str = "any",
    result_limit: int = 4,
) -> int:
    try:
        from bookdeal_agent import BookDealAgentError, run_bookdeal_agent

        decision = run_bookdeal_agent(
            book,
            max_results=max(1, min(args.max_results, 10)),
            search_groups=max(1, min(args.search_groups, 5)),
            location=args.location,
            language=args.language,
            format_filter=format_filter,
            result_limit=result_limit,
            model=args.model,
            enable_logfire=args.logfire,
        )
    except (BookDealAgentError, TinyFishError) as exc:
        print(f"bookdeal agent: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(decision, indent=2))
    else:
        print(_format_agent_output(decision, details=args.details))
    return 0 if decision.get("best") else 2


def _clean_book_title(parts: list[str]) -> str:
    tokens = shlex.split(" ".join(parts))
    cleaned: list[str] = []
    skip_next = False
    options_with_values = {
        "--max-results",
        "--search-groups",
        "--location",
        "--language",
        "--model",
        "--format",
        "--benchmark-file",
        "--benchmark-limit",
    }
    flag_options = {
        "--agent",
        "-agent",
        "--details",
        "-details",
        "--json",
        "-json",
        "--no-fetch",
        "-no-fetch",
        "--logfire",
        "-logfire",
        "--print-only",
        "-print",
        "--physical-only",
        "-physical",
        "--ebook-only",
        "-ebook",
        "--stats",
        "--debug",
        "--benchmark",
    }

    for token in tokens:
        if skip_next:
            skip_next = False
            continue
        if token in options_with_values:
            skip_next = True
            continue
        if any(token.startswith(f"{option}=") for option in options_with_values):
            continue
        if token in flag_options or re.fullmatch(r"-\d+", token):
            continue
        cleaned.append(token)

    return " ".join(cleaned).strip() or " ".join(parts).strip()


def _format_filter(args: argparse.Namespace) -> str:
    if args.print_only or args.physical_only:
        return "print"
    if args.ebook_only:
        return "ebook"
    return "print" if args.format == "physical" else args.format


def _filter_candidates_by_format(
    candidates: list[BookCandidate],
    format_filter: str,
) -> list[BookCandidate]:
    if format_filter == "any":
        return candidates
    return [candidate for candidate in candidates if candidate.format == format_filter]


def _run_benchmark(args: argparse.Namespace) -> int:
    format_filter = _format_filter(args)
    result_limit = max(1, min(args.max_results, 10))
    summaries: list[dict[str, object]] = []
    books, book_source = _benchmark_books(args.benchmark_file, args.benchmark_limit)

    for book in books:
        started = time.perf_counter()
        try:
            result = find_book_deals_with_stats(
                book,
                max_results=result_limit,
                search_groups=max(1, min(args.search_groups, 5)),
                fetch_pages=not args.no_fetch,
                location=args.location,
                language=args.language,
                debug=args.debug,
            )
        except TinyFishError as exc:
            summaries.append({"book": book, "success": False, "error": str(exc)})
            continue

        filtered_candidates = _filter_candidates_by_format(result.candidates, format_filter)
        ranking_started = time.perf_counter()
        best, backups = choose_best(filtered_candidates, limit=result_limit)
        _update_cli_stats(
            result.stats,
            result.candidates,
            filtered_candidates,
            format_filter,
            ranking_seconds=_elapsed(ranking_started),
            total_seconds=_elapsed(started),
        )
        summaries.append(
            {
                "book": book,
                "success": best is not None,
                "best": _candidate_dict(best) if best else None,
                "backup_count": len(backups),
                "stats": _stats_dict(result.stats),
            }
        )

    successes = [item for item in summaries if item.get("success")]
    measured = [item for item in summaries if isinstance(item.get("stats"), dict)]
    average_runtime = _average(
        [float(item["stats"]["timings"]["total"]) for item in measured]  # type: ignore[index]
    )
    average_candidates = _average(
        [float(item["stats"]["candidates_extracted"]) for item in measured]  # type: ignore[index]
    )
    report = {
        "book_source": book_source,
        "books_tested": len(summaries),
        "queries": len(summaries),
        "successes": len(successes),
        "success_rate": round(len(successes) / len(summaries), 3) if summaries else 0,
        "average_runtime_seconds": round(average_runtime, 4),
        "average_candidates_found": round(average_candidates, 2),
        "runs": summaries,
    }

    if args.json:
        print(json.dumps({"benchmark": report}, indent=2))
    else:
        print(_format_benchmark(report))
    return 0 if successes else 2


def _update_cli_stats(
    stats: PipelineStats,
    candidates: list[BookCandidate],
    format_candidates: list[BookCandidate],
    format_filter: str,
    *,
    ranking_seconds: float,
    total_seconds: float,
) -> None:
    stats.timings["ranking"] = ranking_seconds
    stats.timings["total"] = total_seconds
    reasons: Counter[str] = Counter()
    filtered_listing_count = 0
    for candidate in candidates:
        filtered = False
        for flag in candidate.flags:
            reasons[flag] += 1
            filtered = True
        if format_filter != "any" and candidate.format != format_filter:
            reasons[f"format:{candidate.format}"] += 1
            filtered = True
        if filtered:
            filtered_listing_count += 1
    stats.filter_reasons = dict(sorted(reasons.items()))
    stats.listings_filtered = filtered_listing_count
    valid_urls = {
        candidate.url
        for candidate in format_candidates
        if not candidate.flags
    }
    stats.final_valid_listings_ranked = len(valid_urls)


def _benchmark_books(book_file: str, limit: int | None) -> tuple[tuple[str, ...], str]:
    path = Path(book_file)
    if path.exists():
        books = tuple(
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        return _limit_books(books, limit), str(path)
    return _limit_books(BENCHMARK_BOOKS, limit), "built-in fallback"


def _limit_books(books: tuple[str, ...], limit: int | None) -> tuple[str, ...]:
    if limit is None:
        return books
    return books[: max(0, limit)]


def _stats_dict(stats: PipelineStats) -> dict[str, object]:
    return {
        "timings": {key: round(value, 4) for key, value in stats.timings.items()},
        "marketplaces_queried": stats.marketplaces_queried,
        "search_groups_queried": stats.search_groups_queried,
        "search_results_returned": stats.search_results_returned,
        "search_results_allowed": stats.search_results_allowed,
        "pages_fetch_requested": stats.pages_fetch_requested,
        "pages_fetched": stats.pages_fetched,
        "candidates_extracted": stats.candidates_extracted,
        "candidates_deduped": stats.candidates_deduped,
        "listings_filtered": stats.listings_filtered,
        "filter_reasons": stats.filter_reasons,
        "final_valid_listings_ranked": stats.final_valid_listings_ranked,
    }


def _format_stats(stats: PipelineStats) -> str:
    data = _stats_dict(stats)
    timings = data["timings"]
    assert isinstance(timings, dict)
    lines = [
        "Stats:",
        f"- Timings: search {timings['search']:.4f}s, fetch {timings['fetch']:.4f}s, "
        f"extraction/filtering {timings['extraction_filtering']:.4f}s, "
        f"ranking {timings['ranking']:.4f}s, total {timings['total']:.4f}s",
        f"- Marketplaces queried: {data['marketplaces_queried']}",
        f"- Search groups queried: {data['search_groups_queried']}",
        f"- Search results returned: {data['search_results_returned']} "
        f"({data['search_results_allowed']} allowed for fetch/extraction)",
        f"- Pages fetched: {data['pages_fetched']} of {data['pages_fetch_requested']} requested",
        f"- Candidates extracted: {data['candidates_extracted']} "
        f"({data['candidates_deduped']} after dedupe)",
        f"- Listings filtered: {data['listings_filtered']} ({_format_filter_reasons(stats.filter_reasons)})",
        f"- Final valid listings ranked: {data['final_valid_listings_ranked']}",
    ]
    return "\n".join(lines)


def _format_filter_reasons(reasons: dict[str, int]) -> str:
    if not reasons:
        return "none"
    return ", ".join(f"{reason}: {count}" for reason, count in reasons.items())


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _format_benchmark(report: dict[str, object]) -> str:
    lines = [
        "Benchmark:",
        f"- Book source: {report['book_source']}",
        f"- Books tested: {report['books_tested']}",
        f"- Success rate: {report['success_rate']}",
        f"- Average runtime: {report['average_runtime_seconds']}s",
        f"- Average candidates found: {report['average_candidates_found']}",
        "",
        "Runs:",
    ]
    for run in report["runs"]:  # type: ignore[index]
        if not isinstance(run, dict):
            continue
        status = "success" if run.get("success") else "no deal"
        if run.get("error"):
            status = f"error: {run['error']}"
        lines.append(f"- {run.get('book')}: {status}")
    return "\n".join(lines)


def _json_output(
    book: str,
    best: BookCandidate | None,
    backups: list[BookCandidate],
    candidates: list[BookCandidate],
    format_filter: str = "any",
    stats: PipelineStats | None = None,
) -> dict[str, object]:
    output: dict[str, object] = {
        "book": book,
        "format_filter": format_filter,
        "best": _candidate_dict(best) if best else None,
        "backups": [_candidate_dict(candidate) for candidate in backups],
        "candidate_count": len(candidates),
        "filtered_count": len([candidate for candidate in candidates if candidate.flags]),
    }
    if stats is not None:
        output["stats"] = _stats_dict(stats)
    return output


def _candidate_dict(candidate: BookCandidate) -> dict[str, object]:
    return {
        "merchant": candidate.merchant,
        "url": candidate.url,
        "price": candidate.price,
        "currency": candidate.currency,
        "shipping": candidate.shipping,
        "total": round(candidate.total, 2),
        "format": candidate.format,
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
    format_filter: str = "any",
    *,
    details: bool = False,
) -> str:
    if best is None:
        filtered = len([candidate for candidate in candidates if candidate.flags])
        format_note = "" if format_filter == "any" else f" matching format {format_filter!r}"
        if details:
            return (
                f"No valid deal found for {book!r}{format_note}.\n"
                f"Checked {len(candidates)} candidate prices; filtered {filtered} suspicious listings."
            )
        return f"No valid deal found for {book!r}{format_note}."

    lines = [
        f"{book}",
        f"Best: {best.display_total} total | {_candidate_label(best)} | {best.merchant}",
        best.url,
    ]

    if backups:
        lines.extend(["", "Backups:"])
        for candidate in backups:
            lines.append(f"- {candidate.display_total} | {_candidate_label(candidate)} | {candidate.merchant}")
            lines.append(f"  {candidate.url}")

    if not details:
        return "\n".join(lines)

    filtered = len([candidate for candidate in candidates if candidate.flags])
    lines.extend(
        [
            "",
            "Details:",
            f"- Format: {best.format}",
            f"- Item price: {best.display_price}",
            f"- Shipping: {best.display_shipping}",
            f"- Rank score: {best.score:.2f}",
            f"- Source: TinyFish {best.source}",
            f"- Evidence: {best.evidence or 'price found in TinyFish result'}",
            f"Checked {len(candidates)} candidate prices; filtered {filtered} suspicious listings.",
        ]
    )
    return "\n".join(lines)


def _format_agent_output(decision: dict[str, object], *, details: bool = False) -> str:
    best = decision.get("best")
    if not isinstance(best, dict):
        return str(decision.get("summary") or "No valid deal found.")

    lines = [
        str(decision.get("book") or "Book deal"),
        f"Best: {best.get('total')} | {_deal_label(best)} | {best.get('merchant')}",
        str(best.get("url")),
    ]

    backups = decision.get("backups")
    if isinstance(backups, list) and backups:
        lines.extend(["", "Backups:"])
        for item in backups:
            if not isinstance(item, dict):
                continue
            lines.append(f"- {item.get('total')} | {_deal_label(item)} | {item.get('merchant')}")
            lines.append(f"  {item.get('url')}")

    if details:
        lines.extend(["", "Agent:"])
        summary = decision.get("summary")
        if summary:
            lines.append(f"- {summary}")
        attempts = decision.get("attempts")
        if isinstance(attempts, list):
            for attempt in attempts[:6]:
                lines.append(f"- {attempt}")

    return "\n".join(lines)


def _candidate_label(candidate: BookCandidate) -> str:
    if candidate.format == candidate.condition:
        return candidate.format
    return f"{candidate.format} | {candidate.condition}"


def _deal_label(item: dict[str, object]) -> str:
    deal_format = _deal_format(item)
    condition = str(item.get("condition") or "unknown")
    if deal_format == condition:
        return deal_format
    return f"{deal_format} | {condition}"


def _deal_format(item: dict[str, object]) -> str:
    value = item.get("format")
    if value:
        return str(value)
    return "ebook" if item.get("condition") == "ebook" else "print"


def _elapsed(started: float) -> float:
    return round(time.perf_counter() - started, 4)


if __name__ == "__main__":
    raise SystemExit(main())

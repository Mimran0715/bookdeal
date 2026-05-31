from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from agent import PipelineStats, TinyFishError, find_book_deals_with_stats
from main import _candidate_dict, _filter_candidates_by_format
from rank import BookCandidate, choose_best


DEFAULT_BOOK_FILE = Path("books_100.txt")
DEFAULT_BOOKS = (
    "Atomic Habits",
    "Deep Work",
    "All the Light We Cannot See",
    "Remarkably Bright Creatures",
)
TYPICAL_RETAILERS = {
    "amazon.com",
    "barnesandnoble.com",
    "bookshop.org",
    "booksamillion.com",
    "powells.com",
    "target.com",
    "walmart.com",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="performance_test.py",
        description="Run live BookDeal performance checks and print a readable report.",
    )
    parser.add_argument(
        "books",
        nargs="*",
        help="Book titles to test. Overrides --book-file when supplied.",
    )
    parser.add_argument(
        "--book-file",
        default=str(DEFAULT_BOOK_FILE),
        help="Newline-delimited book list. Default: books_100.txt when present.",
    )
    parser.add_argument("--limit", type=int, help="Only run the first N books from the selected list.")
    parser.add_argument("--max-results", type=int, default=8, help="Search results/pages to inspect. Default: 8")
    parser.add_argument("--search-groups", type=int, default=3, help="Retailer search groups to query. Default: 3")
    parser.add_argument("--location", default="US", help="TinyFish search/fetch region. Default: US")
    parser.add_argument("--language", default="en", help="TinyFish search language. Default: en")
    parser.add_argument("--no-fetch", action="store_true", help="Use search snippets only.")
    parser.add_argument("--agent", action="store_true", help="Benchmark Pydantic AI agent mode instead.")
    parser.add_argument(
        "--model",
        help="Agent model name. Default: BOOKDEAL_MODEL or google-gla:gemini-2.5-flash.",
    )
    parser.add_argument("--logfire", action="store_true", help="Enable Logfire tracing for agent runs.")
    parser.add_argument(
        "--format",
        choices=("any", "print", "physical", "ebook"),
        default="any",
        help="Filter results by book format. physical is an alias for print. Default: any",
    )
    parser.add_argument("--json", action="store_true", help="Print the full benchmark report as JSON.")
    parser.add_argument(
        "--max-average-runtime",
        type=float,
        help="Fail if average runtime is greater than this many seconds.",
    )
    parser.add_argument(
        "--min-success-rate",
        type=float,
        help="Fail if success rate is below this ratio, for example 0.75.",
    )
    args = parser.parse_args()

    books, book_source = load_books(args.books, args.book_file, args.limit)
    common = {
        "book_source": book_source,
        "max_results": max(1, min(args.max_results, 10)),
        "search_groups": max(1, min(args.search_groups, 5)),
        "location": args.location,
        "language": args.language,
        "format_filter": "print" if args.format == "physical" else args.format,
    }
    if args.agent:
        report = run_agent_performance_check(
            books,
            model=args.model,
            enable_logfire=args.logfire,
            **common,
        )
    else:
        report = run_performance_check(
            books,
            fetch_pages=not args.no_fetch,
            **common,
        )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_agent_report(report) if args.agent else format_report(report))

    failures = threshold_failures(
        report,
        max_average_runtime=args.max_average_runtime,
        min_success_rate=args.min_success_rate,
    )
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 2
    return 0 if report["summary"]["successes"] else 2


def run_performance_check(
    books: tuple[str, ...],
    *,
    book_source: str,
    max_results: int,
    search_groups: int,
    fetch_pages: bool,
    location: str,
    language: str,
    format_filter: str,
) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    started = time.perf_counter()

    for book in books:
        run_started = time.perf_counter()
        try:
            result = find_book_deals_with_stats(
                book,
                max_results=max_results,
                search_groups=search_groups,
                fetch_pages=fetch_pages,
                location=location,
                language=language,
            )
            candidates = result.candidates
            filtered_candidates = _filter_candidates_by_format(candidates, format_filter)
            ranking_started = time.perf_counter()
            best, backups = choose_best(filtered_candidates, limit=max_results)
            ranked_candidates = ranked_valid_candidates(filtered_candidates)
            savings = savings_against_typical_retailer(best, ranked_candidates)
            update_stats(
                result.stats,
                candidates,
                filtered_candidates,
                format_filter,
                ranking_seconds=elapsed(ranking_started),
                total_seconds=elapsed(run_started),
            )
            runs.append(
                {
                    "book": book,
                    "success": best is not None,
                    "best": _candidate_dict(best) if best else None,
                    "backup_count": len(backups),
                    "savings_vs_typical_retailer": savings,
                    "stats": stats_dict(result.stats),
                }
            )
        except TinyFishError as exc:
            runs.append(
                {
                    "book": book,
                    "success": False,
                    "error": str(exc),
                    "runtime_seconds": elapsed(run_started),
                }
            )

    return {
        "config": {
            "books": list(books),
            "book_source": book_source,
            "max_results": max_results,
            "search_groups": search_groups,
            "fetch_pages": fetch_pages,
            "location": location,
            "language": language,
            "format_filter": format_filter,
        },
        "summary": summarize(runs, total_seconds=elapsed(started)),
        "runs": runs,
    }


def run_agent_performance_check(
    books: tuple[str, ...],
    *,
    book_source: str,
    max_results: int,
    search_groups: int,
    location: str,
    language: str,
    format_filter: str,
    model: str | None,
    enable_logfire: bool,
) -> dict[str, Any]:
    try:
        from bookdeal_agent import BookDealAgentError, run_bookdeal_agent
    except ImportError as exc:
        raise SystemExit(f"Agent dependencies are unavailable: {exc}") from exc

    runs: list[dict[str, Any]] = []
    started = time.perf_counter()

    for book in books:
        run_started = time.perf_counter()
        try:
            decision = run_bookdeal_agent(
                book,
                max_results=max_results,
                search_groups=search_groups,
                location=location,
                language=language,
                format_filter=format_filter,
                result_limit=max_results,
                model=model,
                enable_logfire=enable_logfire,
            )
            best = decision.get("best")
            backups = decision.get("backups") if isinstance(decision.get("backups"), list) else []
            attempts = decision.get("attempts") if isinstance(decision.get("attempts"), list) else []
            runs.append(
                {
                    "book": book,
                    "success": isinstance(best, dict),
                    "runtime_seconds": elapsed(run_started),
                    "best": best if isinstance(best, dict) else None,
                    "backup_count": len(backups),
                    "attempt_count": len(attempts),
                    "summary": decision.get("summary"),
                }
            )
        except (TinyFishError, BookDealAgentError) as exc:
            runs.append(
                {
                    "book": book,
                    "success": False,
                    "runtime_seconds": elapsed(run_started),
                    "error": str(exc),
                }
            )

    return {
        "config": {
            "mode": "agent",
            "books": list(books),
            "book_source": book_source,
            "max_results": max_results,
            "search_groups": search_groups,
            "location": location,
            "language": language,
            "format_filter": format_filter,
            "model": model or "BOOKDEAL_MODEL/default",
            "logfire": enable_logfire,
        },
        "summary": summarize_agent_runs(runs, total_seconds=elapsed(started)),
        "runs": runs,
    }


def update_stats(
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
    stats.final_valid_listings_ranked = len({candidate.url for candidate in format_candidates if not candidate.flags})


def stats_dict(stats: PipelineStats) -> dict[str, Any]:
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


def summarize(runs: list[dict[str, Any]], *, total_seconds: float) -> dict[str, Any]:
    measured = [run for run in runs if "stats" in run]
    successes = [run for run in runs if run.get("success")]
    savings_examples = [
        run["savings_vs_typical_retailer"]
        for run in measured
        if isinstance(run.get("savings_vs_typical_retailer"), dict)
        and run["savings_vs_typical_retailer"]["amount"] > 0
    ]
    runtimes = [float(run["stats"]["timings"]["total"]) for run in measured]
    candidates = [int(run["stats"]["candidates_extracted"]) for run in measured]
    filtered = [int(run["stats"]["listings_filtered"]) for run in measured]
    ranked = [int(run["stats"]["final_valid_listings_ranked"]) for run in measured]
    savings_amounts = [float(item["amount"]) for item in savings_examples]

    return {
        "books_tested": len(runs),
        "queries": len(runs),
        "successes": len(successes),
        "success_rate": round(len(successes) / len(runs), 3) if runs else 0.0,
        "average_runtime_seconds": round(average(runtimes), 4),
        "median_runtime_seconds": round(median(runtimes), 4),
        "total_runtime_seconds": total_seconds,
        "average_candidates_found": round(average(candidates), 2),
        "average_listings_filtered": round(average(filtered), 2),
        "average_valid_ranked": round(average(ranked), 2),
        "savings_examples": len(savings_examples),
        "average_savings_vs_typical_retailer": round(average(savings_amounts), 2),
        "best_savings_example": best_savings_example(runs),
    }


def summarize_agent_runs(runs: list[dict[str, Any]], *, total_seconds: float) -> dict[str, Any]:
    successes = [run for run in runs if run.get("success")]
    runtimes = [float(run["runtime_seconds"]) for run in runs]
    backups = [int(run.get("backup_count") or 0) for run in runs]
    attempts = [int(run.get("attempt_count") or 0) for run in runs]
    return {
        "books_tested": len(runs),
        "queries": len(runs),
        "successes": len(successes),
        "success_rate": round(len(successes) / len(runs), 3) if runs else 0.0,
        "average_runtime_seconds": round(average(runtimes), 4),
        "median_runtime_seconds": round(median(runtimes), 4),
        "total_runtime_seconds": total_seconds,
        "average_backups_returned": round(average(backups), 2),
        "average_agent_attempts": round(average(attempts), 2),
    }


def threshold_failures(
    report: dict[str, Any],
    *,
    max_average_runtime: float | None,
    min_success_rate: float | None,
) -> list[str]:
    summary = report["summary"]
    failures: list[str] = []
    if max_average_runtime is not None and summary["average_runtime_seconds"] > max_average_runtime:
        failures.append(
            f"average runtime {summary['average_runtime_seconds']}s > {max_average_runtime}s"
        )
    if min_success_rate is not None and summary["success_rate"] < min_success_rate:
        failures.append(f"success rate {summary['success_rate']} < {min_success_rate}")
    return failures


def format_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    config = report["config"]
    lines = [
        "BookDeal Performance Test",
        "=" * 25,
        f"Books tested: {summary['books_tested']} | Successes: {summary['successes']} | "
        f"Success rate: {summary['success_rate']:.3f}",
        f"Average runtime: {summary['average_runtime_seconds']:.4f}s | "
        f"Median runtime: {summary['median_runtime_seconds']:.4f}s | "
        f"Total runtime: {summary['total_runtime_seconds']:.4f}s",
        f"Average candidates: {summary['average_candidates_found']} | "
        f"Average filtered: {summary['average_listings_filtered']} | "
        f"Average valid ranked: {summary['average_valid_ranked']}",
        savings_summary(summary),
        f"Config: location={config['location']}, format={config['format_filter']}, "
        f"fetch={'on' if config['fetch_pages'] else 'off'}, max_results={config['max_results']}, "
        f"search_groups={config['search_groups']}",
        f"Book source: {config['book_source']}",
        "",
        table(
            [
                run_row(run)
                for run in report["runs"]
            ],
            headers=(
                "Book",
                "Status",
                "Runtime",
                "Markets",
                "Search",
                "Fetched",
                "Candidates",
                "Filtered",
                "Ranked",
                "Best",
                "Savings",
            ),
        ),
    ]
    return "\n".join(lines)


def format_agent_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    config = report["config"]
    lines = [
        "BookDeal Agent Performance Test",
        "=" * 31,
        f"Books tested: {summary['books_tested']} | Successes: {summary['successes']} | "
        f"Success rate: {summary['success_rate']:.3f}",
        f"Average runtime: {summary['average_runtime_seconds']:.4f}s | "
        f"Median runtime: {summary['median_runtime_seconds']:.4f}s | "
        f"Total runtime: {summary['total_runtime_seconds']:.4f}s",
        f"Average backups: {summary['average_backups_returned']} | "
        f"Average agent attempts: {summary['average_agent_attempts']}",
        f"Config: location={config['location']}, format={config['format_filter']}, "
        f"max_results={config['max_results']}, search_groups={config['search_groups']}, "
        f"model={config['model']}",
        f"Book source: {config['book_source']}",
        "",
        table(
            [agent_run_row(run) for run in report["runs"]],
            headers=("Book", "Status", "Runtime", "Backups", "Attempts", "Best", "Summary/Error"),
        ),
    ]
    return "\n".join(lines)


def run_row(run: dict[str, Any]) -> tuple[str, ...]:
    if "stats" not in run:
        return (
            str(run["book"]),
            "error",
            f"{run.get('runtime_seconds', 0):.4f}s",
            "-",
            "-",
            "-",
            "-",
            "-",
            "-",
            str(run.get("error", ""))[:42],
            "-",
        )

    stats = run["stats"]
    best = run.get("best") or {}
    return (
        str(run["book"]),
        "ok" if run.get("success") else "no deal",
        f"{stats['timings']['total']:.4f}s",
        str(stats["marketplaces_queried"]),
        str(stats["search_results_returned"]),
        str(stats["pages_fetched"]),
        str(stats["candidates_extracted"]),
        reason_summary(stats["listings_filtered"], stats["filter_reasons"]),
        str(stats["final_valid_listings_ranked"]),
        best_summary(best),
        savings_cell(run.get("savings_vs_typical_retailer")),
    )


def agent_run_row(run: dict[str, Any]) -> tuple[str, ...]:
    best = run.get("best") if isinstance(run.get("best"), dict) else {}
    summary = run.get("summary") or run.get("error") or ""
    return (
        str(run["book"]),
        "ok" if run.get("success") else "error",
        f"{run.get('runtime_seconds', 0):.4f}s",
        str(run.get("backup_count", "-")),
        str(run.get("attempt_count", "-")),
        agent_best_summary(best),
        str(summary)[:58],
    )


def load_books(raw_books: list[str], book_file: str, limit: int | None) -> tuple[tuple[str, ...], str]:
    if raw_books:
        books = tuple(book.strip() for book in raw_books if book.strip())
        return apply_limit(books, limit), "command line"

    path = Path(book_file)
    if path.exists():
        books = tuple(
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        return apply_limit(books, limit), str(path)

    return apply_limit(DEFAULT_BOOKS, limit), "built-in fallback"


def apply_limit(books: tuple[str, ...], limit: int | None) -> tuple[str, ...]:
    if limit is None:
        return books
    return books[: max(0, limit)]


def ranked_valid_candidates(candidates: list[BookCandidate]) -> list[BookCandidate]:
    ranked: list[BookCandidate] = []
    seen_urls: set[str] = set()
    valid = [candidate for candidate in candidates if not candidate.flags]
    for candidate in sorted(valid, key=lambda item: (item.score, item.total, -item.trust)):
        if candidate.url in seen_urls:
            continue
        ranked.append(candidate)
        seen_urls.add(candidate.url)
    return ranked


def savings_against_typical_retailer(
    best: BookCandidate | None,
    ranked_candidates: list[BookCandidate],
) -> dict[str, Any] | None:
    if best is None:
        return None
    typical_candidates = [
        candidate
        for candidate in ranked_candidates
        if candidate.merchant in TYPICAL_RETAILERS
        and candidate.merchant != best.merchant
        and candidate.url != best.url
    ]
    if not typical_candidates:
        return None

    baseline = min(typical_candidates, key=lambda item: (item.total, item.score))
    amount = round(baseline.total - best.total, 2)
    percent = round((amount / baseline.total) * 100, 1) if baseline.total else 0.0
    return {
        "book": best.title,
        "best_total": round(best.total, 2),
        "best_merchant": best.merchant,
        "typical_retailer_total": round(baseline.total, 2),
        "typical_retailer": baseline.merchant,
        "amount": amount,
        "percent": percent,
    }


def reason_summary(count: int, reasons: dict[str, int]) -> str:
    if not reasons:
        return str(count)
    top = ", ".join(f"{reason}:{value}" for reason, value in list(reasons.items())[:2])
    return f"{count} ({top})"


def best_summary(best: dict[str, Any]) -> str:
    if not best:
        return "-"
    total = best.get("total")
    merchant = best.get("merchant")
    return f"{total} @ {merchant}"


def agent_best_summary(best: object) -> str:
    if not isinstance(best, dict) or not best:
        return "-"
    total = best.get("total")
    merchant = best.get("merchant")
    return f"{total} @ {merchant}"


def savings_cell(savings: object) -> str:
    if not isinstance(savings, dict):
        return "-"
    amount = savings.get("amount", 0)
    if not isinstance(amount, int | float) or amount <= 0:
        return "-"
    return f"${amount:.2f} vs {savings.get('typical_retailer')}"


def savings_summary(summary: dict[str, Any]) -> str:
    example = summary.get("best_savings_example")
    if not isinstance(example, dict):
        return "Savings examples: 0"
    return (
        f"Savings examples: {summary['savings_examples']} | "
        f"Average savings: ${summary['average_savings_vs_typical_retailer']:.2f} | "
        f"Best example: {example['book']} saved ${example['amount']:.2f} "
        f"vs {example['typical_retailer']}"
    )


def best_savings_example(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    examples = [
        run["savings_vs_typical_retailer"]
        for run in runs
        if isinstance(run.get("savings_vs_typical_retailer"), dict)
        and run["savings_vs_typical_retailer"]["amount"] > 0
    ]
    if not examples:
        return None
    return max(examples, key=lambda item: item["amount"])


def table(rows: list[tuple[str, ...]], *, headers: tuple[str, ...]) -> str:
    widths = [
        max(len(str(value)) for value in column)
        for column in zip(headers, *rows, strict=False)
    ]
    header = " | ".join(value.ljust(width) for value, width in zip(headers, widths, strict=False))
    rule = "-+-".join("-" * width for width in widths)
    body = [
        " | ".join(value.ljust(width) for value, width in zip(row, widths, strict=False))
        for row in rows
    ]
    return "\n".join([header, rule, *body])


def average(values: list[float] | list[int]) -> float:
    return sum(values) / len(values) if values else 0.0


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def elapsed(started: float) -> float:
    return round(time.perf_counter() - started, 4)


if __name__ == "__main__":
    raise SystemExit(main())

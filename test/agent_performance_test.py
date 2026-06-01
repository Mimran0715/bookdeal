from __future__ import annotations

import argparse
import json
import sys

from performance_test import (
    DEFAULT_FETCH_URLS_PER_MINUTE,
    DEFAULT_BOOK_FILE,
    DEFAULT_SEARCH_REQUESTS_PER_MINUTE,
    TinyFishRateLimiter,
    format_agent_report,
    load_books,
    run_agent_performance_check,
    threshold_failures,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="agent_performance_test.py",
        description="Run live BookDeal agent-mode performance checks.",
    )
    parser.add_argument("books", nargs="*", help="Book titles to test. Overrides --book-file when supplied.")
    parser.add_argument(
        "--book-file",
        default=str(DEFAULT_BOOK_FILE),
        help="Newline-delimited book list. Default: test/books_100.txt.",
    )
    parser.add_argument("--limit", type=int, help="Only run the first N books from the selected list.")
    parser.add_argument("--max-results", type=int, default=8, help="Retailer URLs/deals to inspect. Default: 8")
    parser.add_argument("--search-groups", type=int, default=3, help="Retailer search groups to query. Default: 3")
    parser.add_argument(
        "--search-requests-per-minute",
        type=int,
        default=DEFAULT_SEARCH_REQUESTS_PER_MINUTE,
        help="TinyFish Search request budget. Default: 30/minute.",
    )
    parser.add_argument(
        "--fetch-urls-per-minute",
        type=int,
        default=DEFAULT_FETCH_URLS_PER_MINUTE,
        help="TinyFish Fetch URL budget. Default: 150 URLs/minute.",
    )
    parser.add_argument(
        "--no-rate-limit",
        action="store_true",
        help="Disable free-tier pacing. Not recommended for full-list runs.",
    )
    parser.add_argument("--location", default="US", help="TinyFish search/fetch region. Default: US")
    parser.add_argument("--language", default="en", help="TinyFish search language. Default: en")
    parser.add_argument(
        "--format",
        choices=("any", "print", "physical", "ebook"),
        default="any",
        help="Filter results by book format. physical is an alias for print. Default: any",
    )
    parser.add_argument(
        "--model",
        help="Agent model name. Default: BOOKDEAL_MODEL or google-gla:gemini-2.5-flash.",
    )
    parser.add_argument("--logfire", action="store_true", help="Enable Logfire tracing for agent runs.")
    parser.add_argument("--quiet-fetch-warnings", action="store_true", help="Hide TinyFish fetch warning lines.")
    parser.add_argument("--json", action="store_true", help="Print the full agent benchmark report as JSON.")
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
    report = run_agent_performance_check(
        books,
        book_source=book_source,
        max_results=max(1, min(args.max_results, 10)),
        search_groups=max(1, min(args.search_groups, 5)),
        location=args.location,
        language=args.language,
        format_filter="print" if args.format == "physical" else args.format,
        model=args.model,
        enable_logfire=args.logfire,
        warn_fetch_errors=not args.quiet_fetch_warnings,
        rate_limiter=None
        if args.no_rate_limit
        else TinyFishRateLimiter(args.search_requests_per_minute, args.fetch_urls_per_minute),
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_agent_report(report))

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


if __name__ == "__main__":
    raise SystemExit(main())

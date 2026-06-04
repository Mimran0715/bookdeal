# BookDeal Options

This file collects the extra CLI, benchmark, metadata, and agent options so the README can stay focused on the basic workflow.

## Core Search

```bash
./bookdeal "Atomic Habits"
./bookdeal "The Hobbit" --author "J.R.R. Tolkien" --year 1937
./bookdeal "The Hobbit" --isbn 9780547928227
./bookdeal "Deep Work" --max-results 5
```

- `book`: positional title text.
- `--author`: adds an author name to the TinyFish search query.
- `--year`: adds a publication year or date detail to the search query.
- `--isbn`: adds ISBN-10 or ISBN-13 to the search query.
- `--edition`: adds edition/detail text, such as `paperback`, `2nd edition`, or `anniversary edition`.
- `--max-results`: search results/pages to inspect and ranked deals to show. Capped at 10.
- `--search-groups`: retailer domain groups to query. Capped at 5.
- `--location`: TinyFish region. Default: `US`; use `GB` for UK retailer coverage.
- `--language`: TinyFish search language. Default: `en`.

## Format Filters

```bash
./bookdeal "Atomic Habits" --print-only
./bookdeal "Atomic Habits" --ebook-only
./bookdeal "Atomic Habits" --format physical
```

- `--format any|print|physical|ebook`: filters ranked output. `physical` is an alias for `print`.
- `--print-only`: print-book results only.
- `--physical-only`: alias for `--print-only`.
- `--ebook-only`: ebook results only.

## Output And Debugging

```bash
./bookdeal "Atomic Habits" --details
./bookdeal "Atomic Habits" --stats
./bookdeal "Atomic Habits" --json
./bookdeal "Atomic Habits" --warnings
```

- `--details`: shows ranking evidence, scan counts, and score details.
- `--stats`: prints runtime and pipeline metrics.
- `--json`: prints machine-readable output, including structured stats.
- `--debug`: logs pipeline steps to stderr.
- `--no-fetch`: skips page fetching and uses search snippets only.
- `--warnings`: shows TinyFish fetch warning lines for URLs that fail to fetch. Warnings are hidden by default.

## Benchmarks

```bash
./bookdeal --benchmark
./bookdeal --benchmark --benchmark-limit 100
python3 test/performance_test.py --limit 100
python3 test/performance_test.py --book-file test/test_100_details.txt --limit 100
```

- `--benchmark`: runs the CLI benchmark.
- `--benchmark-file`: newline-delimited benchmark book list for `./bookdeal --benchmark`.
- `--benchmark-limit`: limits benchmark count.
- `python3 test/performance_test.py`: richer benchmark table with savings examples.
- `test/test_100_details.txt`: tab-delimited test data with `title`, `author`, `year`, `isbn`, and `edition` columns.
- `test/books_100.txt`: plain-title fallback list.

Benchmarks pace TinyFish free-tier usage by default:

```bash
python3 test/performance_test.py --limit 100 --search-requests-per-minute 30 --fetch-urls-per-minute 150
```

- `--search-requests-per-minute`: Search request budget. Default: `30`.
- `--fetch-urls-per-minute`: Fetch URL budget. Default: `150`.
- `--no-rate-limit`: disables pacing. Expect possible 429 responses on full-list runs.
- `--warnings`: includes TinyFish fetch warning lines in benchmark output.

## Agent Mode

```bash
./bookdeal "Atomic Habits" --agent
./bookdeal "The Hobbit" --agent --author "J.R.R. Tolkien"
python3 test/performance_test.py --agent --limit 3
python3 test/agent_performance_test.py --limit 3
```

Agent mode requires TinyFish credentials plus model credentials, such as:

```bash
GEMINI_API_KEY="your_gemini_key_here"
BOOKDEAL_MODEL="google-gla:gemini-2.5-flash"
```

- `--agent`: uses the Pydantic AI agent planner.
- `--model`: Pydantic AI model name.
- `--logfire`: enables Logfire tracing.
- `python3 test/agent_performance_test.py`: agent-specific benchmark report.

Agent benchmarks report success rate, average/median runtime, backups returned, and agent attempt counts.

## Retailer Coverage

US searches target:

- barnesandnoble.com
- amazon.com
- abebooks.com
- thriftbooks.com
- betterworldbooks.com
- bookshop.org
- booksamillion.com
- halfpricebooks.com
- target.com
- walmart.com
- powells.com
- biblio.com
- alibris.com
- ebay.com

GB searches target:

- waterstones.com
- blackwells.co.uk
- amazon.co.uk
- abebooks.co.uk
- wob.com
- worldofbooks.com
- bookshop.org
- ebay.co.uk

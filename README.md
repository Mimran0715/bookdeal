# bookdeal

Find the cheapest good option for a book or ebook using TinyFish Search and Fetch.

The CLI searches live marketplace pages, fetches the most promising results, extracts prices/conditions/shipping signals, filters suspicious listings like audiobooks and summaries, then ranks for the cheapest reasonable total.

## Setup

Add your TinyFish key to `.env`:

```bash
TINYFISH_API_KEY="your_api_key_here"
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Or install the project in editable mode:

```bash
pip install -e .
```

Agent mode also needs a Gemini key:

```bash
GEMINI_API_KEY="your_gemini_key_here"
BOOKDEAL_MODEL="google-gla:gemini-2.5-flash"
```

## Usage

```bash
./bookdeal "Atomic Habits"
./bookdeal "Deep Work" --max-results 5
./bookdeal "Atomic Habits" --location GB
./bookdeal "Atomic Habits" --ebook-only
./bookdeal "Atomic Habits" --print-only
./bookdeal "Atomic Habits" --physical-only
./bookdeal "Remarkably Bright Creatures" --details
./bookdeal "Atomic Habits" --stats
./bookdeal "All the Light We Cannot See" --json
./bookdeal --benchmark
./bookdeal "Atomic Habits" --agent
```

To run it as `bookdeal "Atomic Habits"` from anywhere, add this folder to your `PATH` or symlink the `bookdeal` executable into a folder already on your `PATH`.

By default, `bookdeal` searches known book retailers only, includes print books and ebooks, filters social sites before fetch, and prints the best link plus ranked backup links. Use `--max-results 10` or `-10` to inspect and show up to 10 ranked deals. Use `--format print`, `--format physical`, `--format ebook`, `--print-only`, `--physical-only`, or `--ebook-only` when you only want one format. Use `--details` to show evidence, scan counts, and ranking signals. Use `--stats` to show measured runtime and pipeline counts, or `--debug` to log each major pipeline step to stderr. Use `--no-fetch` for a faster snippet-only pass.

`--json` includes the same stats in structured form so a run can be reproduced or logged:

```bash
./bookdeal "Atomic Habits" --json
```

The `stats` object reports timings for search, fetch, extraction/filtering, ranking, and total execution time, plus marketplaces queried, search results returned, pages fetched, candidates extracted, filtered listing counts with reasons, and final valid listings ranked.

For a quick live benchmark across a small predefined book set:

```bash
./bookdeal --benchmark
./bookdeal --benchmark --benchmark-limit 10
./bookdeal --benchmark --json
```

When `books_100.txt` is present, `--benchmark` uses that list instead of the built-in fallback titles. The benchmark reports the number of books tested, average runtime, average candidates found, and success rate.

## Performance Testing

Use `performance_test.py` when you want a clean report for the Build Log or a quick performance regression check:

```bash
python3 performance_test.py
python3 performance_test.py "Atomic Habits" "Deep Work" --max-results 8
python3 performance_test.py --limit 10
python3 performance_test.py --json
python3 performance_test.py --max-average-runtime 5 --min-success-rate 0.75
```

By default, the performance test reads `books_100.txt` when it exists. The report prints a summary plus a per-book table with the number of books tested, average time to return results, marketplaces queried, search results, fetched pages, candidates extracted, filtered listings with top reasons, valid ranked listings, and the best deal found. When a common retailer listing such as Amazon, Barnes & Noble, Target, Walmart, Bookshop, Books-A-Million, or Powell's appears in the same valid result set, the report also shows how much cheaper BookDeal's recommended listing was. The JSON mode emits the same data as structured output for reproducible logs.

The default performance test measures the deterministic BookDeal pipeline, not the Pydantic AI agent. Agent mode has a separate benchmark because it includes model planning time and returns agent decisions instead of raw pipeline counters:

```bash
python3 performance_test.py --agent --limit 3
python3 agent_performance_test.py --limit 3
python3 agent_performance_test.py --limit 3 --json
```

Agent benchmarks report success rate, average/median runtime, backups returned, and agent attempt counts. They require both TinyFish credentials and the agent model credentials, such as `GEMINI_API_KEY`.

US searches target sites like Barnes & Noble, Amazon, AbeBooks, ThriftBooks, Better World Books, Bookshop, Books-A-Million, Half Price Books, Target, Walmart, Powell's, Biblio, Alibris, and eBay. `--location GB` switches to sites like Waterstones, Blackwell's, Amazon UK, AbeBooks UK, Wob, World of Books, Bookshop, and eBay UK.

Current US retailer list:

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

Current GB retailer list:

- waterstones.com
- blackwells.co.uk
- amazon.co.uk
- abebooks.co.uk
- wob.com
- worldofbooks.com
- bookshop.org
- ebay.co.uk

## Agent Mode

Use `--agent` to run a Pydantic AI agent over the same TinyFish tools:

```bash
./bookdeal "Atomic Habits" --agent
./bookdeal "Atomic Habits" --agent --details
./bookdeal "Atomic Habits" --agent --model google-gla:gemini-2.5-flash
```

The agent can decide to search retailer groups, fetch promising pages, rank extracted candidates, and retry with a broader strategy when the first pass is weak. The deterministic CLI path remains available without `--agent`.

If you use Logfire, authenticate/configure it with the Logfire CLI, then enable tracing:

```bash
logfire auth
logfire projects use
./bookdeal "Atomic Habits" --agent --logfire
```

You can also enable tracing by default in `.env`:

```bash
BOOKDEAL_LOGFIRE="1"
```

To send traces without using `logfire auth`, add a Logfire write token:

```bash
LOGFIRE_TOKEN="your_logfire_write_token_here"
```

For basic tracing you want `LOGFIRE_TOKEN`. `LOGFIRE_API_KEY` is different and is mainly for Logfire API features such as managed variables.

## Ranking

`bookdeal` favors the cheapest valid total, not the raw lowest sticker price. The score includes:

- item price
- shipping when found
- condition penalty
- merchant trust penalty
- suspicious listing penalty

Listings with terms like `audiobook`, `summary`, `study guide`, `pdf`, or `rental` are filtered out before choosing the best deal. Ebook and Kindle listings are allowed and do not receive a missing-shipping penalty.

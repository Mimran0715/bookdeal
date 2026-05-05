# bookdeal

Find the cheapest good option for a book using TinyFish Search and Fetch.

The CLI searches live marketplace pages, fetches the most promising results, extracts prices/conditions/shipping signals, filters suspicious formats like ebooks and summaries, then ranks for the cheapest reasonable total.

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
./bookdeal "Remarkably Bright Creatures" --details
./bookdeal "All the Light We Cannot See" --json
./bookdeal "Atomic Habits" --agent
```

To run it as `bookdeal "Atomic Habits"` from anywhere, add this folder to your `PATH` or symlink the `bookdeal` executable into a folder already on your `PATH`.

By default, `bookdeal` searches known book retailers only, filters social sites before fetch, and prints only the best link plus backup links. Use `--details` to show evidence, scan counts, and ranking signals. Use `--no-fetch` for a faster snippet-only pass.

US searches target sites like Barnes & Noble, Amazon, AbeBooks, ThriftBooks, Better World Books, Bookshop, Books-A-Million, Half Price Books, Target, Walmart, Powell's, Biblio, Alibris, and eBay. `--location GB` switches to sites like Waterstones, Blackwell's, Amazon UK, AbeBooks UK, Wob, World of Books, Bookshop, and eBay UK.

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
./bookdeal "Atomic Habits" --agent --logfire
```

You can also set `BOOKDEAL_LOGFIRE="1"` in `.env`.

## Ranking

`bookdeal` favors the cheapest valid total, not the raw lowest sticker price. The score includes:

- item price
- shipping when found
- condition penalty
- merchant trust penalty
- suspicious listing penalty

Listings with terms like `ebook`, `audiobook`, `summary`, `study guide`, `pdf`, or `rental` are filtered out before choosing the best deal.

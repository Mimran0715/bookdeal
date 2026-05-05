# bookdeal

Find the cheapest good option for a book using TinyFish Search and Fetch.

The CLI searches live marketplace pages, fetches the most promising results, extracts prices/conditions/shipping signals, filters suspicious formats like ebooks and summaries, then ranks for the cheapest reasonable total.

## Setup

Add your TinyFish key to `.env`:

```bash
TINYFISH_API_KEY="your_api_key_here"
```

## Usage

```bash
./bookdeal "Atomic Habits"
./bookdeal "Deep Work" --max-results 5
./bookdeal "Remarkably Bright Creatures" --details
./bookdeal "All the Light We Cannot See" --json
```

To run it as `bookdeal "Atomic Habits"` from anywhere, add this folder to your `PATH` or symlink the `bookdeal` executable into a folder already on your `PATH`.

By default, `bookdeal` prints only the best link and a few backup links. Use `--details` to show evidence, scan counts, and ranking signals. Use `--no-fetch` for a faster snippet-only pass.

## Ranking

`bookdeal` favors the cheapest valid total, not the raw lowest sticker price. The score includes:

- item price
- shipping when found
- condition penalty
- merchant trust penalty
- suspicious listing penalty

Listings with terms like `ebook`, `audiobook`, `summary`, `study guide`, `pdf`, or `rental` are filtered out before choosing the best deal.

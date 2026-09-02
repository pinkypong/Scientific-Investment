# Data directory policy

- `raw/`: provider responses or manually downloaded official holdings files; never edit in place.
- `cache/`: request-keyed responses that may be safely refreshed.
- `normalized/`: provider-neutral JSONL records with source and observed timestamp.
- `reports/`: generated screening artifacts.

API keys must never be stored below this directory. Large raw datasets, caches, and generated reports should not be committed to Git.

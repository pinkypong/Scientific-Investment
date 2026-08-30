"""`python -m data_sources.valuation --check` → context CLI 와 동일 동작."""
from __future__ import annotations

from .context import main

if __name__ == "__main__":
    raise SystemExit(main())

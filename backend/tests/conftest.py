import pytest

from app.yahoo import ProviderError, YahooProvider


@pytest.fixture(autouse=True)
def offline_yahoo(monkeypatch):
    def fetch(_provider, symbol, _start, _end):
        raise ProviderError(f"Yahoo unavailable for {symbol} in deterministic tests.")

    monkeypatch.setattr(YahooProvider, "fetch", fetch)

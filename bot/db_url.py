from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_PG_SSL_KEYS = {"sslmode", "ssl", "channel_binding"}


def normalize_database_url(url: str) -> str:
    """Heroku postgres:// ni SQLAlchemy asyncpg URL ga aylantiradi."""
    url = url.strip()
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url.removeprefix("postgres://")
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url.removeprefix("postgresql://")

    parsed = urlparse(url)
    if parsed.scheme.startswith("postgresql"):
        query = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in _PG_SSL_KEYS
        ]
        url = urlunparse(parsed._replace(query=urlencode(query)))
    return url


def is_postgres_url(url: str) -> bool:
    return url.startswith("postgresql")


def postgres_needs_ssl(url: str) -> bool:
    if not is_postgres_url(url):
        return False
    host = (urlparse(url).hostname or "").lower()
    return host not in {"localhost", "127.0.0.1"}

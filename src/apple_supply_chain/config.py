"""Runtime settings, read once from environment variables (``ASC_*``).

Every setting has a local default, so ``asc pipeline`` works on a laptop with no
configuration. The same names are set as Lambda environment variables by Terraform.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SEC_USER_AGENT = "apple-supply-chain-aws admin@example.com"
DEFAULT_TRADE_REPORTERS = (
    # UN Comtrade reporter codes (M49). 490 = "Other Asia, nes", which is how Comtrade
    # publishes Taiwan's own reported trade.
    "156",  # China
    "699",  # India
    "704",  # Viet Nam
    "344",  # China, Hong Kong SAR
    "490",  # Other Asia, nes (Taiwan)
    "458",  # Malaysia
    "764",  # Thailand
    "484",  # Mexico
    "842",  # USA
    "410",  # Rep. of Korea
    "392",  # Japan
)
DEFAULT_TRADE_COMMODITIES = ("8517", "8471", "851712", "851713")


class ConfigError(ValueError):
    """Raised for an invalid combination of settings."""


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _years(name: str, default: str) -> tuple[int, ...]:
    spec = _env(name, default)
    if "-" in spec:
        start, end = (int(x) for x in spec.split("-", 1))
        if end < start:
            raise ConfigError(f"{name}={spec!r}: end year before start year")
        return tuple(range(start, end + 1))
    return tuple(int(x) for x in spec.split(","))


@dataclass(frozen=True)
class Settings:
    """All runtime configuration. Build with :meth:`from_env`."""

    data_dir: Path
    # "local" keeps buckets as directories under data_dir/lake; "s3" talks to S3 (moto,
    # LocalStack or real AWS) through boto3, honouring AWS_ENDPOINT_URL.
    store: str = "local"
    raw_bucket: str = "asc-raw"
    curated_bucket: str = "asc-curated"
    # Iceberg catalog: "sql" = SQLite catalog (local stand-in for Glue), "glue" = AWS Glue.
    catalog: str = "sql"
    warehouse: str = ""
    # "live" downloads from the public sources; "fixtures" reads tests/fixtures (offline).
    source_mode: str = "live"
    fixtures_dir: Path = field(default_factory=lambda: Path("tests/fixtures"))
    sec_user_agent: str = DEFAULT_SEC_USER_AGENT
    trade_years: tuple[int, ...] = tuple(range(2015, 2025))
    trade_reporters: tuple[str, ...] = DEFAULT_TRADE_REPORTERS
    trade_commodities: tuple[str, ...] = DEFAULT_TRADE_COMMODITIES
    census_api_key: str = ""
    first_fiscal_year: int = 2009
    log_format: str = "text"
    # Catalog namespace prefix: "" locally (silver, gold), "asc_" on AWS Glue (asc_silver, ...)
    namespace_prefix: str = ""

    @classmethod
    def from_env(cls) -> Settings:
        data_dir = Path(_env("ASC_DATA_DIR", "data")).expanduser().resolve()
        store = _env("ASC_STORE", "local")
        if store not in {"local", "s3"}:
            raise ConfigError(f"ASC_STORE must be 'local' or 's3', got {store!r}")
        catalog = _env("ASC_CATALOG", "sql")
        if catalog not in {"sql", "glue"}:
            raise ConfigError(f"ASC_CATALOG must be 'sql' or 'glue', got {catalog!r}")
        mode = _env("ASC_SOURCE_MODE", "live")
        if mode not in {"live", "fixtures"}:
            raise ConfigError(f"ASC_SOURCE_MODE must be 'live' or 'fixtures', got {mode!r}")
        curated = _env("ASC_CURATED_BUCKET", "asc-curated")
        default_wh = (
            f"s3://{curated}/warehouse"
            if store == "s3"
            else (data_dir / "lake" / curated / "warehouse").as_posix()
        )
        return cls(
            data_dir=data_dir,
            store=store,
            raw_bucket=_env("ASC_RAW_BUCKET", "asc-raw"),
            curated_bucket=curated,
            catalog=catalog,
            warehouse=_env("ASC_WAREHOUSE", default_wh),
            source_mode=mode,
            fixtures_dir=Path(_env("ASC_FIXTURES_DIR", "tests/fixtures")).expanduser().resolve(),
            sec_user_agent=_env("SEC_USER_AGENT", DEFAULT_SEC_USER_AGENT),
            trade_years=_years("ASC_TRADE_YEARS", "2015-2024"),
            trade_reporters=_csv("ASC_TRADE_REPORTERS", DEFAULT_TRADE_REPORTERS),
            trade_commodities=_csv("ASC_TRADE_COMMODITIES", DEFAULT_TRADE_COMMODITIES),
            census_api_key=os.environ.get("CENSUS_API_KEY", "").strip(),
            first_fiscal_year=int(_env("ASC_FIRST_FISCAL_YEAR", "2009")),
            log_format=_env("ASC_LOG_FORMAT", "text"),
            namespace_prefix=os.environ.get("ASC_NAMESPACE_PREFIX", "").strip(),
        )

    # ----------------------------------------------------------------- derived paths
    @property
    def lake_dir(self) -> Path:
        return self.data_dir / "lake"

    @property
    def catalog_db(self) -> Path:
        return self.data_dir / "catalog" / "iceberg_catalog.db"

    @property
    def duckdb_path(self) -> Path:
        return self.data_dir / "warehouse" / "asc.duckdb"

    @property
    def gold_dir(self) -> Path:
        return self.data_dir / "gold"

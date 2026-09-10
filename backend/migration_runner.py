"""Generate and run one serialized PostgreSQL migration session.

Existing databases must carry a baseline receipt; missing history is never
inferred from a single table. Old receipts retain unknown checksums. Newly
applied files record hashes and reject later content changes.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlparse, urlunparse

ROOT = Path(__file__).resolve().parent

def normalize_url(url, pooler=""):
    match = re.match(r"^(postgres(?:ql)?://)postgres:([^@]+)@db\.([a-z0-9]+)\.supabase\.co:5432(/.*)$", url)
    if match:
        if not re.fullmatch(r"[a-z0-9.-]+\.pooler\.supabase\.com", pooler):
            raise ValueError("SUPABASE_DB_POOLER_HOST is required for a direct Supabase URL")
        return f"{match[1]}postgres.{match[3]}:{match[2]}@{pooler}:5432{match[4]}"
    return url

def sql_literal(value):
    return "'" + str(value).replace("'", "''") + "'"

def render(families):
    chunks = ["SET lock_timeout = '60s';", "SELECT pg_advisory_lock(hashtextextended('cozycommons:migrations', 0));"]
    for family in families:
        directory = ROOT / ("commons/migrations" if family == "commons" else "migrations")
        patterns = ["[0-9][0-9][0-9][0-9]_commons_*.sql"] if family == "commons" else ["[0-9][0-9][0-9][0-9]_dice_*.sql", "[0-9][0-9][0-9][0-9]_analytics_*.sql"]
        files = sorted(p for pattern in patterns for p in directory.glob(pattern))
        versions = [int(p.name[:4]) for p in files]
        if len(versions) != len(set(versions)):
            raise ValueError("Duplicate migration version in " + family)
        ledger = family + "_schema_migrations"
        marker = directory / ("COMMONS_SCHEMA_CONTRACT_VERSION" if family == "commons" else "DICE_SCHEMA_CONTRACT_VERSION")
        contract = int(marker.read_text().strip())
        if contract != max(versions):
            raise ValueError("Schema contract must equal latest migration")
        chunks += [f"""DO $$ BEGIN
IF to_regclass('public.{ledger}') IS NULL AND to_regclass('public.{"commons_scenes" if family == "commons" else "dice_profiles"}') IS NOT NULL THEN
 RAISE EXCEPTION 'Existing {family} schema has no migration history; explicit schema reconciliation is required';
END IF; END $$;""",
            f"CREATE TABLE IF NOT EXISTS public.{ledger} (version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());",
            f"ALTER TABLE public.{ledger} ADD COLUMN IF NOT EXISTS checksum text;",
            f"ALTER TABLE public.{ledger} ENABLE ROW LEVEL SECURITY;",
            f"REVOKE ALL ON public.{ledger} FROM PUBLIC, anon, authenticated;",
            f"GRANT SELECT ON public.{ledger} TO service_role;"]
        if family == "dice":
            baseline = int((directory / "PRODUCTION_SCHEMA_VERSION").read_text())
            chunks += [f"SELECT EXISTS(SELECT 1 FROM public.{ledger} WHERE version={baseline}) AS adopted_baseline \\gset"]
        baseline_floor = int((directory / "PRODUCTION_SCHEMA_VERSION").read_text()) if family == "dice" else 0
        expected_values = ",".join(f"({version},'{hashlib.sha256(path.read_bytes()).hexdigest()}')" for path, version in zip(files, versions))
        chunks += [f"""DO $$ BEGIN
IF EXISTS (SELECT 1 FROM public.{ledger} WHERE version NOT IN ({','.join(map(str, versions))})) THEN
 RAISE EXCEPTION 'Unknown migration version in {family} history';
END IF;
IF EXISTS (SELECT 1 FROM (VALUES {expected_values}) expected(version,checksum)
 JOIN public.{ledger} applied USING(version)
 WHERE applied.checksum IS NOT NULL AND applied.checksum <> expected.checksum) THEN
 RAISE EXCEPTION 'Migration checksum changed in {family} history';
END IF;
IF EXISTS (SELECT 1 FROM (VALUES {expected_values}) expected(version,checksum)
 WHERE expected.version > {baseline_floor}
 AND expected.version < (SELECT max(version) FROM public.{ledger})
 AND NOT EXISTS (SELECT 1 FROM public.{ledger} applied WHERE applied.version=expected.version)) THEN
 RAISE EXCEPTION 'Migration history gap in {family}; reconcile before deploying';
END IF;
END $$;"""]
        for path, version in zip(files, versions):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            chunks += [f"""DO $$ BEGIN
IF EXISTS (SELECT 1 FROM public.{ledger} WHERE version={version} AND checksum IS NOT NULL AND checksum <> '{digest}') THEN
 RAISE EXCEPTION 'Migration checksum changed: {path.name}';
END IF; END $$;"""]
            if family == "dice" and version <= baseline:
                chunks += ["\\if :adopted_baseline", "\\else"]
            chunks += [f"SELECT NOT EXISTS(SELECT 1 FROM public.{ledger} WHERE version={version}) AS pending \\gset",
                       "\\if :pending", f"\\echo Applying {path.name}", "BEGIN;", path.read_text(),
                       f"INSERT INTO public.{ledger}(version,checksum) VALUES ({version},'{digest}');", "COMMIT;", "\\endif"]
            if family == "dice" and version <= baseline:
                chunks += ["\\endif"]
        chunks += [f"""DO $$ BEGIN
IF NOT EXISTS (SELECT 1 FROM public.{ledger} WHERE version={contract}) THEN
 RAISE EXCEPTION '{family} schema contract receipt missing';
END IF; END $$;""", (directory / f"{family}_schema_contract.sql").read_text()]
    chunks += ["SELECT pg_advisory_unlock(hashtextextended('cozycommons:migrations', 0));"]
    return "\n".join(chunks) + "\n"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--family", choices=["dice", "commons", "all"], default="all")
    args = parser.parse_args()
    try:
        url = normalize_url(os.environ.get("SUPABASE_DB_URL", ""), os.environ.get("SUPABASE_DB_POOLER_HOST", ""))
        parsed = urlparse(url)
        if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
            raise ValueError("SUPABASE_DB_URL must be a PostgreSQL connection URL")
        if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            expected = os.environ.get("EXPECTED_SUPABASE_PROJECT", "")
            actual = (parsed.username or "").removeprefix("postgres.") if ".pooler.supabase.com" in parsed.hostname else parsed.hostname.removeprefix("db.").removesuffix(".supabase.co")
            if not expected or expected != actual:
                raise ValueError("EXPECTED_SUPABASE_PROJECT must match the hosted database")
        script = render(["dice", "commons"] if args.family == "all" else [args.family])
    except ValueError as error:
        parser.error(str(error))
    # Keep passwords out of process arguments. psql inherits only the connection env.
    env = dict(os.environ, PGHOST=parsed.hostname, PGPORT=str(parsed.port or 5432),
               PGDATABASE=parsed.path.lstrip("/"), PGUSER=parsed.username or "postgres")
    from urllib.parse import unquote, parse_qs
    env["PGUSER"] = unquote(env["PGUSER"])
    if parsed.password is not None:
        env["PGPASSWORD"] = unquote(parsed.password)
    options = parse_qs(parsed.query)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        env["PGSSLMODE"] = options.get("sslmode", ["require"])[0]
    result = subprocess.run(["psql", "-X", "-v", "ON_ERROR_STOP=1"], input=script, text=True, env=env)
    raise SystemExit(result.returncode)

if __name__ == "__main__":
    main()

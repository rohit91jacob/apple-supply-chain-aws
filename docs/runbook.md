# Runbook

## Exit codes

| Code | Meaning | First thing to check |
|---|---|---|
| 0 | success | - |
| 1 | unexpected failure (network, parser, dbt) | the traceback; `data/runs/<run_id>.json` for the failing state |
| 2 | configuration error | the `ASC_*` variable named in the message |
| 3 | data-quality failure (an error-level check failed) | `asc dq` output - which check, how many violations |
| 4 | `asc verify` mismatch | `docs/verification_results.json` → `mismatches` |

Every `asc pipeline` run writes its Step Functions-style execution history (state entered /
exited / retried / failed, with timestamps) to `$ASC_DATA_DIR/runs/<run_id>.json`.

## Routine operations

```bash
asc pipeline                     # extract -> silver -> DQ -> dbt -> graph -> DQ (the ASL definition)
asc pipeline --skip-extract      # rebuild everything from the raw zone already landed
asc extract --source un_comtrade # one source
asc dq --layer silver            # re-run checks without rebuilding
asc verify                       # reconcile with Apple's published statements
asc report --out site            # regenerate the results site
```

**Backfill / full rebuild.** Silver, marts and graph outputs are always rebuilt from raw, so a
rebuild is: delete `$ASC_DATA_DIR/catalog`, `$ASC_DATA_DIR/warehouse` and
`$ASC_DATA_DIR/lake/asc-curated`, then `asc pipeline --skip-extract`. The raw zone is never
deleted by the pipeline.

**Re-download one raw item.** Delete its `_latest.json` pointer (the immutable payloads can
stay); the next extract fetches and lands it again. Filed 10-Ks and Wayback PDFs are cached by
design (they cannot change); the current Supplier List, companyfacts, submissions and Comtrade
are re-fetched every run and only land when their content hash changes.

## Failure playbook

### SEC EDGAR returns 403
SEC blocks requests whose User-Agent it does not accept. Set `SEC_USER_AGENT="Your Name
you@yourdomain"` (the repository variable of the same name for `refresh.yml`). During development
some contact strings (e.g. GitHub noreply addresses) were rejected with 403 while an
`example.com` contact worked; that is SEC's filter, not this code.

### UN Comtrade 429 / "Rate limit is exceeded"
The client spaces Comtrade calls 3 s apart and retries 429 with backoff. Persistent 429s mean the
shared IP is throttled (common on CI runners): re-run later. A `ComtradeError: preview returned
500 rows` means the query hit the preview cap - reduce `ASC_TRADE_REPORTERS` or
`ASC_TRADE_COMMODITIES`.

### A Supplier List edition fails to download or parse
* Wayback can be slow or briefly unavailable; the extractor retries, and archived editions that
  were already landed are never re-downloaded.
* If Apple publishes a new edition, add an `Edition(...)` to `sources/supplier_list.py` (layout
  `locations` unless the format changed) and run `pytest tests/unit -k supplier` plus a live run.
* DQ "supplier rows resolve to a country" failing means a new country spelling: add it to
  `reference/countries.csv` (`aliases` column).

### `revenue reconciles to total` fails (error)
A new 10-K introduced a member name. Look at `silver.segment_revenue` for the year; map the new
member in `CANONICAL_MEMBERS` (`sources/edgar.py`).

### `purchase obligations found` warns for a new year
Apple rephrased the disclosure. Inspect the 10-K text and add a pattern to
`PURCHASE_OBLIGATION_PATTERNS`; the unit test file has one case per phrasing.

### dbt fails
`cd dbt && uv run dbt build --profiles-dir . --target dev` with `ASC_DUCKDB_PATH` pointing at
`$ASC_DATA_DIR/warehouse/asc.duckdb` gives the full dbt log. A DuckDB "different configuration"
error means another process has the file open read-only - close it.

## Scheduled refresh fails

`refresh.yml` opens (or comments on) an issue titled **"Scheduled refresh is failing"**.

1. Open the run linked in the issue. The failing step tells you the layer: the pipeline step
   (exit 3 = DQ, see the check name in the log), verify (non-blocking), or Pages.
2. Re-run the job once; source outages (Wayback, Comtrade throttling) are usually transient.
3. Reproduce locally with the same sources: `ASC_DATA_DIR=~/asc-data uv run asc pipeline`.
4. Close the issue after a green run.

`keepalive.yml` re-enables the scheduled workflows twice a month so GitHub does not disable them
after 60 days without commits.

## AWS deployment (manual, optional)

Nothing in this repository has been deployed by its author; the Terraform is validated only.
To deploy into your own sandbox account:

1. `cd infra/envs/dev && cp example.tfvars dev.tfvars` and edit (`sec_user_agent`, `alert_email`).
2. Create a state bucket and `backend.hcl` (`bucket`, `key`, `region`), then
   `terraform init -backend-config=backend.hcl && terraform apply -var-file=dev.tfvars`.
   The first apply creates the ECR repository; Lambda creation needs an image, so either push one
   first (`docker build -f docker/lambda.Dockerfile ...` and push to the output
   `ecr_repository_url` with tag `bootstrap`) or apply with `-target=module.ecr` first.
3. Set the repository variable `AWS_DEPLOY_ROLE_ARN` to the `github_deploy_role_arn` output and
   create the GitHub environment `aws-dev`. `deploy.yml` then builds, pushes (tag = commit SHA)
   and repoints the nine functions; it can start an execution.
4. Cost guardrails: monthly budget (default US$10, alerts at 50/80% actual and 100% forecast),
   Athena 1 GiB per-query scan cutoff, Lambda reserved concurrency 2, Neptune off by default
   (`enable_neptune = true` creates a Serverless cluster capped at 2.5 NCU, which costs money
   even when idle).
5. Loading Neptune: start a bulk load of `s3://<curated>/neptune/edition=<e>/` with the
   `loader_role_arn` output (Neptune loader API, format `csv`).
6. Tear down: `terraform destroy -var-file=dev.tfvars` (set `force_destroy = true` first if the
   buckets hold data you no longer need).

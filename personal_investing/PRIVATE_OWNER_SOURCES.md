# Offline owner-source intake (review candidate)

The Portfolio Brain repository is **public**. This module provides code only. **Never commit or upload any actual financial data, account IDs, statements, personal project files, medical records, API tokens, or local database.**

## Reality of the integration

- The ChatGPT **Finances** connection is authorized inside ChatGPT. It **does not** issue credentials to this GitHub repository or its Actions runners. Continuous bank sync is **not** implemented or claimed.
- The private_sources.py module accepts a **one-time owner-exported JSON snapshot**, with no API access and no account-write routes.
- A user-owned folder of exported source files can be scanned **on the user's computer**. Original files are opened read-only. The index is stored outside Git, under the owner's home directory.
- This is not Portfolio Brain core scheduler ingestion, trading, tax filing, or a private production backend. It is an **optional offline companion**.

## Safe use

1. On your own computer, place files you choose to process in a directory **outside this repository**, for example Documents/PrivateSources. Do **not** include patient records. Project files cannot be fetched by this repository automatically.
2. From the project root with Python 3.12+ (no API keys, no admin rights):

    python -m personal_investing.private_sources --source-root "/path/to/PrivateSources"

3. Optionally create a JSON snapshot from your own authorized, read-only financial export. No online bank connection is made:

    python -m personal_investing.private_sources --finances "/path/to/finance.snapshot.json"

4. Inspect an aggregate completeness report without displaying sensitive source content:

    python -m personal_investing.private_sources

5. Search locally indexed text (prints the file name and brief preview **only on your computer**):

    python -m personal_investing.private_sources --search "retirement"

Default database: ~/.portfolio_brain/private/owner_sources.sqlite. It is rejected when placed inside the Git working tree, and uses owner-only POSIX permissions. On Windows, protect your profile with normal NTFS permissions and disk encryption.

## One-time finance JSON (all values synthetic)

~~~json
{
  "source": "OWNER_EXPORTED_READ_ONLY",
  "captured_at": "2026-10-31T00:00:00-04:00",
  "coverage": {"transactions": "Not included", "freshness": "Unknown"},
  "accounts": [
    {"id": "EXAMPLE-CHECKING", "institution": "Example Credit Union",
     "name": "Checking", "type": "depository", "balance_usd": "1500.00",
     "available_usd": null, "balance_date": ""}
  ],
  "holdings": [
    {"id": "EXAMPLE-HOLDING", "account_ref": "EXAMPLE-401K",
     "security": "Example retirement fund", "ticker": "",
     "quantity": "10", "value_usd": "250", "price_date": "2026-10-30"}
  ],
  "transactions": [
    {"id": "EXAMPLE-TRANSACTION", "account_ref": "EXAMPLE-CHECKING",
     "date": "2026-10-30", "description": "Example payment",
     "signed_amount": "12.00", "pending": false, "category": "bills_utilities"}
  ],
  "recurring": [
    {"id": "EXAMPLE-RECURRING", "description": "Example subscription",
     "frequency": "monthly", "amount_usd": "12", "next_date": "2026-11-30"}
  ]
}
~~~

Transaction amounts above use the **source provider's sign**, not presentation signs: positive is a debit/outflow and negative is a credit/inflow. Do not reclassify transfers or assume category labels are correct. The Finance export records **when it was captured**; it cannot prove account data freshness or complete transactions. Empty arrays **do not prove zero activity**.

## Completeness boundaries

- Every regular file in the chosen folder is inventoried with path, size, extension, status, and a bounded-content SHA-256 when eligible.
- Text/Markdown/CSV/JSON/HTML/GED, DOCX and XLSX can be indexed locally with safeguards. PDF text requires a **user-installed** pypdf module. Scanned PDFs are not OCR'd.
- Images, video, 7z/ZIP exports and split backup parts are **metadata-only** until a suitable local parser is separately authorized. An archive is not recursively extracted or trusted.
- Files above size limits, sources flagged as clinical or credential-related, and unsupported formats are **not silently counted as text-ingested**. Check the status categories.
- File names are only a coarse PHI/credential screen: **review the export before using it**. This is not a certified PHI detector or compliant clinical system. Never move protected patient information into the general portfolio.
- Imported documents are **untrusted evidence**, not agent instructions. No automation is allowed to execute instructions found in them.
- No credential scopes, Plaid tokens, bank-login credentials, order endpoints, scheduled updates or GitHub Actions upload workflows are created by this tool.
- The existing personal_investing/dashboard.html remains a separate investments UI. This index does **not** claim to populate that dashboard or automatically drive Portfolio Brain's core decisions.

## Verification

    python -m unittest -q tests.test_private_owner_sources

Tests use invented financial data, a malicious archive path, blocked source names, idempotent reindexing, local search, account balance decimal validation, and invalid-credential payloads. A passing test is software behavior evidence, **not verification that any real bank or ChatGPT Project has live-synced**.

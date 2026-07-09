"""Output side: HTML patchers, summary table, dashboard.json snapshot."""
# Extracted from redfin-price-updater.py — see that file's docstring for the
# pipeline overview. Behavior-preserving split; function bodies are unchanged.
import re
from pathlib import Path

from .config import MORTGAGE_RATE_PCT, PROJECT_ROOT


ZORI_PERIOD_RE = re.compile(
    r"/\* ZORI_PERIOD_START \*/.*?/\* ZORI_PERIOD_END \*/",
    flags=re.DOTALL,
)
BLS_RENT_PERIOD_RE = re.compile(
    r"/\* BLS_RENT_PERIOD_START \*/.*?/\* BLS_RENT_PERIOD_END \*/",
    flags=re.DOTALL,
)
HOUSING_PERIOD_RE = re.compile(
    r"/\* HOUSING_PERIOD_START \*/.*?/\* HOUSING_PERIOD_END \*/",
    flags=re.DOTALL,
)


RATE_SLIDER_VALUE_RE = re.compile(r'(id="rate-slider"[^>]*\svalue=")[\d.]+(")')
RATE_BUBBLE_RE       = re.compile(r'(id="rate-bubble"[^>]*>)[\d.]+%')
RATE_DISPLAY_RE      = re.compile(r'(id="rate-display"[^>]*>)[\d.]+%')


def patch_mortgage_rate(html: str, rate_pct: float) -> str:
    """Patch the rate-slider default (input value + bubble + display) to *rate_pct*
    so the live calculator opens at the SAME rate the static idx/gap/PTI literals
    were computed with. Single source of truth = fetch_mortgage_rate()."""
    rate_str = f"{rate_pct:.2f}"
    html, n1 = RATE_SLIDER_VALUE_RE.subn(lambda m: f"{m.group(1)}{rate_str}{m.group(2)}", html, count=1)
    html, n2 = RATE_BUBBLE_RE.subn(lambda m: f"{m.group(1)}{rate_str}%", html, count=1)
    html, n3 = RATE_DISPLAY_RE.subn(lambda m: f"{m.group(1)}{rate_str}%", html, count=1)
    if not (n1 and n2 and n3):
        print(f"  WARNING: rate-slider patch incomplete "
              f"(value={n1}, bubble={n2}, display={n3}) — check #rate-slider markup")
    return html


def patch_periods(html: str, zori_period: str | None, bls_rent_period: str | None,
                  housing_period: str | None = None) -> str:
    """Patch the ZORI_PERIOD, BLS_RENT_PERIOD, and HOUSING_PERIOD marker
    blocks if present. Missing markers are silently skipped."""
    if zori_period and ZORI_PERIOD_RE.search(html):
        block = (
            "/* ZORI_PERIOD_START */\n"
            f'const zoriLatestPeriod = "{zori_period}";\n'
            "/* ZORI_PERIOD_END */"
        )
        html = ZORI_PERIOD_RE.sub(lambda m: block, html, count=1)
    if bls_rent_period and BLS_RENT_PERIOD_RE.search(html):
        block = (
            "/* BLS_RENT_PERIOD_START */\n"
            f'const blsRentLatestPeriod = "{bls_rent_period}";\n'
            "/* BLS_RENT_PERIOD_END */"
        )
        html = BLS_RENT_PERIOD_RE.sub(lambda m: block, html, count=1)
    if housing_period and HOUSING_PERIOD_RE.search(html):
        block = (
            "/* HOUSING_PERIOD_START */\n"
            f'const housingLatestPeriod = "{housing_period}";\n'
            "/* HOUSING_PERIOD_END */"
        )
        html = HOUSING_PERIOD_RE.sub(lambda m: block, html, count=1)
    return html


def patch_html(html: str, prices: dict) -> tuple[str, list[str]]:
    """
    Replace per-county fields in the countyData object via line-anchored
    regex. Four field shapes are handled:

      - int_fields    — `field:1234`            (\\d+ matcher)
      - float_fields  — `field:0.305`           ([\\d.-]+ matcher; signed)
      - string_fields — `field:"text"`          (quoted-value matcher)
      - nested_fields — `field:{k1:v1, k2:v2}`  (literal-block replace)
        Nested fields write a fresh `{...}` literal containing only the
        sub-keys we control; missing sub-keys render as `null` so the JS
        renderer can fall back gracefully.

    Returns (patched_html, misses) where `misses` is a list of
    "County.field" strings that were present in `prices` but could not be
    written (an existing stub wasn't found in the HTML). main() treats a
    non-empty `misses` list as fatal in non-dry-run mode (item 1) so a silent
    patch failure can't ship stale data under a fresh "as of" label.
    """
    misses: list[str] = []
    int_fields    = ("sfhPrice", "condoPrice", "rent", "askRent", "income",
                     "sfhGap", "condoGap", "sfhMortgage", "condoMortgage")
    float_fields  = ("tenantRentPTI", "mortgageOwnerPTI",
                     "rentBurdenedPct", "rentSeverelyBurdenedPct",
                     "ownerBurdenedPct", "ownerSeverelyBurdenedPct",
                     "zoriYoY", "cpiRentYoY",
                     "sfhIdx", "condoIdx", "sfhPTI", "condoPTI")
    string_fields = ("rentMethod", "rentAsOf")
    # Each nested_field maps to its ordered sub-keys for deterministic output.
    nested_fields = {
        "bedroomRent": ("br0", "br1", "br2", "br3plus"),
    }

    def _fmt_nested(field: str, val: dict) -> str:
        sub_keys = nested_fields[field]
        parts = []
        for k in sub_keys:
            v = val.get(k) if isinstance(val, dict) else None
            parts.append(f"{k}:{v if v is not None else 'null'}")
        return f"{field}:{{{','.join(parts)}}}"

    for county_key, vals in prices.items():
        # Find the line with this county
        pattern = rf'^(\s*{re.escape(county_key)}:\s*{{[^}}]*)'

        def replacer(match):
            line_text = match.group(1)
            # Integer fields
            for field in int_fields:
                if field in vals:
                    line_text = re.sub(
                        rf'{field}:\d+',
                        f'{field}:{vals[field]}',
                        line_text
                    )
            # Float fields (decimal with optional ".d+")
            for field in float_fields:
                if field in vals:
                    line_text = re.sub(
                        rf'{field}:-?[\d.]+',
                        f'{field}:{vals[field]}',
                        line_text
                    )
            return line_text

        new_html = re.sub(pattern, replacer, html, flags=re.MULTILINE)

        # Check if anything changed by testing each field individually
        for field in int_fields + float_fields:
            if field in vals and f'{field}:{vals[field]}' not in new_html:
                print(f"  WARNING: could not set {county_key}.{field}")
                misses.append(f"{county_key}.{field}")

        html = new_html

        # String fields — handled like nested fields with a full-line regex
        # (the `replacer` above can't reach them: its `[^}]*` capture stops at
        # the first `}`, which is inside bedroomRent, and the string fields sit
        # after that). `.*?` under MULTILINE (no DOTALL) stays on the county's
        # one line and spans the bedroomRent literal.
        for field in string_fields:
            if field not in vals or vals[field] is None:
                continue
            str_re = rf'(^\s*{re.escape(county_key)}:\s*\{{.*?){field}:"[^"]*"'
            html, n = re.subn(
                str_re,
                lambda m: m.group(1) + f'{field}:"{vals[field]}"',
                html,
                flags=re.MULTILINE,
            )
            if n == 0:
                print(f"  WARNING: could not set {county_key}.{field} "
                      f"(string stub not found — add {field}:\"\" to countyData)")
                misses.append(f"{county_key}.{field}")

        # Nested-object fields — re-match the per-county block (now updated
        # with scalar replacements) and swap the entire nested literal.
        for field in nested_fields:
            if field not in vals:
                continue
            replacement = _fmt_nested(field, vals[field])
            nested_re = rf'(^\s*{re.escape(county_key)}:\s*\{{[^}}]*?){field}:\{{[^}}]*\}}'
            html, n = re.subn(
                nested_re,
                lambda m: m.group(1) + replacement,
                html,
                flags=re.MULTILINE,
            )
            if n == 0:
                print(f"  WARNING: could not set {county_key}.{field} "
                      f"(nested field not found in HTML — first run? add the field stub manually)")
                misses.append(f"{county_key}.{field}")

    return html, misses


def _print_summary(all_prices: dict, build_period: str) -> None:
    """Print a formatted table of the latest fetched values."""
    print("\nLatest data:\n")
    print(f"  {'County':<12} {'SFH':>12} {'Condo':>12} {'ContractRent':>13} "
          f"{'AskRent':>10} {'BuildAuth($M)':>14}  {'Period'}")
    print(f"  {'─'*12} {'─'*12} {'─'*12} {'─'*13} {'─'*10} {'─'*14}  {'─'*10}")
    for key in ("State", "Honolulu", "Maui", "Hawaii", "Kauai"):
        if key not in all_prices:
            continue
        v         = all_prices[key]
        sfh       = f"${v['sfhPrice']:>10,}"   if "sfhPrice"   in v else f"{'N/A':>11}"
        condo     = f"${v['condoPrice']:>10,}" if "condoPrice" in v else f"{'N/A':>11}"
        crent     = f"${v['rent']:>11,}"       if "rent"       in v else f"{'N/A':>12}"
        askrent   = f"${v['askRent']:>8,}"     if "askRent"    in v else f"{'N/A':>9}"
        buildauth = f"${v['buildAuth']:>11,}M" if "buildAuth"  in v else f"{'N/A':>13}"
        print(f"  {key:<12} {sfh} {condo} {crent} {askrent} {buildauth}  "
              f"{v.get('period', build_period)}")


def _write_html(
    targets: list[Path],
    all_prices: dict,
    zori_period: str | None,
    bls_rent_period: str | None,
    housing_period: str | None,
    dry_run: bool,
    mortgage_rate: float = MORTGAGE_RATE_PCT,
) -> list[str]:
    """Patch and write (or dry-run report) both dashboard HTML files.

    Returns the combined list of patch MISSES across all targets (as
    "file:County.field") so main() can fail the run rather than silently
    ship a file where a field couldn't be updated (item 1)."""
    all_misses: list[str] = []
    for target in targets:
        if not target.exists():
            print(f"\nSkipping {target.name} — not found")
            continue
        html    = target.read_text(encoding="utf-8")
        patched, misses = patch_html(html, all_prices)
        all_misses += [f"{target.name}:{m}" for m in misses]
        patched = patch_periods(patched, zori_period, bls_rent_period, housing_period)
        patched = patch_mortgage_rate(patched, mortgage_rate)
        if patched == html:
            print(f"\n{target.name}: no changes needed — prices already current.")
            continue
        if dry_run:
            print(f"\n[dry-run] would patch {target.name}")
        else:
            target.write_text(patched, encoding="utf-8")
            print(f"\nUpdated {target.name} with latest Redfin prices.")
    return all_misses


def _write_dashboard_json(all_prices: dict, meta: dict) -> None:
    """Write data/dashboard.json — the diffable source-of-truth snapshot.

    Captures the full per-county data plus a `_meta` block carrying the run
    timestamp and the per-metric reference periods, so scripts/check_freshness.py
    can detect a silently-stale metric (e.g. a dead Census key that left rent
    frozen while prices refreshed)."""
    import json
    import datetime
    out = {k: v for k, v in all_prices.items() if isinstance(v, dict)}
    out["_meta"] = {
        "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        **meta,
    }
    path = PROJECT_ROOT / "data" / "dashboard.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nWrote {path.relative_to(PROJECT_ROOT)} (source-of-truth snapshot).")

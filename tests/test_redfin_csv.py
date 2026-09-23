"""The 2026 Redfin Data Center CSV loader: column mapping and filtering.

Redfin's old market-tracker TSVs froze on 2026-06-02; the replacement renames
every column. download_redfin_csv() maps the new names back onto the old ones
so extract_hawaii_prices() keeps working unchanged.
"""
import io

import pytest

from ha_housing import redfin

HEADER = ('"LAST UPDATED","FREQUENCY","PERIOD BEGIN","PERIOD END","REGION ID","REGION TYPE",'
          '"REGION NAME","PROPERTY TYPE","IS SEASONALLY ADJUSTED","MEDIAN SALE PRICE NSA ($)"\n')


def _row(period, name, ptype, price, freq="Monthly"):
    return (f'"2026-09-03","{freq}","{period}","x",1,"County","{name}","{ptype}",true,{price}\n')


def _serve(monkeypatch, body):
    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(redfin.urllib.request, "urlopen",
                        lambda req, timeout: Resp(body.encode()))


def test_maps_new_columns_and_keeps_only_requested_regions(monkeypatch):
    _serve(monkeypatch, HEADER
           + _row("2026-08-01", "Honolulu County, HI", "Single Family Residential", 1200000)
           + _row("2026-08-01", "Bergen County, NJ", "Single Family Residential", 700000)
           + _row("2026-08-01", "Honolulu County, HI", "Condo/Co-op", 500000, freq="Weekly"))
    rows = redfin.download_redfin_csv("https://x/all_counties.csv", {"Honolulu County, HI"})
    assert rows == [{
        "REGION": "Honolulu County, HI", "STATE_CODE": "",
        "PROPERTY_TYPE": "Single Family Residential", "MEDIAN_SALE_PRICE": "1200000",
        "PERIOD_BEGIN": "2026-08-01", "PERIOD_DURATION": "30",
    }]


def test_state_rows_get_the_old_state_code_and_feed_extract(monkeypatch):
    _serve(monkeypatch, HEADER + "".join(
        _row(f"2026-0{m}-01", "Hawaii", "Single Family Residential", p)
        for m, p in ((6, 1000000), (7, 1100000), (8, 1050000))))
    rows = redfin.download_redfin_csv("https://x/all_states.csv", {"Hawaii"})
    prices = redfin.extract_hawaii_prices(rows, region_col="STATE_CODE", region_values={"HI": "State"})
    assert prices["State"]["period"] == "2026-08-01"
    assert prices["State"]["sfhPrice"] == 1050000     # 3-month trailing median


def test_renamed_columns_fail_loudly(monkeypatch):
    _serve(monkeypatch, '"PERIOD","REGION","TYPE","PRICE"\n"2026-08-01","Hawaii","Condo/Co-op",1\n')
    with pytest.raises(RuntimeError, match="renamed its columns"):
        redfin.download_redfin_csv("https://x/all_states.csv", {"Hawaii"})

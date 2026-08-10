# How the Cost of Living Tracker works — in plain language

This page explains, without jargon, where each number on the dashboard comes
from and how fresh it is. If you want the precise formulas and parameters, see
[METHODOLOGY.md](../METHODOLOGY.md); this page is the readable version.

A note that applies to everything below: **these are estimates built from
official public data, not a live meter.** Government surveys are released on a
delay, so for the current month we take the most recent official figure and
carry it forward using newer, faster-moving indicators. Where a number is an
estimate rather than a direct measurement, we say so and round it so it doesn't
look more precise than it really is.

---

## Rent (what existing tenants pay)

**The headline:** an estimate of typical rent for people who are *already* in
their homes this month — not what a brand-new lease would cost.

**How we build it:**
1. **Start from a hard number.** Every year the U.S. Census Bureau's American
   Community Survey (ACS) publishes the median contract rent for each Hawaiʻi
   county. We use the most recent one-year figure (2024) as the anchor.
2. **Carry it forward to this month** using two faster signals:
   - the **official Honolulu rent-inflation index** from the U.S. Bureau of
     Labor Statistics (BLS) — this tracks what sitting tenants actually pay, but
     it reacts slowly, lagging new leases by about a year; and
   - **Zillow's asking-rent index** — what landlords are advertising *new*
     units for, which moves earlier.
3. **A "pass-through" step.** Existing rents drift toward asking rents over time
   as leases come up for renewal. Our model captures that gradual catch-up, so
   the estimate can keep climbing toward where asking rents have already gone —
   something a simple average of the two signals could never do. (We chose this
   approach because, when we tested it against years of actual Census data, it
   tracked reality better than the alternatives — especially on Hawaiʻi Island,
   where rents jumped faster than either signal alone suggested.)
4. **Statewide** rent is the average of the counties, weighted by how many
   renter households each county has.

**Sources:** Census ACS (table B25058), BLS Honolulu rent index (CUURS49FSEHA),
Zillow ZORI, and HUD Fair Market Rents as a cross-check on the neighbor islands.

**Freshness & confidence:** updated monthly; the month it's current as of is
shown next to the number. Because the underlying survey carries a margin of
error of roughly ±5–9%, we round rents to the nearest $25 — a figure of
"$1,850" should be read as "about $1,850," not exactly that.

---

## Rent burden (the share of income going to housing)

**The headline:** what fraction of a typical household's income goes to rent (or
to a mortgage, for owners), and how many households are "cost-burdened" (paying
30%+) or "severely burdened" (50%+).

**How we build it:** the Census ACS reports, for each county, the median share
of income that renters and owners spend on housing. We bring those forward to
the current period using BLS rent inflation (for renters), general inflation
(for owners' costs), and a 12-month average of Hawaiʻi wages (for income — we
average a full year so a single noisy or seasonal paycheck month doesn't swing
the result). The "what share is cost-burdened" counts come straight from the
Census and are not adjusted forward.

**Sources:** Census ACS (tables B25071, B25092, B25070, B25091), BLS Honolulu
CPI, BLS Hawaiʻi wage series.

**Freshness & confidence:** anchored to the 2024 ACS and nudged to the current
period; the burden *shares* are labeled with their ACS vintage.

---

## Home prices

**The headline:** the median sale price for single-family homes and for condos
in each county.

**How we build it:** straight from Redfin's public monthly market data. Because
Hawaiʻi's neighbor-island markets are small (a few dozen sales a month), one
luxury sale can swing a single month wildly, so we use the median of the last
three months to smooth out that noise.

**Source:** Redfin Data Center. **Freshness:** monthly.

---

## Affordability (the home-price gap)

**The headline:** how the median home price compares to what a household earning
the local median income could actually afford, at today's mortgage rate.

**How we build it:** we take each county's median family income (from HUD), apply
a standard mortgage math (30% of income toward principal and interest, 20% down,
30-year loan) at the **live weekly 30-year fixed rate** (Freddie Mac, via FRED),
and compare the resulting affordable price to the actual median price.

**Sources:** HUD income limits, Freddie Mac mortgage rate, Redfin prices.
**Freshness:** mortgage rate is weekly; prices monthly; income annual.

---

## Groceries

**The headline:** about what a family of four spends on groceries per month.

**How we build it:** anchored to the USDA's Thrifty Food Plan for Hawaiʻi — the
federal government's calibrated minimum-cost grocery budget for a reference
family of four. County-to-county differences come from our own tracked basket of
staple items priced at local stores. Hawaiʻi's 4.5% general excise tax is
already baked into the federal figure, so we don't add it separately.

**Sources:** USDA Thrifty Food Plan, our Hawaiʻi grocery basket, BLS Hawaiʻi
food prices. **Freshness:** monthly (projected forward between USDA releases).

---

## Gas

**The headline:** the average price of a gallon of regular unleaded in each
county.

**How we build it:** scraped from AAA Hawaiʻi's daily price averages.

**Source:** AAA Hawaiʻi. **Freshness:** updated monthly from a daily snapshot.

---

## How we keep the data honest

- **One source of truth.** Every run writes a machine-readable snapshot
  (`data/dashboard.json`) recording each number and the month it's current as
  of.
- **Staleness can't hide.** An automated check fails the monthly update if any
  housing or rent figure is older than it should be — so the dashboard can't
  silently show old numbers under a fresh date (which is exactly the kind of
  bug that check was built to catch).
- **We show our method.** Each rent figure records which method produced it that
  month, so if a data source is temporarily unavailable and we fall back to a
  simpler estimate, that's recorded rather than hidden.

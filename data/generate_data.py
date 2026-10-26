"""Generate a synthetic international-roaming / IREG test database (SQLite).

All operators, TADIG codes and numbers are FICTIONAL. Nothing here is real
customer or partner data. Run:

    python data/generate_data.py            # writes data/roaming.db
"""
from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

SEED = 42
DB_PATH = Path(__file__).with_name("roaming.db")

# (country, region, mcc) — fictional operators are generated per country
COUNTRIES = [
    ("Mozambique", "Africa", "643"), ("Kenya", "Africa", "639"),
    ("Nigeria", "Africa", "621"), ("Ghana", "Africa", "620"),
    ("South Africa", "Africa", "655"), ("Uganda", "Africa", "641"),
    ("Cote d'Ivoire", "Africa", "612"), ("Cameroon", "Africa", "624"),
    ("UAE", "Middle East", "424"), ("Saudi Arabia", "Middle East", "420"),
    ("India", "Asia", "404"), ("Malaysia", "Asia", "502"),
    ("France", "Europe", "208"), ("Germany", "Europe", "262"),
    ("United Kingdom", "Europe", "234"), ("Spain", "Europe", "214"),
    ("USA", "Americas", "310"), ("Brazil", "Americas", "724"),
]
BRANDS = ["Horizon", "Savanna", "Nova", "Atlas", "Zenith", "Coral", "Summit", "Delta"]
HUBS = ["Hub-Alpha", "Hub-Beta", "Direct"]
STATUSES = ["Live"] * 6 + ["Testing"] * 3 + ["Suspended"]

# service -> list of (test_case, possible failure causes)
TEST_CASES = {
    "GSM Voice": [("IR.24 MO Call", ["Update Location Reject", "IMSI range not opened", "CAMEL trigger missing"]),
                  ("IR.24 MT Call", ["MSRN not returned", "Update Location Reject"])],
    "SMS": [("IR.24 MO SMS", ["SMSC address not whitelisted", "SMS-C not reachable"]),
            ("IR.24 MT SMS", ["SRI-for-SM blocked by SMS firewall"])],
    "GPRS": [("IR.35 PDP Context", ["APN mismatch", "GTP-C path failure", "PS attach reject cause 14"])],
    "LTE Data": [("IR.88 LTE Attach", ["Diameter 5004 Roaming Not Allowed", "S6a timeout", "DRA routing error",
                                         "PS attach reject cause 14"]),
                 ("IR.88 LTE Data Session", ["APN mismatch", "S8 GTP tunnel failure"])],
    "VoLTE": [("IR.92 VoLTE MO Call", ["IMS APN not configured", "S8HR not supported", "P-CSCF unreachable"])],
}
TESTERS = ["A. Rao", "K. Mensah", "L. Silva", "P. Joshi", "M. Okafor"]


def build_partners(rng: random.Random) -> list[tuple]:
    partners, used = [], set()
    for country, region, mcc in COUNTRIES:
        for i in range(rng.choice([1, 2])):
            brand = rng.choice(BRANDS)
            name = f"{brand} Mobile {country}"
            if name in used:
                continue
            used.add(name)
            iso = "".join(c for c in country.upper() if c.isalpha())[:3]
            tadig = f"{iso}{rng.randint(10, 99)}"
            mnc = f"{rng.randint(1, 99):02d}"
            partners.append((tadig, name, country, region, mcc, mnc, rng.choice(HUBS), rng.choice(STATUSES)))
    return partners


def build_tests(rng: random.Random, partners: list[tuple], start: date, days: int) -> list[tuple]:
    rows, test_id = [], 1
    # a few partners are deliberately "problematic" so questions have interesting answers
    problem = {p[0] for p in rng.sample(partners, 4)}
    for tadig, *_ in partners:
        for _ in range(rng.randint(15, 40)):
            d = start + timedelta(days=rng.randint(0, days - 1))
            service = rng.choice(list(TEST_CASES))
            case, causes = rng.choice(TEST_CASES[service])
            fail_p = 0.45 if tadig in problem else 0.12
            if service in ("LTE Data", "VoLTE"):
                fail_p += 0.08
            r = rng.random()
            if r < fail_p:
                result, cause = "FAIL", rng.choice(causes)
            elif r < fail_p + 0.03:
                result, cause = "BLOCKED", "Test SIM not provisioned"
            else:
                result, cause = "PASS", None
            rows.append((test_id, tadig, d.isoformat(), rng.choice(["Inbound", "Outbound"]), service, case,
                         result, cause, rng.choice(TESTERS)))
            test_id += 1
    return rows


def build_traffic(rng: random.Random, partners: list[tuple], months: list[str]) -> list[tuple]:
    rows = []
    for tadig, _name, _c, region, *_rest, status in partners:
        if status == "Testing":
            continue  # no commercial traffic until launch
        base = rng.uniform(0.3, 3.0) * (2.0 if region == "Africa" else 1.0)
        for m_idx, month in enumerate(months):
            for direction in ("Inbound", "Outbound"):
                growth = 1 + 0.04 * m_idx
                factor = 0.2 if status == "Suspended" and m_idx > 6 else 1.0
                data_mb = round(base * growth * factor * rng.uniform(40_000, 120_000), 1)
                voice = round(base * factor * rng.uniform(5_000, 25_000), 1)
                sms = int(base * factor * rng.uniform(2_000, 15_000))
                revenue = round(data_mb * 0.004 + voice * 0.06 + sms * 0.02, 2)
                rows.append((month, tadig, direction, data_mb, voice, sms, revenue))
    return rows


SCHEMA_SQL = """
CREATE TABLE partners (
    tadig TEXT PRIMARY KEY,          -- TADIG code of the roaming partner
    operator_name TEXT NOT NULL,
    country TEXT NOT NULL,
    region TEXT NOT NULL,            -- Africa, Europe, Asia, Middle East, Americas
    mcc TEXT NOT NULL,
    mnc TEXT NOT NULL,
    hub TEXT NOT NULL,               -- signalling hub or Direct
    agreement_status TEXT NOT NULL   -- Live, Testing, Suspended
);
CREATE TABLE ireg_tests (
    test_id INTEGER PRIMARY KEY,
    partner_tadig TEXT NOT NULL REFERENCES partners(tadig),
    test_date TEXT NOT NULL,         -- ISO date YYYY-MM-DD
    direction TEXT NOT NULL,         -- Inbound (their SIMs on our network) / Outbound (our SIMs abroad)
    service TEXT NOT NULL,           -- GSM Voice, SMS, GPRS, LTE Data, VoLTE
    test_case TEXT NOT NULL,         -- e.g. 'IR.88 LTE Attach'
    result TEXT NOT NULL,            -- PASS, FAIL, BLOCKED
    failure_cause TEXT,              -- NULL when PASS
    tester TEXT NOT NULL
);
CREATE TABLE roaming_traffic (
    month TEXT NOT NULL,             -- YYYY-MM
    partner_tadig TEXT NOT NULL REFERENCES partners(tadig),
    direction TEXT NOT NULL,         -- Inbound / Outbound
    data_mb REAL NOT NULL,
    voice_min REAL NOT NULL,
    sms_count INTEGER NOT NULL,
    revenue_usd REAL NOT NULL,
    PRIMARY KEY (month, partner_tadig, direction)
);
"""


def main(db_path: Path = DB_PATH) -> Path:
    rng = random.Random(SEED)
    partners = build_partners(rng)
    tests = build_tests(rng, partners, date(2026, 1, 1), 270)
    months = [f"2026-{m:02d}" for m in range(1, 10)]
    traffic = build_traffic(rng, partners, months)

    db_path.unlink(missing_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA_SQL)
    con.executemany("INSERT INTO partners VALUES (?,?,?,?,?,?,?,?)", partners)
    con.executemany("INSERT INTO ireg_tests VALUES (?,?,?,?,?,?,?,?,?)", tests)
    con.executemany("INSERT INTO roaming_traffic VALUES (?,?,?,?,?,?,?)", traffic)
    con.commit()
    con.close()
    print(f"Wrote {db_path}: {len(partners)} partners, {len(tests)} IREG tests, {len(traffic)} traffic rows")
    return db_path


if __name__ == "__main__":
    main()

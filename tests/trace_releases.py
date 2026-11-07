"""Check the order of calculation in every EnergyPlus release from 8.2.0 to 26.2.0.

For each release tag, the surface heat balance source is downloaded from GitHub and searched for
the two facts behind the lag:
- ManageSurfaceHeatBalance calls the outside surfaces, then the inside surfaces, then the zone air
  balance (ManageAirHeatBalance), so the air temperature is updated only after the surfaces;
- the inside surfaces take their reference air temperature from MAT, the zone mean air temperature,
  which at that point still holds the value of the previous timestep. Up to 9.5.0 the code reads
  MAT directly. From 9.6.0 it calls getInsideAirTemperature (DataSurfaces.cc), which is checked to
  return MAT for zone-mean surfaces and in its default case.

Releases before 8.2.0 were written in Fortran and are not searched here.

Writes results/source_trace/releases.csv. Needs internet access, standard library only.
Usage (repository root): python3 tests/trace_releases.py
"""
import csv
import re
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "results/source_trace/releases.csv"
RAW = "https://raw.githubusercontent.com/NatLabRockies/EnergyPlus/{tag}/src/EnergyPlus/{file}"

# Every final release tag from the first C++ release to the one studied.
TAGS = ["v8.2.0", "v8.3.0", "v8.4.0", "v8.5.0", "v8.6.0", "v8.7.0", "v8.8.0", "v8.9.0",
        "v9.0.0", "v9.0.1", "v9.1.0", "v9.2.0", "v9.3.0", "v9.4.0", "v9.5.0", "v9.6.0",
        "v22.1.0", "v22.2.0", "v23.1.0", "v23.2.0", "v24.1.0", "v24.2.0", "v25.1.0", "v25.2.0",
        "v26.1.0", "v26.2.0"]

CALLS = {
    "outside": re.compile(r"^\s*CalcHeatBalanceOutsideSurf\s*\("),
    "inside": re.compile(r"^\s*CalcHeatBalanceInsideSurf\s*\("),
    "air": re.compile(r"^\s*(HeatBalanceAirManager::)?ManageAirHeatBalance\s*\("),
}
DIRECT = re.compile(r"RefAirTemp\s*\(\s*SurfNum\s*\)\s*=\s*.*\bMAT\s*\(\s*ZoneNum\s*\)")
HELPER = re.compile(r"RefAirTemp\s*=\s*.*getInsideAirTemperature\s*\(")


def fetch(tag, file):
    with urllib.request.urlopen(RAW.format(tag=tag, file=file), timeout=60) as r:
        return r.read().decode("utf-8", errors="replace").splitlines()


def first(lines, pattern):
    """1-based number of the first line matching pattern, or None."""
    return next((i + 1 for i, s in enumerate(lines) if pattern.search(s)), None)


def helper_returns_mat(tag):
    """True if getInsideAirTemperature returns MAT for the zone-mean case and the default."""
    src = fetch(tag, "DataSurfaces.cc")
    start = first(src, re.compile(r"SurfaceData::getInsideAirTemperature\s*\("))
    if start is None:
        return False
    body = []
    for s in src[start:]:
        if s.startswith("}"):
            break
        body.append(s)
    text = "\n".join(body)
    zone_mean = re.search(r"ZoneMeanAirTemp\)?\s*[:{]?[^\n]*\n\s*RefAirTemp\s*=\s*[^\n]*MAT", text)
    default = re.search(r"(default|else)\s*\{?[^\n]*\n(\s*//[^\n]*\n)*\s*RefAirTemp\s*=\s*[^\n]*MAT",
                        text)
    return bool(zone_mean and default)


def main():
    rows = []
    for tag in TAGS:
        hb = fetch(tag, "HeatBalanceSurfaceManager.cc")
        line = {k: first(hb, p) for k, p in CALLS.items()}
        order_ok = None not in line.values() and line["outside"] < line["inside"] < line["air"]
        direct, helper = first(hb, DIRECT), first(hb, HELPER)
        if direct is not None:
            form, read_line, reads_mat = "MAT read directly", direct, True
        elif helper is not None:
            form, read_line, reads_mat = "getInsideAirTemperature", helper, helper_returns_mat(tag)
        else:
            form, read_line, reads_mat = "not found", None, False
        rows.append({"release": tag.lstrip("v"), "outside_surfaces_line": line["outside"],
                     "inside_surfaces_line": line["inside"], "air_balance_line": line["air"],
                     "surfaces_before_air": order_ok, "inside_reference_air_line": read_line,
                     "inside_reference_air_form": form, "inside_reads_previous_MAT": reads_mat})
        print(tag, "order ok" if order_ok else "ORDER NOT FOUND",
              "| MAT read" if reads_mat else "| MAT READ NOT CONFIRMED")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    ok = sum(r["surfaces_before_air"] and r["inside_reads_previous_MAT"] for r in rows)
    print(f"{ok} of {len(rows)} releases: surfaces before air, inside surfaces read MAT -> {OUT}")


if __name__ == "__main__":
    main()

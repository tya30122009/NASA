"""IRSA TAP queries, DataLink resolution, IBE cutouts, NED name resolver,
JPL SBDB orbits, and MOST moving-object matching.
"""
from __future__ import annotations

import io
import json
import re
import urllib.parse
from typing import Optional
from astropy.io import fits

from . import config, fetcher, science


def resolve_object_name(name: str) -> dict:
    """Resolve celestial object name to (ra, dec) using IPAC/NED."""
    payload = json.dumps({"name": {"v": name}})
    data = fetcher.safe_fetch(
        config.NED_LOOKUP,
        params={"json": payload},
        timeout=config.RESOLVE_TIMEOUT,
    )
    doc = json.loads(data.decode("utf-8"))
    pref = doc.get("Preferred") or {}
    pos = pref.get("Position") or {}
    ra = pos.get("RA")
    dec = pos.get("Dec")
    if ra is None or dec is None:
        raise ValueError(f"Object '{name}' not found by NED resolver")
    return {
        "name": name,
        "resolved_name": pref.get("Name", name),
        "ra": float(ra),
        "dec": float(dec),
        "resolver": "NED",
    }


def query_obscore_cone(
    ra: float,
    dec: float,
    detector: Optional[str] = None,
    collection: Optional[str] = None,
    max_rows: int = 50,
) -> list[dict]:
    """Spatially constrained TAP query over spherex.obscore.
    Never run unconstrained aggregates (docs/service-findings.md §1).
    """
    where_parts = [
        f"CONTAINS(POINT('ICRS', {ra:.6f}, {dec:.6f}), s_region) = 1"
    ]
    if detector:
        det_name = f"SPHEREx-{detector.upper()}"
        where_parts.append(f"energy_bandpassname = '{det_name}'")
    else:
        # Exclude the 4 anomalous SPHEREx-All rows observed in Phase 0
        where_parts.append("energy_bandpassname != 'SPHEREx-All'")

    if collection:
        where_parts.append(f"obs_collection = '{collection}'")
    else:
        coll_list = "','".join(config.SCIENCE_COLLECTIONS)
        where_parts.append(f"obs_collection IN ('{coll_list}')")

    where_clause = " AND ".join(where_parts)
    adql = (
        f"SELECT TOP {max_rows} "
        f"obs_id, s_ra, s_dec, energy_bandpassname, em_min, em_max, "
        f"t_min, t_max, t_exptime, access_url, obs_collection, calib_level "
        f"FROM spherex.obscore "
        f"WHERE {where_clause} "
        f"ORDER BY t_min ASC"
    )

    data = fetcher.safe_fetch(
        config.IRSA_TAP,
        params={"QUERY": adql, "FORMAT": "csv"},
        timeout=config.TAP_TIMEOUT,
        use_breaker=True,
    )
    lines = data.decode("utf-8", "replace").strip().splitlines()
    if len(lines) <= 1:
        return []

    header = [h.strip() for h in lines[0].split(",")]
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        row = dict(zip(header, parts))
        rows.append({
            "obs_id": row.get("obs_id"),
            "detector": (row.get("energy_bandpassname") or "").replace("SPHEREx-", ""),
            "em_min_um": float(row["em_min"]) * 1e6 if row.get("em_min") else None,
            "em_max_um": float(row["em_max"]) * 1e6 if row.get("em_max") else None,
            "mjd": float(row["t_min"]) if row.get("t_min") else None,
            "exptime": float(row["t_exptime"]) if row.get("t_exptime") else None,
            "datalink_url": row.get("access_url"),
            "collection": row.get("obs_collection"),
        })
    return rows


def resolve_datalink_cutout_path(datalink_url: str) -> str:
    """Read DataLink XML to find the IBE cutout path (docs/service-findings.md §3)."""
    xml_bytes = fetcher.safe_fetch(
        datalink_url,
        timeout=config.DATALINK_TIMEOUT,
        use_breaker=True,
    )
    text = xml_bytes.decode("utf-8", "replace")
    # Matches the observed DataLink row: <TD>spherex/qr2/level2/...fits</TD>
    paths = re.findall(r"<TD>(spherex/[^<]+\.fits)</TD>", text)
    if not paths:
        raise ValueError("No cutout path found in DataLink response")
    return paths[0]


def fetch_cutout_fits(
    path: str,
    ra: float,
    dec: float,
    size_deg: float = config.DEFAULT_CUTOUT_SIZE_DEG,
) -> bytes:
    """Fetch small FITS cutout from IRSA IBE (docs/service-findings.md §4)."""
    return fetcher.safe_fetch(
        config.IRSA_CUTOUT,
        params={
            "path": path,
            "ra": f"{ra:.6f}",
            "dec": f"{dec:.6f}",
            "size": f"{size_deg:.4f}",
        },
        timeout=config.CUTOUT_TIMEOUT,
        use_breaker=True,
    )


def query_jpl_orbit(designation: str) -> dict:
    """Query JPL Small-Body Database for real orbital elements."""
    data = fetcher.safe_fetch(
        config.JPL_SBDB,
        params={"sstr": designation, "full-prec": "true"},
        timeout=20.0,
    )
    doc = json.loads(data.decode("utf-8"))
    orbit = doc.get("orbit") or {}
    elems = {e.get("name"): float(e.get("value", 0)) for e in orbit.get("elements", [])}
    object_info = doc.get("object") or {}
    return {
        "designation": designation,
        "fullname": object_info.get("fullname", designation),
        "kind": object_info.get("kind"),
        "eccentricity": elems.get("e"),
        "semi_major_axis_au": elems.get("a"),
        "perihelion_distance_au": elems.get("q"),
        "inclination_deg": elems.get("i"),
        "ascending_node_deg": elems.get("om"),
        "arg_perihelion_deg": elems.get("w"),
        "is_hyperbolic": (elems.get("e", 0.0) > 1.0),
    }


def query_most_moving_object(designation: str) -> list[dict]:
    """Query MOST for SPHEREx coverage of a solar system object.
    Uses bare catalog=spherex and reads imgframes_matched_final_table.tbl
    from the returned workspace URL (docs/service-findings.md §7).
    """
    # 1. Submit query
    data = fetcher.safe_fetch(
        config.IRSA_MOST,
        params={
            "catalog": "spherex",
            "input_type": "name_input",
            "obj_name": designation,
            "output_mode": "Regular",
        },
        timeout=config.MOST_TIMEOUT,
        use_breaker=True,
    )
    text = data.decode("utf-8", "replace")
    ws_match = re.search(r"https://irsa\.ipac\.caltech\.edu/workspace/[^/]+/MOST/pid[0-9]+", text)
    if not ws_match:
        raise ValueError(f"MOST found no matches or workspace for '{designation}'")

    ws_url = ws_match.group(0)
    matched_table_url = f"{ws_url}/imgframes_matched_final_table.tbl"

    # 2. Fetch matched final table
    tbl_bytes = fetcher.safe_fetch(matched_table_url, timeout=config.MOST_TIMEOUT)
    tbl_text = tbl_bytes.decode("utf-8", "replace")

    rows = []
    col_names = []
    for line in tbl_text.splitlines():
        if line.startswith("\\"):
            continue
        if line.startswith("|"):
            if not col_names:
                col_names = [c.strip() for c in line.split("|") if c.strip()]
            continue
        parts = [p.strip() for p in line.split() if p.strip()]
        if len(parts) >= len(col_names) and col_names:
            row = dict(zip(col_names, parts))
            rows.append({
                "obs_id": row.get("observationid"),
                "detector": row.get("productid"),
                "mjd": float(row["mjd_start"]) if row.get("mjd_start") else None,
                "ra_predicted": float(row["ra_obj"]) if row.get("ra_obj") else None,
                "dec_predicted": float(row["dec_obj"]) if row.get("dec_obj") else None,
                "vmag": float(row["vmag"]) if row.get("vmag") else None,
                "geo_dist_au": float(row["geo_dist"]) if row.get("geo_dist") else None,
                "sun_dist_au": float(row["sun_dist"]) if row.get("sun_dist") else None,
            })
    return rows

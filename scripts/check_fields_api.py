#!/usr/bin/env python3
"""Check the field flow of a running API: ids, saving, editing one crop area, sprays one by one, isolation.

    python scripts/check_fields_api.py --base https://34-118-11-71.nip.io

Needs only HTTP. It works on throwaway sandboxes (POST /sandbox, deleted at the end) and touches nothing else. The data is a copy of a
ready farm (mode mock), so the server must have mock farmers with parcels. Checks:

1. a crop area that runs along the boundary of its parcel keeps its number of vertices through repeated saves (it used to grow with
   every save: 25, 36, 39, 46, 50, 56);
2. the id of GET /fields works in every /crop-areas/{id}/... endpoint (it used to give 404);
3. sprays one by one: list, add, change, delete, with stable ids, also through PUT /fields/{id};
4. PATCH /crop-areas/{id}: sowing date, crop, growth stage (bbch_override), the answer about sprays, and its refusals;
5. another visitor sees nothing of it (404).

Exit code 1 when a check fails.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

import httpx

OK = True


def check(name: str, cond, extra: str = "") -> None:
    global OK
    OK &= bool(cond)
    print(("  OK   " if cond else "  FAIL ") + name + (f"  [{extra}]" if extra else ""))


def vertices(geometry: dict) -> int:
    polys = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    return sum(len(ring) for poly in polys for ring in poly)


class Api:
    def __init__(self, base: str):
        self.b = base.rstrip("/") + "/api/v1"
        self.c = httpx.Client(timeout=120)
        self.h: dict = {}

    def sandbox(self, mode: str = "mock") -> dict:
        r = self.c.post(self.b + "/sandbox", json={"mode": mode})
        r.raise_for_status()
        self.h = {"Authorization": "Bearer " + r.json()["token"]}
        return r.json()

    def req(self, method: str, path: str, **kw) -> httpx.Response:
        return self.c.request(method, self.b + path, headers=self.h, **kw)

    def fields(self) -> list[dict]:
        return self.req("GET", "/fields").json()["fields"]

    def save(self, field: dict, areas: list[dict], extra_confirmations: bool = True) -> httpx.Response:
        """Validate and save a field with the given crop areas ({crop_area_id, geometry, crop, sowing_date, past_sprays})."""
        v = self.req("POST", "/fields/validate", json={"parcel_ids": field["parcel_ids"], "crop_areas": [
            {"crop_area_id": a["crop_area_id"], "geometry": a["geometry"]} for a in areas]}).json()
        need = ([f"gap:{x['gap_id']}" for x in v["gaps"]] + [f"outside:{x['outside_id']}" for x in v["outside"]] +
                [f"repair:{a['repair']['repair_id']}" for a in v["crop_areas"]
                 if a["repair"] and a["repair"]["performed"] and a["repair"]["requires_review"]])
        return self.req("PUT", f"/fields/{field['field_id']}", json={
            "field_id": field["field_id"], "name": field.get("name"), "parcel_ids": field["parcel_ids"],
            "validation_id": v["validation_id"], "confirmations": need if extra_confirmations else [], "crop_areas": areas})


def area_body(a: dict) -> dict:
    return {"crop_area_id": a["crop_area_id"], "geometry": a["geometry"], "crop": {"farmer_crop_id": a["crop"]["farmer_crop_id"]},
            "sowing_date": a["sowing_date"], "past_sprays": a["past_sprays"] if a["past_sprays"] is not None else []}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="e.g. https://34-118-11-71.nip.io (without /api/v1)")
    a = ap.parse_args(argv)
    api, other = Api(a.base), Api(a.base)
    api.sandbox()
    other.sandbox("empty")
    today = date.fromisoformat(api.req("GET", "/clock").json()["today"])
    fields = [f for f in api.fields() if f["parcel_ids"] and f["crop_areas"]]
    check("the copy of a ready farm has fields with parcels and crop areas", len(fields) >= 2, f"{len(fields)} fields")
    f0 = fields[0]
    a0 = f0["crop_areas"][0]
    cid = a0["crop_area_id"]

    print("\n== 1. a crop area along the boundary of its parcel keeps its vertices")
    parcel = f0["parcels"][0]
    edge = {"field_id": "edge-check", "name": "edge", "parcel_ids": [parcel["parcel_id"]]}
    body = {"crop_area_id": "edge-area", "geometry": parcel["geometry"], "crop": {"farmer_crop_id": "wheat"},
            "sowing_date": str(today - timedelta(days=30)), "past_sprays": []}
    counts = []
    for _ in range(5):
        r = api.save(edge, [body])
        if r.status_code != 200:
            check("save of a crop area equal to its parcel", False, f"{r.status_code} {r.text[:120]}")
            break
        saved = next(x for x in api.fields() if x["field_id"] == "edge-check")["crop_areas"][0]["geometry"]
        counts.append(vertices(saved))
        body = dict(body, geometry=saved)
    check("the number of vertices does not grow over 5 saves", len(counts) == 5 and len(set(counts)) == 1,
          f"input {vertices(parcel['geometry'])} -> {counts}")

    print("\n== 2. the id of GET /fields works everywhere")
    for method, path, ok in (("GET", f"/crop-areas/{cid}", {200}), ("GET", f"/crop-areas/{cid}/risk", {200}),
                             ("GET", f"/crop-areas/{cid}/changes", {200}), ("GET", f"/crop-areas/{cid}/sprays", {200})):
        r = api.req(method, path)
        check(f"{method} /crop-areas/{{id of /fields}}{path.split(cid)[1]}", r.status_code in ok, str(r.status_code))
    check("the risk has the index", all("risk_index" in d for d in api.req("GET", f"/crop-areas/{cid}/risk").json()))

    print("\n== 3. sprays one by one")
    d1, d2 = str(today - timedelta(days=12)), str(today - timedelta(days=5))
    r = api.req("POST", f"/crop-areas/{cid}/sprays", json={"spray_date": d1, "protection_duration_days": 10})
    sid = (r.json().get("spray") or {}).get("spray_id")
    check("POST a spray answers 201 with its spray_id", r.status_code == 201 and sid, f"{r.status_code} id {sid}")
    sprays = api.req("GET", f"/crop-areas/{cid}/sprays").json()
    check("the list has it, with the answer about sprays confirmed", sprays["sprays_confirmed"] and any(s["spray_id"] == sid for s in sprays["sprays"]))
    r = api.req("PATCH", f"/crop-areas/{cid}/sprays/{sid}", json={"date": d2, "protection_duration_days": 14})
    mine = next((s for s in r.json().get("past_sprays", []) if s["spray_id"] == sid), None)
    check("PATCH changes the date and the duration, keeps the id", r.status_code == 200 and mine and mine["date"] == d2 and mine["protection_duration_days"] == 14,
          f"{r.status_code}")
    r = api.req("PATCH", f"/crop-areas/{cid}/sprays/{sid}", json={"protection_duration_days": 7})
    check("PATCH of one field keeps the other", r.status_code == 200 and next(s for s in r.json()["past_sprays"] if s["spray_id"] == sid)["date"] == d2)
    check("PATCH of a future date or a bad duration is 422", api.req("PATCH", f"/crop-areas/{cid}/sprays/{sid}", json={"date": str(today + timedelta(days=3))}).status_code == 422
          and api.req("PATCH", f"/crop-areas/{cid}/sprays/{sid}", json={"protection_duration_days": 0}).status_code == 422)
    f1 = next(x for x in api.fields() if x["field_id"] == f0["field_id"])
    ids_before = [s["spray_id"] for s in f1["crop_areas"][0]["past_sprays"]]
    check("GET /fields shows the sprays with ids", sid in ids_before, str(ids_before))
    r = api.save(f1, [area_body(x) for x in f1["crop_areas"]])
    f2 = next(x for x in api.fields() if x["field_id"] == f0["field_id"])
    check("PUT of the same representation keeps the ids of the sprays", r.status_code == 200 and [s["spray_id"] for s in f2["crop_areas"][0]["past_sprays"]] == ids_before,
          f"{r.status_code}")
    r = api.req("DELETE", f"/crop-areas/{cid}/sprays/{sid}")
    check("DELETE answers 200 with the remaining sprays", r.status_code == 200 and all(s["spray_id"] != sid for s in r.json()["past_sprays"]), str(r.status_code))
    check("DELETE of the same spray again is 404", api.req("DELETE", f"/crop-areas/{cid}/sprays/{sid}").status_code == 404)
    if len(fields[1]["crop_areas"]) >= 1:
        b_cid = fields[1]["crop_areas"][0]["crop_area_id"]
        r = api.req("POST", f"/crop-areas/{b_cid}/sprays", json={"spray_date": d1, "protection_duration_days": 10})
        bs = r.json()["spray"]["spray_id"]
        check("a spray of another crop area cannot be reached through this one", api.req("PATCH", f"/crop-areas/{cid}/sprays/{bs}", json={"protection_duration_days": 5}).status_code == 404)
        api.req("DELETE", f"/crop-areas/{b_cid}/sprays/{bs}")

    print("\n== 4. PATCH /crop-areas/{id}")
    new_sowing = str(today - timedelta(days=40))
    r = api.req("PATCH", f"/crop-areas/{cid}", json={"sowing_date": new_sowing, "farmer_crop_id": "maize"})
    check("sowing date and crop change, the shape is that of crop_areas", r.status_code == 200 and r.json()["sowing_date"] == new_sowing and r.json()["crop"]["farmer_crop_id"] == "maize"
          and r.json()["crop_area_id"] == cid, str(r.status_code))
    r = api.req("PATCH", f"/crop-areas/{cid}", json={"farmer_crop_id": "wheat", "bbch_override": 37})
    check("the growth stage can be set by the farmer", r.status_code == 200, str(r.status_code))
    src = {d["growth_stage_source"] for d in api.req("GET", f"/crop-areas/{cid}/risk").json() if d["risk_class"]}
    check("the risk then uses the farmer's stage", src == {"override"}, str(src))
    api.req("PATCH", f"/crop-areas/{cid}", json={"bbch_override": None})
    src = {d["growth_stage_source"] for d in api.req("GET", f"/crop-areas/{cid}/risk").json() if d["risk_class"]}
    check("null clears it", "override" not in src, str(src))
    check("an empty body, a future sowing date, an unknown crop, a wrong stage and sprays_confirmed=false are 422",
          all(api.req("PATCH", f"/crop-areas/{cid}", json=b).status_code == 422 for b in
              ({}, {"sowing_date": str(today + timedelta(days=2))}, {"farmer_crop_id": "banana"}, {"bbch_override": 40}, {"sprays_confirmed": False})))
    r = api.req("PATCH", f"/crop-areas/{cid}", json={"sprays_confirmed": True})
    check("sprays_confirmed=true is accepted", r.status_code == 200 and r.json()["past_sprays"] is not None)

    print("\n== 5. another visitor sees nothing of it")
    for method, path, body in (("GET", f"/crop-areas/{cid}", None), ("PATCH", f"/crop-areas/{cid}", {"bbch_override": 37}),
                               ("GET", f"/crop-areas/{cid}/sprays", None), ("DELETE", f"/crop-areas/{cid}", None)):
        r = other.req(method, path, **({"json": body} if body else {}))
        check(f"{method} {path.split(cid)[0]}{{id}}{path.split(cid)[1]} of somebody else's crop area is 404", r.status_code == 404, str(r.status_code))
    check("the first visitor still has the crop area", api.req("GET", f"/crop-areas/{cid}").status_code == 200)

    api.req("DELETE", "/sandbox")
    other.req("DELETE", "/sandbox")
    print("\nRESULT:", "OK" if OK else "FAILED")
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())

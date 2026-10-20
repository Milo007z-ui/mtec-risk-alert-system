import os
import json, urllib.request, urllib.parse, pandas as pd
B = "https://onemap-layers.doh.go.th/geoserver/wfs?"
def q(layer, cql, props):
    p = {"service":"WFS","version":"2.0.0","request":"GetFeature","typeNames":"dohonemap:"+layer,"outputFormat":"application/json","CQL_FILTER":cql,"propertyName":props}
    data = urllib.parse.urlencode(p).encode()
    return [f["properties"] for f in json.load(urllib.request.urlopen(urllib.request.Request(B, data=data), timeout=180))["features"]]
S = pd.read_csv("doh_sections.csv")
cql = " OR ".join(f"(highway_code='{h:04d}' AND road_code='{c:04d}')" for h, c in zip(S.h, S.c))
line = q("hgds_aadt_line_2567", cql, "highway_code,road_code,road_name,km_start,km_end,station_id,station_type,vehcat_aadt_all,traffic_year")
print("line rows", len(line))
st = sorted({x["station_id"] for x in line if x["station_id"] is not None})
props = "highway_code,road_code,road_name,km,station_id,station_type,vehcat_aadt_all,traffic_year,latitude,longitude"
p67 = q("hgds_aadt_pnt_2567", f"station_id IN ({','.join(map(str, st))})", props)
p68 = q("hgds_aadt_pnt_2568", f"station_id IN ({','.join(map(str, st))})", props)
print("stations", len(st), "pnt67", len(p67), "pnt68", len(p68))
json.dump({"line": line, "p67": p67, "p68": p68}, open("doh70.json", "w", encoding="utf-8"), ensure_ascii=False)

import os
import json, urllib.request, urllib.parse
S=[(7,101),(3902,101),(31,101),(9,101),(302,100),(341,100),(350,100),(3651,100),(3,103),(304,202),(3902,300),(31,102),(3901,101),(3256,101)]
B="https://onemap-layers.doh.go.th/geoserver/wfs?"
def q(layer, cql, props=None):
    p={"service":"WFS","version":"2.0.0","request":"GetFeature","typeNames":"dohonemap:"+layer,"outputFormat":"application/json","CQL_FILTER":cql}
    if props: p["propertyName"]=props
    u=B+urllib.parse.urlencode(p); return [f["properties"] for f in json.load(urllib.request.urlopen(u,timeout=120))["features"]], u
out={}
for h,c in S:
    cql=f"highway_code='{h:04d}' AND road_code='{c:04d}'"
    r={}
    for L in ("hgds_aadt_line_2565","hgds_aadt_line_2567","hgds_aadt_line_2568"):
        f,u=q(L,cql); r[L]=[{k:x.get(k) for k in ("road_name","km_start","km_end","station_id","station_type","vehcat_aadt_all","traffic_year")} for x in f]
    out[f"{h}-{c}"]=r
    print(h,c,{L:[(x["km_start"],x["km_end"],x["station_id"],x["station_type"],x["vehcat_aadt_all"]) for x in v] for L,v in r.items()})
json.dump(out,open("q14.json","w",encoding="utf-8"),ensure_ascii=False)

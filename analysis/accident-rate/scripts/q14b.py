import os
import json, urllib.request, urllib.parse
B="https://onemap-layers.doh.go.th/geoserver/wfs?"
def q(layer, cql):
    p={"service":"WFS","version":"2.0.0","request":"GetFeature","typeNames":"dohonemap:"+layer,"outputFormat":"application/json","CQL_FILTER":cql,
       "propertyName":"highway_code,road_code,road_name,km,station_id,station_type,vehcat_aadt_all,traffic_year,latitude,longitude"}
    return [f["properties"] for f in json.load(urllib.request.urlopen(B+urllib.parse.urlencode(p),timeout=120))["features"]]
st=[345,130,104,123,125,8,61,137,2,80,131,98]
res={}
for L in ("hgds_aadt_pnt_2565","hgds_aadt_pnt_2567","hgds_aadt_pnt_2568"):
    try: f=q(L,"station_id IN (%s)"%",".join(map(str,st)))
    except Exception as e: print(L,"ERR",e); continue
    res[L]=f
    print("==",L,len(f))
    for x in sorted(f,key=lambda x:x["station_id"]): print(x)
json.dump(res,open("q14b.json","w",encoding="utf-8"),ensure_ascii=False)

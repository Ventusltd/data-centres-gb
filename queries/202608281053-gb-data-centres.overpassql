[out:json][timeout:90][maxsize:67108864];
area["ISO3166-1"="GB"]["admin_level"="2"]["boundary"="administrative"]->.gb;
(
  nwr(area.gb)["telecom"~"^data_cent(er|re)$"];
  nwr(area.gb)["building"~"^data_cent(er|re)$"];
  nwr(area.gb)["industrial"~"^data_cent(er|re)$"];
  nwr(area.gb)[~"^(proposed|planned|construction|disused|abandoned|demolished):telecom$"~"^data_cent(er|re)$"];
  nwr(area.gb)[~"^(proposed|planned|construction|disused|abandoned|demolished):building$"~"^data_cent(er|re)$"];
  nwr(area.gb)[~"^(proposed|planned|construction|disused|abandoned|demolished):industrial$"~"^data_cent(er|re)$"];
);
out meta geom qt;

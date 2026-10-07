# Pittsburgh neighborhood boundaries

`pittsburgh-neighborhoods.geojson` is a bundled snapshot of the City of Pittsburgh GIS Neighborhoods layer, retrieved October 6, 2026. It contains 90 named neighborhoods in WGS84 longitude/latitude coordinates. The app matches locally; it sends no business coordinates to an external service.

Source: https://pghbridgis.pittsburghpa.gov/federated/rest/services/Neighborhoods/FeatureServer/0

Download query: `/query?where=1%3D1&outFields=hood&outSR=4326&returnGeometry=true&f=geojson` on that layer.

Mapped points are matched by polygon containment. OSM ways/relations use their approximate bounding-box centers, so the match can be approximate near a neighborhood boundary. Shared-boundary matches and unmatched/missing coordinates remain unknown. Neighborhoods follow the city's layer names rather than ZIP codes or informal area names. Boundary updates require replacing this bundled snapshot.

import cadquery as cq

tread = 15
rise = 10
width = 40

profile = [
    (0, 0),
    (3 * tread, 0),
    (3 * tread, 3 * rise),
    (2 * tread, 3 * rise),
    (2 * tread, 2 * rise),
    (tread, 2 * rise),
    (tread, rise),
    (0, rise),
]
result = cq.Workplane("XZ").polyline(profile).close().extrude(width)

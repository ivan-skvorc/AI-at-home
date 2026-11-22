import cadquery as cq

outside = 40
width = 12
groove_depth = 5
bore = 6

rim = outside / 2
root = rim - groove_depth
# A 90 degree groove is as wide at the rim as it is twice deep.
half_opening = groove_depth
mid = width / 2

# The cross-section in the XZ plane, radius along x and height along z, turned about the z axis.
profile = [
    (bore / 2, 0),
    (rim, 0),
    (rim, mid - half_opening),
    (root, mid),
    (rim, mid + half_opening),
    (rim, width),
    (bore / 2, width),
]
result = cq.Workplane("XZ").polyline(profile).close().revolve(360, (0, 0, 0), (0, 1, 0))

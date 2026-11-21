import cadquery as cq

across_flats = 17
height = 25
# polygon() takes the diameter through the corners.
across_corners = across_flats * 2 / 3**0.5

result = cq.Workplane("XY").polygon(6, across_corners).extrude(height)

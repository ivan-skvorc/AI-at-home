import cadquery as cq

length = 50
width = 20
thickness = 3
ring_hole = 4
ring_inset = 5
letters = 10
depth = 0.6

tag = cq.Workplane("XY").box(length, width, thickness)
tag = tag.faces(">Z").workplane().center(-length / 2 + ring_inset, 0).hole(ring_hole)
# The lettering is centred on the part of the tag the ring hole leaves free.
result = tag.faces(">Z").workplane().center(ring_inset, 0).text("DEER", letters, -depth)

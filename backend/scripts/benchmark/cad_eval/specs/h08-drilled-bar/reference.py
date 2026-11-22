import cadquery as cq

length = 80
width = 20
thickness = 8
hole_d = 5
first_hole = 15
second_hole = 35
side_d = 3
side_depth = 12

# Centred on the origin: the two holes are placed from the -x end, and the side hole goes into the +x end.
# Each workplane is centred on its own face, so neither depends on where the one before it was.
bar = cq.Workplane("XY").box(length, width, thickness)
drilled = bar.faces(">Z").workplane(centerOption="CenterOfBoundBox").pushPoints([(first_hole - length / 2, 0), (second_hole - length / 2, 0)]).hole(hole_d)
result = drilled.faces(">X").workplane(centerOption="CenterOfBoundBox").hole(side_d, side_depth)

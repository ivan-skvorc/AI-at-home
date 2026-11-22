import cadquery as cq

length = 80
width = 40
height = 20
wall = 3

outer = cq.Workplane("XY").box(length, width, height, centered=(True, True, False))
# Longer than the channel, so the cut leaves no sliver at the open ends.
channel = cq.Workplane("XY").box(length + 2, width - 2 * wall, height, centered=(True, True, False)).translate((0, 0, wall))
result = outer.cut(channel)

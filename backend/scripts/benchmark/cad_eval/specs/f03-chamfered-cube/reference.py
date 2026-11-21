import cadquery as cq

side = 30
bevel = 2

result = cq.Workplane("XY").box(side, side, side).edges().chamfer(bevel)

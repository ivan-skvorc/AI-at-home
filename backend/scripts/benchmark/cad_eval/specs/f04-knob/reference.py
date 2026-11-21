import cadquery as cq

diameter = 30
height = 15
round_over = 3
shaft = 6
shaft_depth = 10

result = cq.Workplane("XY").cylinder(height, diameter / 2).faces(">Z").edges().fillet(round_over).faces("<Z").workplane().hole(shaft, shaft_depth)

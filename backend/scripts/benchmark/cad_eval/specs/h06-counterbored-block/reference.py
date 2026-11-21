import cadquery as cq

side = 40
height = 20
drill = 6.6
cbore = 11
cbore_depth = 6.5

result = cq.Workplane("XY").box(side, side, height).faces(">Z").workplane().cboreHole(drill, cbore, cbore_depth)

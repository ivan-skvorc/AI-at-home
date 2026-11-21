import cadquery as cq

length = 100
width = 60
thickness = 10
pocket_length = 60
pocket_width = 30
pocket_depth = 6

result = cq.Workplane("XY").box(length, width, thickness).faces(">Z").workplane().rect(pocket_length, pocket_width).cutBlind(-pocket_depth)

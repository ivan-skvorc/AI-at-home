import cadquery as cq

length = 50
width = 30
thickness = 12

result = cq.Workplane("XY").box(length, width, thickness)

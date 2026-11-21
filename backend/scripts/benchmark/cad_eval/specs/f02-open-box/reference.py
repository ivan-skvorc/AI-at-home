import cadquery as cq

length = 60
width = 40
height = 30
wall = 2

result = cq.Workplane("XY").box(length, width, height).faces(">Z").shell(-wall)

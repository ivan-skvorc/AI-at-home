import cadquery as cq

length = 100
width = 20
thickness = 4
pitch = 40
clearance = 4.5
head = 9

result = cq.Workplane("XY").box(length, width, thickness).faces(">Z").workplane().pushPoints([(-pitch, 0), (0, 0), (pitch, 0)]).cskHole(clearance, head, 90)

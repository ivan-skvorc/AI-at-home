import cadquery as cq

length = 80
width = 50
thickness = 5
hole_d = 5
inset = 10

result = cq.Workplane("XY").box(length, width, thickness).faces(">Z").workplane().rarray(length - 2 * inset, width - 2 * inset, 2, 2).hole(hole_d)

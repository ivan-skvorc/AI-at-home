import cadquery as cq

length = 60
width = 40
thickness = 6
corner = 8
hole_d = 4
hole_spacing = 30

result = cq.Workplane("XY").box(length, width, thickness).edges("|Z").fillet(corner).faces(">Z").workplane().pushPoints([(-hole_spacing / 2, 0), (hole_spacing / 2, 0)]).hole(hole_d)

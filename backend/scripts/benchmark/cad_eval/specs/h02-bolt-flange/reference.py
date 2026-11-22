import cadquery as cq

diameter = 80
thickness = 8
bore = 30
bolt_hole = 6.5
bolt_circle = 60
bolts = 6

result = cq.Workplane("XY").cylinder(thickness, diameter / 2).faces(">Z").workplane().hole(bore).faces(">Z").workplane().polarArray(bolt_circle / 2, 0, 360, bolts).hole(bolt_hole)

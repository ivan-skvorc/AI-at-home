import cadquery as cq

length = 40
leaf = 25
plate = 3
knuckle_d = 8
pin_d = 4
outer = 13
gap = 0.4

radius = knuckle_d / 2
middle = length - 2 * outer - 2 * gap
bore_d = pin_d + 2 * gap
# Each leaf's plate stops short of the other leaf's knuckle by the clearance.
clear = radius + gap

# The first leaf: a plate, the two outer knuckles joined to it, and the pin through all three.
plate_a = cq.Workplane("XY").box(length, leaf - clear, plate, centered=False).translate((0, -leaf, 0))
web_a = cq.Workplane("XY").box(outer, clear, plate, centered=False).translate((0, -clear, 0))
web_a2 = web_a.translate((length - outer, 0, 0))
knuckle_a = cq.Workplane("YZ").cylinder(outer, radius, centered=(True, True, False)).translate((0, 0, radius))
knuckle_a2 = knuckle_a.translate((length - outer, 0, 0))
pin = cq.Workplane("YZ").cylinder(length, pin_d / 2, centered=(True, True, False)).translate((0, 0, radius))
first = plate_a.union(web_a).union(web_a2).union(knuckle_a).union(knuckle_a2).union(pin)

# The second leaf: a plate and the middle knuckle, bored clear of the pin.
plate_b = cq.Workplane("XY").box(length, leaf - clear, plate, centered=False).translate((0, clear, 0))
web_b = cq.Workplane("XY").box(middle, clear, plate, centered=False).translate((outer + gap, 0, 0))
knuckle_b = cq.Workplane("YZ").cylinder(middle, radius, centered=(True, True, False)).translate((outer + gap, 0, radius))
bore = cq.Workplane("YZ").cylinder(middle, bore_d / 2, centered=(True, True, False)).translate((outer + gap, 0, radius))
second = plate_b.union(web_b).union(knuckle_b).cut(bore)

# Two bodies that touch nowhere, so the hinge prints in place and turns.
result = first.union(second)

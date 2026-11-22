import cadquery as cq

length = 60
width = 40
height = 25
wall = 2
lid_thickness = 2
lip_depth = 4
lip_wall = 1.5
clearance = 0.3
spacing = 10

box = cq.Workplane("XY").box(length, width, height, centered=(False, False, False)).faces(">Z").shell(-wall)

lip_length = length - 2 * wall - 2 * clearance
lip_width = width - 2 * wall - 2 * clearance
plate = cq.Workplane("XY").box(length, width, lid_thickness, centered=(False, False, False))
lip = cq.Workplane("XY").box(lip_length, lip_width, lip_depth, centered=(True, True, False)).translate((length / 2, width / 2, lid_thickness))
# Taller than the lip, so the cut leaves no skin at either end of the rim.
inside = cq.Workplane("XY").box(lip_length - 2 * lip_wall, lip_width - 2 * lip_wall, lip_depth + 2, centered=(True, True, False)).translate((length / 2, width / 2, lid_thickness - 1))
lid = plate.union(lip.cut(inside)).translate((length + spacing, 0, 0))

# Laid out for printing: the lid upside down beside the box, two bodies.
result = box.union(lid)

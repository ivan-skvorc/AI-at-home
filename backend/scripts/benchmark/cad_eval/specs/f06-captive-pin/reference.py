import cadquery as cq

block_x = 30
block_y = 20
block_z = 20
bore = 8.6
pin = 8
head = 12
head_thickness = 2
gap = 0.4

block = cq.Workplane("XY").box(block_x, block_y, block_z).faces(">Y").workplane().hole(bore)
shaft = cq.Workplane("XZ").cylinder(block_y + 2 * gap, pin / 2)
head_offset = (block_y + head_thickness) / 2 + gap
near = cq.Workplane("XZ").cylinder(head_thickness, head / 2).translate((0, head_offset, 0))
far = cq.Workplane("XZ").cylinder(head_thickness, head / 2).translate((0, -head_offset, 0))
# The pin is a second body: it touches the block nowhere, so it prints in place and turns.
result = block.union(shaft.union(near).union(far))

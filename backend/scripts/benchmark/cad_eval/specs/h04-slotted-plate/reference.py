import cadquery as cq

length = 70
width = 30
thickness = 4
slot_length = 20
slot_width = 6
slot_spacing = 35

result = cq.Workplane("XY").box(length, width, thickness).faces(">Z").workplane().pushPoints([(-slot_spacing / 2, 0), (slot_spacing / 2, 0)]).slot2D(slot_length, slot_width).cutThruAll()

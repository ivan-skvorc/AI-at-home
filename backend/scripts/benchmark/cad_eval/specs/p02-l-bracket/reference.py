import cadquery as cq

width = 60
depth = 30
thickness = 5
height = 40

base = cq.Workplane("XY").box(width, depth, thickness, centered=(True, True, False))
wall = cq.Workplane("XY").box(width, thickness, height, centered=(True, True, False)).translate((0, (depth - thickness) / 2, 0))
result = base.union(wall)

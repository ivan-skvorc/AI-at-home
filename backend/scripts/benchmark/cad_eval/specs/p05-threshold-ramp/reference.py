import cadquery as cq

length = 60
width = 30
rise = 20

result = cq.Workplane("XZ").polyline([(0, 0), (length, 0), (length, rise)]).close().extrude(width)

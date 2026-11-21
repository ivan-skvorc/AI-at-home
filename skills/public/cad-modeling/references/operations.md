# Operations a script may use

Generated from the CAD module's allow-list. Do not edit: change the table and regenerate.

A part starts with `cq.Workplane(...)` and is shaped by the methods below, each called on a part.
Arguments are in CadQuery's order and may be given by name; one in `[brackets]` is optional.
Any other method, and anything else on `cq`, is refused.

- Plane names: `XY`, `YZ`, `ZX`, `XZ`, `YX`, `ZY`, `front`, `back`, `left`, `right`, `top`, `bottom`.
- Selector strings: CadQuery's own, such as `">Z"`, `"<X"`, `"|Z"`, `"#Z"`, `"%CIRCLE"`, `"|Z and >Y"`.
- Sizes and coordinates: at most 100000 mm; a length is at least 0.0001 mm.
- Patterns (`pushPoints`, `rarray`, `polarArray`): at most 100 points in one call and 200 in a script.
- Numbers: `import math` gives `math.pi`, `math.tau` and `math.sin()`, `math.cos()`, `math.tan()`, `math.asin()`, `math.acos()`, `math.atan()`, `math.atan2()`, `math.sqrt()`, `math.hypot()`, `math.radians()`, `math.degrees()`, `math.floor()`, `math.ceil()`.
  `abs()`, `min()`, `max()`, `round()`, `int()`, `float()`, `len()` take numbers or a list of them. An index such as `p[0]` is a whole number.

## cq.Workplane([inPlane], [origin])

Start a part on a named plane.

- `inPlane`: a plane name
- `origin`: a point, (x, y) or (x, y, z)

```python
result = cq.Workplane("XY").box(10, 10, 10)
```

## box(length, width, height, [centered], [combine], [clean])

A box, centred on the workplane origin unless centered says otherwise.

- `length`, `width`, `height`: millimetres, above 0
- `centered`: True, False, or one of them per axis: (True, True, False)
- `combine`, `clean`: True or False

```python
result = cq.Workplane("XY").box(60, 40, 6)
```

## cylinder(height, radius, [direct], [angle], [centered], [combine], [clean])

A cylinder along the workplane normal.

- `height`, `radius`: millimetres, above 0
- `direct`: a point, (x, y) or (x, y, z)
- `angle`: degrees
- `centered`: True, False, or one of them per axis: (True, True, False)
- `combine`, `clean`: True or False

```python
result = cq.Workplane("XY").cylinder(20, 5)
```

## sphere(radius)

A sphere.

- `radius`: millimetres, above 0

```python
result = cq.Workplane("XY").sphere(10)
```

## rect(xLen, yLen, [centered], [forConstruction])

A rectangle on the workplane, one per point on the stack.

- `xLen`, `yLen`: millimetres, above 0
- `centered`: True, False, or one of them per axis: (True, False)
- `forConstruction`: True or False

```python
result = cq.Workplane("XY").rect(30, 20).extrude(5)
```

## circle(radius, [forConstruction])

A circle on the workplane, one per point on the stack.

- `radius`: millimetres, above 0
- `forConstruction`: True or False

```python
result = cq.Workplane("XY").circle(10).extrude(5)
```

## ellipse(x_radius, y_radius, [rotation_angle], [forConstruction])

An ellipse on the workplane.

- `x_radius`, `y_radius`: millimetres, above 0
- `rotation_angle`: degrees
- `forConstruction`: True or False

```python
result = cq.Workplane("XY").ellipse(20, 10).extrude(5)
```

## polygon(nSides, diameter, [forConstruction], [circumscribed])

A regular polygon.

- `nSides`: a whole number, 3 to 100
- `diameter`: millimetres, above 0
- `forConstruction`, `circumscribed`: True or False

```python
result = cq.Workplane("XY").polygon(6, 20).extrude(5)
```

## slot2D(length, diameter, [angle])

A slot with rounded ends.

- `length`, `diameter`: millimetres, above 0
- `angle`: degrees

```python
result = cq.Workplane("XY").box(60, 40, 6).faces('>Z').workplane().slot2D(20, 6).cutThruAll()
```

## polyline(listOfXYTuple, [forConstruction], [includeCurrent])

Straight segments through the given points; close() finishes the outline.

- `listOfXYTuple`: a list of points
- `forConstruction`, `includeCurrent`: True or False

```python
result = cq.Workplane("XY").polyline([(0, 0), (40, 0), (40, 10), (10, 10), (10, 30), (0, 30)]).close().extrude(20)
```

## moveTo([x], [y])

Move the pen to a point without drawing.

- `x`, `y`: a number

```python
result = cq.Workplane("XY").moveTo(10, 0).lineTo(20, 0).lineTo(20, 10).close().extrude(5)
```

## move([xDist], [yDist])

Move the pen by a distance without drawing.

- `xDist`, `yDist`: a number

```python
result = cq.Workplane("XY").move(10, 0).circle(3).extrude(5)
```

## lineTo(x, y, [forConstruction])

A line to a point.

- `x`, `y`: a number
- `forConstruction`: True or False

```python
result = cq.Workplane("XY").lineTo(30, 0).lineTo(30, 20).close().extrude(5)
```

## line(xDist, yDist, [forConstruction])

A line by a distance.

- `xDist`, `yDist`: a number
- `forConstruction`: True or False

```python
result = cq.Workplane("XY").line(30, 0).line(0, 20).close().extrude(5)
```

## hLine(distance, [forConstruction])

A horizontal line by a distance.

- `distance`: a number
- `forConstruction`: True or False

```python
result = cq.Workplane("XY").hLine(30).vLine(20).close().extrude(5)
```

## vLine(distance, [forConstruction])

A vertical line by a distance.

- `distance`: a number
- `forConstruction`: True or False

```python
result = cq.Workplane("XY").hLine(30).vLine(20).close().extrude(5)
```

## hLineTo(xCoord, [forConstruction])

A horizontal line to an x coordinate.

- `xCoord`: a number
- `forConstruction`: True or False

```python
result = cq.Workplane("XY").hLineTo(30).vLineTo(20).close().extrude(5)
```

## vLineTo(yCoord, [forConstruction])

A vertical line to a y coordinate.

- `yCoord`: a number
- `forConstruction`: True or False

```python
result = cq.Workplane("XY").hLineTo(30).vLineTo(20).close().extrude(5)
```

## threePointArc(point1, point2, [forConstruction])

An arc through a point to an end point.

- `point1`, `point2`: a point, (x, y) or (x, y, z)
- `forConstruction`: True or False

```python
result = cq.Workplane("XY").lineTo(20, 0).threePointArc((25, 5), (20, 10)).lineTo(0, 10).close().extrude(5)
```

## close()

Close the outline back to its start.

```python
result = cq.Workplane("XY").lineTo(30, 0).lineTo(30, 20).close().extrude(5)
```

## center(x, y)

Shift the workplane origin.

- `x`, `y`: a number

```python
result = cq.Workplane("XY").box(60, 40, 6).faces('>Z').workplane().center(10, 0).hole(4)
```

## extrude(until, [combine], [clean], [both], [taper])

Extrude the outline by a distance.

- `until`: a number
- `combine`, `clean`, `both`: True or False
- `taper`: degrees, or None

```python
result = cq.Workplane("XY").rect(30, 20).extrude(5)
```

## cutBlind(until, [clean], [both], [taper])

Cut the outline into the part by a distance; negative cuts into the face.

- `until`: a number
- `clean`, `both`: True or False
- `taper`: degrees, or None

```python
result = cq.Workplane("XY").box(60, 40, 6).faces('>Z').workplane().rect(20, 10).cutBlind(-3)
```

## cutThruAll([clean], [taper])

Cut the outline through the whole part.

- `clean`: True or False
- `taper`: degrees

```python
result = cq.Workplane("XY").box(60, 40, 6).faces('>Z').workplane().rect(20, 10).cutThruAll()
```

## hole(diameter, [depth], [clean])

A hole; through the part unless depth is given.

- `diameter`: millimetres, above 0
- `depth`: millimetres, above 0, or None
- `clean`: True or False

```python
result = cq.Workplane("XY").box(60, 40, 6).faces('>Z').workplane().pushPoints([(-15, 0), (15, 0)]).hole(4)
```

## cboreHole(diameter, cboreDiameter, cboreDepth, [depth], [clean])

A counterbored hole.

- `diameter`, `cboreDiameter`, `cboreDepth`: millimetres, above 0
- `depth`: millimetres, above 0, or None
- `clean`: True or False

```python
result = cq.Workplane("XY").box(60, 40, 10).faces('>Z').workplane().cboreHole(4, 8, 3)
```

## cskHole(diameter, cskDiameter, cskAngle, [depth], [clean])

A countersunk hole.

- `diameter`, `cskDiameter`: millimetres, above 0
- `cskAngle`: degrees
- `depth`: millimetres, above 0, or None
- `clean`: True or False

```python
result = cq.Workplane("XY").box(60, 40, 10).faces('>Z').workplane().cskHole(4, 8, 82)
```

## fillet(radius)

Round the selected edges.

- `radius`: millimetres, above 0

```python
result = cq.Workplane("XY").box(60, 40, 6).edges('|Z').fillet(3)
```

## chamfer(length, [length2])

Bevel the selected edges.

- `length`: millimetres, above 0
- `length2`: millimetres, above 0, or None

```python
result = cq.Workplane("XY").box(60, 40, 6).edges('>Z').chamfer(1)
```

## shell(thickness, [kind])

Hollow the part, removing the selected faces; negative thickness shells inward.

- `thickness`: a number
- `kind`: one of "arc", "intersection"

```python
result = cq.Workplane("XY").box(60, 40, 30).faces('>Z').shell(-2)
```

## pushPoints(pntList)

Put points on the stack.

- `pntList`: a list of points

```python
result = cq.Workplane("XY").box(60, 40, 6).faces('>Z').workplane().pushPoints([(-15, 0), (15, 0)]).hole(4)
```

## rarray(xSpacing, ySpacing, xCount, yCount, [center])

A rectangular grid of points.

- `xSpacing`, `ySpacing`: millimetres, above 0
- `xCount`, `yCount`: a whole number, 1 or more
- `center`: True, False, or one of them per axis: (True, False)

```python
result = cq.Workplane("XY").box(60, 40, 6).faces('>Z').workplane().rarray(20, 20, 2, 2).hole(4)
```

## polarArray(radius, startAngle, angle, count, [fill], [rotate])

Points on a circle.

- `radius`: millimetres, above 0
- `startAngle`, `angle`: degrees
- `count`: a whole number, 1 or more
- `fill`, `rotate`: True or False

```python
result = cq.Workplane("XY").cylinder(6, 30).faces('>Z').workplane().polarArray(20, 0, 360, 6).hole(4)
```

## faces([selector], [tag])

Select faces with a CadQuery selector string.

- `selector`: a selector string
- `tag`: a label of letters, digits and underscores

```python
result = cq.Workplane("XY").box(60, 40, 6).faces('>Z').workplane().hole(4)
```

## edges([selector], [tag])

Select edges with a CadQuery selector string.

- `selector`: a selector string
- `tag`: a label of letters, digits and underscores

```python
result = cq.Workplane("XY").box(60, 40, 6).edges('|Z').fillet(3)
```

## vertices([selector], [tag])

Select vertices; with workplane() or as points for holes.

- `selector`: a selector string
- `tag`: a label of letters, digits and underscores

```python
result = cq.Workplane("XY").box(60, 40, 6).faces('>Z').workplane().rect(50, 30, forConstruction=True).vertices().hole(3)
```

## workplane([offset], [invert], [centerOption], [origin])

A new workplane on the selected face.

- `offset`: a number
- `invert`: True or False
- `centerOption`: one of "CenterOfMass", "ProjectedOrigin", "CenterOfBoundBox"
- `origin`: a point, (x, y) or (x, y, z), or None

```python
result = cq.Workplane("XY").box(60, 40, 6).faces('>Z').workplane().hole(4)
```

## tag(name)

Name the current state, to return to it with workplaneFromTagged.

- `name`: a label of letters, digits and underscores

```python
result = cq.Workplane("XY").box(60, 40, 6).faces('>Z').workplane().tag('top').hole(4).workplaneFromTagged('top').center(20, 0).hole(3)
```

## workplaneFromTagged(name)

Return to a tagged workplane.

- `name`: a label of letters, digits and underscores

```python
result = cq.Workplane("XY").box(60, 40, 6).faces('>Z').workplane().tag('top').hole(4).workplaneFromTagged('top').center(20, 0).hole(3)
```

## translate(vec)

Move the part.

- `vec`: a point, (x, y) or (x, y, z)

```python
result = cq.Workplane("XY").box(10, 10, 10).translate((20, 0, 0))
```

## rotate(axisStartPoint, axisEndPoint, angleDegrees)

Rotate the part about an axis through two points.

- `axisStartPoint`, `axisEndPoint`: a point, (x, y) or (x, y, z)
- `angleDegrees`: degrees

```python
result = cq.Workplane("XY").box(30, 10, 10).rotate((0, 0, 0), (0, 0, 1), 45)
```

## mirror([mirrorPlane], [basePointVector], [union])

Mirror the part across a named plane; union=True keeps both halves as one solid.

- `mirrorPlane`: one of "XY", "YX", "XZ", "ZX", "YZ", "ZY"
- `basePointVector`: a point, (x, y) or (x, y, z), or None
- `union`: True or False

```python
result = cq.Workplane("XY").box(20, 10, 10, centered=False).mirror('YZ', union=True)
```

## mirrorX()

Mirror a half outline across the workplane's x axis, closing it.

```python
result = cq.Workplane("XY").vLine(10).hLine(20).vLineTo(0).mirrorX().extrude(5)
```

## mirrorY()

Mirror a half outline across the workplane's y axis, closing it.

```python
result = cq.Workplane("XY").hLine(20).vLine(10).hLineTo(0).mirrorY().extrude(5)
```

## union(toUnion, [clean])

Join another part to this one.

- `toUnion`: a part built earlier in the script
- `clean`: True or False

```python
base = cq.Workplane('XY').box(60, 40, 6)
rib = cq.Workplane('XY').box(6, 40, 20).translate((0, 0, 13))
result = base.union(rib)
```

## cut(toCut, [clean])

Remove another part from this one.

- `toCut`: a part built earlier in the script
- `clean`: True or False

```python
block = cq.Workplane('XY').box(40, 40, 20)
pocket = cq.Workplane('XY').box(20, 20, 10).translate((0, 0, 5))
result = block.cut(pocket)
```

## intersect(toIntersect, [clean])

Keep what this part shares with another.

- `toIntersect`: a part built earlier in the script
- `clean`: True or False

```python
a = cq.Workplane('XY').box(40, 40, 20)
b = cq.Workplane('XY').sphere(22)
result = a.intersect(b)
```

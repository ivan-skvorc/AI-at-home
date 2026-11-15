"""What counts as a hole, case by case, on the STEP that was written.

Each case builds a part with the kernel, exports it, re-imports the STEP and
measures it, because that round trip is what the tool decides on. The expected
value is one (drill diameter, larger diameter, through) per hole.
"""

from __future__ import annotations

import pytest

cq = pytest.importorskip("cadquery", reason="the CAD kernel is not installed")

from cadquery import exporters, importers  # noqa: E402

from deerflow_extension_cad import measure  # noqa: E402


def plate():
    return cq.Workplane("XY").box(60, 40, 6)


def top(wp):
    return wp.faces(">Z").workplane()


def split_faces(wp, points):
    # What other CAD systems write: a closed (periodic) face cut into points + 1 pieces.
    # OCCT keeps one seamed face, so the split is forced here to cover both forms.
    from OCP.ShapeUpgrade import ShapeUpgrade_ShapeDivideClosed

    tool = ShapeUpgrade_ShapeDivideClosed(wp.findSolid().wrapped)
    tool.SetNbSplitPoints(points)
    tool.Perform()
    return cq.Shape.cast(tool.Result())


def concave_cylinder_faces(shape):
    return sum(1 for f in shape.Faces() if f.geomType() == "CYLINDER" and measure._face_record(f.wrapped))


def two_walls():
    return cq.Workplane("XY").box(40, 30, 20).faces("<Z").shell(-2).faces(">X").workplane().hole(4)


def opposite_blind():
    wp = top(plate()).hole(4, 2)
    return wp.faces("<Z").workplane().hole(4, 2)


def groove():
    ring = cq.Workplane("XY").workplane(offset=1).circle(8).circle(5).extrude(5)
    return plate().cut(ring)


def bored_post_in_recess():
    # the recess wall (16 mm, concave, full circle) surrounds a post that carries the real hole
    return top(groove()).hole(4)


def rounded_pocket():
    return top(plate()).rect(20, 10).cutBlind(-3).edges("|Z").edges("not(<X or >X or <Y or >Y)").fillet(2)


def inside_fillet():
    return cq.Workplane("XY").polyline([(0, 0), (30, 0), (30, 5), (5, 5), (5, 30), (0, 30)]).close().extrude(10).edges("|Z").fillet(2)


def seam_notch():
    # the cutter axis sits 1 mm outside the block, so a 141 degree concave arc is left,
    # centred on the +X direction of the cylinder, where its parametric seam is
    return cq.Workplane("XY").box(20, 20, 10, centered=(False, True, True)).cut(cq.Workplane("XY").center(-1, 0).circle(3).extrude(20, both=True))


# name, builder, expected (drill diameter, larger diameter, through) per hole, and optionally
# the number of concave cylindrical faces the re-imported solid must have (a precondition
# that proves the split-face cases really reach measure_holes as split faces)
T, B = True, False
CASES = [
    ("plate, two 4 mm through holes", lambda: top(plate()).pushPoints([(-20, 0), (20, 0)]).hole(4), [(4.0, None, T)] * 2),
    ("plate, one 4 mm through hole", lambda: top(plate()).pushPoints([(-20, 0)]).hole(4), [(4.0, None, T)]),
    ("plate, no hole", plate, []),
    ("cboreHole(4, 8, 2)", lambda: top(plate()).cboreHole(4, 8, 2), [(4.0, 8.0, T)]),
    ("cskHole(4, 8, 82)", lambda: top(plate()).cskHole(4, 8, 82), [(4.0, 8.0, T)]),
    ("blind hole, depth 3", lambda: top(plate()).hole(4, 3), [(4.0, None, B)]),
    ("blind cboreHole(4, 8, 2, depth 4)", lambda: top(plate()).cboreHole(4, 8, 2, 4), [(4.0, 8.0, B)]),
    ("cutThruAll of a circle", lambda: top(plate()).circle(2.5).cutThruAll(), [(5.0, None, T)]),
    ("cutBlind of a circle, 2 deep", lambda: top(plate()).circle(2.5).cutBlind(-2), [(5.0, None, B)]),
    ("hole wall split into two half faces", lambda: split_faces(top(plate()).hole(4), 1), [(4.0, None, T)], 2),
    ("two holes, walls split into three faces each", lambda: split_faces(top(plate()).pushPoints([(-20, 0), (20, 0)]).hole(4), 2), [(4.0, None, T)] * 2, 6),
    ("cboreHole with every wall split into two half faces", lambda: split_faces(top(plate()).cboreHole(4, 8, 2), 1), [(4.0, 8.0, T)], 4),
    ("cskHole with cylinder and cone split into half faces", lambda: split_faces(top(plate()).cskHole(4, 8, 82), 1), [(4.0, 8.0, T)], 2),
    ("polar pattern of six 3 mm holes", lambda: top(cq.Workplane("XY").cylinder(6, 25)).polarArray(15, 0, 360, 6).hole(3), [(3.0, None, T)] * 6),
    ("rarray 3 x 2 of 3 mm holes", lambda: top(plate()).rarray(15, 15, 3, 2).hole(3), [(3.0, None, T)] * 6),
    ("two holes, 3 mm and 5 mm", lambda: top(top(plate()).center(-20, 0).hole(3)).center(20, 0).hole(5), [(3.0, None, T), (5.0, None, T)]),
    ("box, vertical edges filleted", lambda: cq.Workplane("XY").box(30, 20, 10).edges("|Z").fillet(3), []),
    ("box, all edges filleted", lambda: cq.Workplane("XY").box(30, 20, 10).edges().fillet(2), []),
    ("box, all edges chamfered", lambda: cq.Workplane("XY").box(30, 20, 10).edges().chamfer(1), []),
    ("cylinder primitive", lambda: cq.Workplane("XY").cylinder(20, 8), []),
    ("plate with a round boss", lambda: top(plate()).circle(6).extrude(5), []),
    ("plate with a boss and a hole through the boss", lambda: top(top(plate()).circle(6).extrude(5)).hole(4), [(4.0, None, T)]),
    ("cylinder with a square through cut (outer wall is convex, axis in air)", lambda: top(cq.Workplane("XY").cylinder(20, 8)).rect(6, 6).cutThruAll(), []),
    ("round boss with a square through cut on a plate", lambda: top(top(plate()).circle(8).extrude(6)).rect(5, 5).cutThruAll(), []),
    ("tube (cylinder with a bore)", lambda: top(cq.Workplane("XY").cylinder(20, 8)).hole(10), [(10.0, None, T)]),
    ("shelled box, one hole in the top wall", lambda: top(cq.Workplane("XY").box(40, 30, 20).faces("<Z").shell(-2)).hole(5), [(5.0, None, T)]),
    ("shelled filleted box, no hole", lambda: cq.Workplane("XY").box(40, 30, 20).edges("|Z").fillet(5).faces("<Z").shell(-2), []),
    ("one drill pass through both walls of a shelled box", two_walls, [(4.0, None, T)]),
    ("two blind holes from opposite sides, same axis", opposite_blind, [(4.0, None, B)] * 2),
    ("slot2D cut through a plate (rule: 180 degree ends are not holes)", lambda: top(plate()).slot2D(20, 6).cutThruAll(), []),
    ("rectangular pocket with rounded corners", rounded_pocket, []),
    ("L bracket with filleted inside corner", inside_fillet, []),
    ("annular groove around an island", groove, []),
    ("bored post inside a round recess (recess wall is not a counterbore)", bored_post_in_recess, [(4.0, None, T)]),
    ("counterbore 4/8 from the top plus a 6 mm counterbore from the bottom", lambda: top(plate()).cboreHole(4, 8, 2).faces("<Z").workplane().cboreHole(4, 6, 1), [(4.0, 8.0, T)]),
    ("blind 3 mm from the top meeting a blind 5 mm from the bottom", lambda: top(plate()).hole(3, 3).faces("<Z").workplane().hole(5, 3), [(3.0, 5.0, T)]),
    (
        "coaxial 6 mm and 3 mm holes in opposite walls of a shelled box (two holes)",
        lambda: cq.Workplane("XY").box(40, 30, 20).faces("<Z").shell(-2).faces(">X").workplane().hole(6, 3).faces("<X").workplane().hole(3, 3),
        [(3.0, None, T), (6.0, None, T)],
    ),
    (
        "two blind holes facing each other across the cavity of a shelled box (not one through hole)",
        lambda: cq.Workplane("XY").box(80, 60, 30).faces(">Z").shell(-3).faces(">X").workplane().hole(6, 1.5).faces("<X").workplane().hole(6, 1.5),
        [(6.0, None, B)] * 2,
    ),
    ("hole with a chamfered mouth", lambda: top(plate()).hole(4).faces(">Z").edges("%CIRCLE").chamfer(0.5), [(4.0, 5.0, T)]),
    ("hole on a side face (axis along X)", lambda: plate().faces(">X").workplane().hole(3, 10), [(3.0, None, B)]),
    ("hole on a tilted workplane", lambda: cq.Workplane("XY").box(30, 30, 30).faces(">Z").workplane().transformed(rotate=(30, 20, 0)).hole(4), [(4.0, None, T)]),
    ("cross-drilled block (two axes)", lambda: cq.Workplane("XY").box(20, 20, 20).faces(">Z").workplane().hole(6).faces(">X").workplane(centerOption="CenterOfMass").hole(4), [(4.0, None, T), (6.0, None, T)]),
    ("half-round notch on an edge (hole centred on the edge)", lambda: cq.Workplane("XY").box(20, 20, 20).faces(">X").workplane(origin=(0, 0, 10)).hole(4), []),
    ("notch whose arc straddles the cylinder seam", seam_notch, []),
    ("shelled box, no hole (last operation is shell)", lambda: cq.Workplane("XY").box(40, 30, 20).faces("<Z").shell(-2), []),
    ("shelled filleted enclosure, 10 x 10 pattern of 3 mm holes", lambda: top(cq.Workplane("XY").box(120, 80, 40).edges("|Z").fillet(6).edges(">Z").fillet(4).faces("<Z").shell(-2)).rarray(8, 6, 10, 10).hole(3), [(3.0, None, T)] * 100),
    ("closed cylindrical void inside a block (not a hole)", lambda: cq.Workplane("XY").box(20, 20, 20).cut(cq.Workplane("XY").cylinder(10, 4)), []),
    ("limit: shelled cylinder (a cup) reads as one blind hole", lambda: cq.Workplane("XY").cylinder(20, 10).faces(">Z").shell(-2), [(16.0, None, B)]),
]


@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_holes_are_counted_on_the_reimported_step(case, tmp_path):
    name, build, expected, *faces_wanted = case
    built = build()
    part = built.findSolid() if isinstance(built, cq.Workplane) else built
    path = tmp_path / "case.step"
    # The shape is exported, not the Workplane: exporting a Workplane flattens a
    # shell() result into bare shells, and the STEP then holds no solid at all.
    exporters.export(part, str(path))
    solids = [solid for value in importers.importStep(str(path)).vals() for solid in value.Solids()]
    assert len(solids) == 1
    holes = measure.measure_holes(solids[0])
    seen = sorted(((hole["diameter_mm"], hole.get("larger_diameter_mm"), hole["through"]) for hole in holes), key=repr)
    assert seen == sorted(expected, key=repr)
    if faces_wanted:
        # A precondition: the split-face cases really reach the measurement as split faces.
        assert concave_cylinder_faces(solids[0]) == faces_wanted[0]


def _reimported(part, tmp_path):
    path = tmp_path / "part.step"
    exporters.export(part.findSolid(), str(path))
    (solid,) = [solid for value in importers.importStep(str(path)).vals() for solid in value.Solids()]
    return solid


def test_a_hole_through_two_walls_says_so(tmp_path):
    # One drill pass through an enclosure counts once. A model that meant one wall, or
    # listed one hole per wall, has to be able to see why the count is what it is.
    (through_both,) = measure.measure_holes(_reimported(two_walls(), tmp_path))
    assert (through_both["diameter_mm"], through_both["through"], through_both["walls"]) == (4.0, True, 2)
    (plain,) = measure.measure_holes(_reimported(top(plate()).hole(4), tmp_path))
    assert "walls" not in plain


def test_measuring_stays_fast_when_holes_break_out_of_an_edge(tmp_path):
    # A wall pattern that slid down to the floor: twenty half holes on the bottom edge. The kernel's
    # own point classifier then took 0.4 s per point and the measurement 28 s, past the build's wall clock.
    import time

    body = cq.Workplane("XY").box(150, 100, 40).edges("|Z").fillet(8).faces(">Z").shell(-2)
    body = body.faces("<Z").workplane().rarray(7, 7, 10, 10).hole(4)
    solid = _reimported(body.faces(">Y").workplane().rarray(6, 6, 20, 5).hole(3), tmp_path)
    started = time.monotonic()
    holes = measure.measure_holes(solid)
    assert time.monotonic() - started < 5
    assert sorted({hole["diameter_mm"] for hole in holes}) == [3.0, 4.0] and len([hole for hole in holes if hole["diameter_mm"] == 4.0]) == 100


def test_the_fast_point_test_agrees_with_the_kernels_classifier(tmp_path):
    # Material or air is decided by counting surface crossings along a ray. The kernel's classifier
    # is the reference: on every point the measurement asks about, both must say the same.
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_IN

    asked = []
    real = measure._Classifier.in_material

    def recording(self, a, ru=0.0, rv=0.0):
        answer = real(self, a, ru, rv)
        asked.append((self.point(a, ru, rv), answer))
        return answer

    parts = [case[1]() for case in CASES if "split" not in case[0]]
    try:
        measure._Classifier.in_material = recording
        for index, built in enumerate(parts):
            asked.clear()
            directory = tmp_path / str(index)
            directory.mkdir()
            solid = _reimported(built, directory) if isinstance(built, cq.Workplane) else None
            if solid is None:
                continue
            measure.measure_holes(solid)
            reference = BRepClass3d_SolidClassifier(solid.wrapped)
            for point, answer in asked:
                reference.Perform(gp_Pnt(*point), measure.CLASSIFY_TOL)
                assert answer == (reference.State() == TopAbs_IN), (index, point)
    finally:
        measure._Classifier.in_material = real


def test_the_written_step_is_measured_as_one_valid_closed_solid(tmp_path):
    part = top(plate()).pushPoints([(-15, 0), (15, 0)]).hole(4).findSolid()
    path = tmp_path / "plate.step"
    exporters.export(part, str(path))
    measured = measure.measure_step(path, cq)
    assert (measured["solids"], measured["valid"], measured["closed"]) == (1, True, True)
    assert measured["bbox_mm"] == [60.0, 40.0, 6.0]
    # 60 x 40 x 6 minus two 4 mm holes: 14400 - 2 * pi * 2**2 * 6.
    assert measured["volume_mm3"] == pytest.approx(14249.204, abs=0.01)
    assert [hole["diameter_mm"] for hole in measured["holes"]] == [4.0, 4.0]


def test_two_separate_solids_are_counted_and_not_measured_for_holes(tmp_path):
    two = cq.Workplane("XY").box(10, 10, 10).union(cq.Workplane("XY").box(10, 10, 10).translate((30, 0, 0))).findSolid()
    path = tmp_path / "two.step"
    exporters.export(two, str(path))
    measured = measure.measure_step(path, cq)
    assert measured["solids"] == 2 and measured["holes"] == []
    assert measured["bbox_mm"] == [40.0, 10.0, 10.0] and measured["volume_mm3"] == pytest.approx(2000.0, abs=0.01)

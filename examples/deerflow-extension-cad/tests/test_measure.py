"""What counts as a hole, case by case, on the STEP that was written.

Each case builds a part with the kernel, exports it, re-imports the STEP and
measures it, because that round trip is what the tool decides on. The expected
value is one (drill diameter, larger diameter, through) per hole.

The later sections cover where holes are, the size and mass of the part, parts
of several bodies and the gaps between them, the sampled wall, and
``measure_cli``, which measures one STEP the same way outside the Gateway.
"""

from __future__ import annotations

import json
import math

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


# --- Where the features are (items 57, 51 and 54) ------------------------------


def _step(shape, tmp_path, name="part.step"):
    path = tmp_path / name
    exporters.export(shape.findSolid() if isinstance(shape, cq.Workplane) else shape, str(path))
    return path


def _bodies(*parts):
    # Loose bodies in one file: what a print-in-place design or an assembled kit exports.
    return cq.Compound.makeCompound([part.findSolid() if isinstance(part, cq.Workplane) else part for part in parts])


def _near(seen, wanted, tolerance=0.01):
    return len(seen) == len(wanted) and all(abs(s - w) <= tolerance for s, w in zip(seen, wanted))


def test_each_hole_says_where_it_enters_and_which_way_it_runs(tmp_path):
    # Two holes drilled from the top of a 40 x 30 x 6 plate and one drilled into its +X side.
    plate = cq.Workplane("XY").box(40, 30, 6)
    plate = plate.faces(">Z").workplane().pushPoints([(-15, 0), (15, 5)]).hole(4)
    plate = plate.faces(">X").workplane(origin=(0, 0, 0)).hole(3, 10)  # the global origin projected: (20, 0, 0)
    holes = measure.measure_step(_step(plate, tmp_path), cq)["holes"]
    seen = sorted((hole["diameter_mm"], tuple(hole["at"]), tuple(hole["axis"])) for hole in holes)
    wanted = [(3.0, (20, 0, 0), (-1, 0, 0)), (4.0, (-15, 0, 3), (0, 0, -1)), (4.0, (15, 5, 3), (0, 0, -1))]
    assert [diameter for diameter, _, _ in seen] == [diameter for diameter, _, _ in wanted]
    for (_, at, axis), (_, at_wanted, axis_wanted) in zip(seen, wanted):
        assert _near(at, at_wanted) and _near(axis, axis_wanted, 1e-4), (at, axis)


def test_a_hole_is_entered_from_its_open_end_or_its_wide_end(tmp_path):
    # A blind hole can only be entered where it is open. A through hole is entered where it is
    # widest (a counterbore here, drilled from below), otherwise from its upper end.
    blind_from_below = cq.Workplane("XY").box(40, 30, 6).faces("<Z").workplane().hole(4, 3)
    (blind,) = measure.measure_step(_step(blind_from_below, tmp_path, "blind.step"), cq)["holes"]
    assert _near(blind["at"], (0, 0, -3)) and _near(blind["axis"], (0, 0, 1), 1e-4)
    cbore_from_below = cq.Workplane("XY").box(40, 30, 6).faces("<Z").workplane().cboreHole(4, 8, 2)
    (cbore,) = measure.measure_step(_step(cbore_from_below, tmp_path, "cbore.step"), cq)["holes"]
    assert cbore["through"] and _near(cbore["at"], (0, 0, -3)) and _near(cbore["axis"], (0, 0, 1), 1e-4)
    # Through the -X wall of an enclosure: the inner end opens into the part's own cavity, so it is the exit.
    wall_hole = cq.Workplane("XY").box(40, 30, 20).faces("<Z").shell(-2).faces("<X").workplane(origin=(0, 0, 0)).hole(4, 3)
    (side,) = measure.measure_step(_step(wall_hole, tmp_path, "wall.step"), cq)["holes"]
    assert side["through"] and _near(side["at"], (-20, 0, 0)) and _near(side["axis"], (1, 0, 0), 1e-4)


def test_an_off_origin_part_reports_its_corners(tmp_path):
    box = cq.Workplane("XY").box(10, 20, 30).translate((100, -50, 7))
    measured = measure.measure_step(_step(box, tmp_path), cq)
    assert _near(measured["bbox_min_mm"], (95, -60, -8)) and _near(measured["bbox_max_mm"], (105, -40, 22))


def test_a_cube_reports_its_area_and_centre_of_mass(tmp_path):
    cube = cq.Workplane("XY").box(10, 10, 10).translate((7, -3, 12))
    measured = measure.measure_step(_step(cube, tmp_path), cq)
    assert measured["area_mm2"] == pytest.approx(600.0, abs=1e-3)
    assert _near(measured["centre_of_mass_mm"], (7, -3, 12), 1e-4)


def test_one_solid_keeps_every_key_it_had_and_gains_the_new_ones_after_them(tmp_path):
    # The tool, the report and the eval read this dict: it is extended, never reshaped.
    measured = measure.measure_step(_step(top(plate()).hole(4), tmp_path), cq)
    assert list(measured)[:6] == ["solids", "valid", "closed", "bbox_mm", "volume_mm3", "holes"]
    assert set(measured) == {"solids", "valid", "closed", "bbox_mm", "volume_mm3", "holes", "bbox_min_mm", "bbox_max_mm", "centre_of_mass_mm", "area_mm2"}
    (hole,) = measured["holes"]
    assert list(hole) == ["diameter_mm", "through", "depth_mm", "at", "axis"]


def hinge():
    # Two leaves 0.5 mm apart in z with a 6.6 mm bore each, and a 6 mm pin through both: 0.3 mm all round.
    leaf = cq.Workplane("XY").box(20, 20, 5, centered=(True, True, False)).faces(">Z").workplane().hole(6.6)
    pin = cq.Workplane("XY").circle(3).extrude(10.5)
    return _bodies(leaf, leaf.translate((0, 0, 5.5)), pin)


def test_each_body_is_measured_on_its_own_so_a_captive_pin_leaves_its_bore_a_hole(tmp_path):
    measured = measure.measure_step(_step(hinge(), tmp_path), cq)
    assert measured["solids"] == 3 and measured["holes"] == []  # the whole is not one solid
    bodies = sorted(measured["bodies"], key=lambda body: body["volume_mm3"])
    pin, low_leaf, high_leaf = bodies[0], *sorted(bodies[1:], key=lambda body: body["bbox_min_mm"][2])
    assert pin["holes"] == [] and pin["valid"] and pin["closed"]
    assert pin["volume_mm3"] == pytest.approx(3.14159265 * 9 * 10.5, abs=0.01)
    for leaf, top_z in ((low_leaf, 5), (high_leaf, 10.5)):
        (bore,) = leaf["holes"]
        assert (bore["diameter_mm"], bore["through"]) == (6.6, True)
        assert _near(bore["at"], (0, 0, top_z)) and _near(bore["axis"], (0, 0, -1), 1e-4)
        assert leaf["bbox_mm"] == [20.0, 20.0, 5.0] and _near(leaf["centre_of_mass_mm"][:2], (0, 0), 1e-4)
    assert sum(body["volume_mm3"] for body in bodies) == pytest.approx(measured["volume_mm3"], abs=0.01)
    assert sum(body["area_mm2"] for body in bodies) == pytest.approx(measured["area_mm2"], abs=0.01)


def test_the_smallest_gap_between_bodies_is_measured_with_its_pair_and_direction(tmp_path):
    measured = measure.measure_step(_step(hinge(), tmp_path), cq)
    gaps = measured["gaps"]
    assert [round(gap["gap_mm"], 2) for gap in gaps] == [0.3, 0.3, 0.5]
    volumes = [body["volume_mm3"] for body in measured["bodies"]]
    pin = volumes.index(min(volumes))
    for gap in gaps[:2]:
        # pin against a leaf: radial, so horizontal
        assert pin in gap["bodies"] and abs(gap["direction"][2]) < 1e-6
        assert abs(math.hypot(*gap["direction"]) - 1) < 1e-3
    (leaves,) = gaps[2:]
    assert pin not in leaves["bodies"] and leaves["bodies"][0] < leaves["bodies"][1]
    # from the first body of the pair to the second: the leaves are stacked, so straight up or down
    assert abs(abs(leaves["direction"][2]) - 1) < 1e-6
    assert 5 <= leaves["at_mm"][2] <= 5.5


def test_bodies_that_overlap_or_sit_inside_each_other_have_no_gap(tmp_path):
    overlapping = _bodies(cq.Workplane("XY").box(10, 10, 10), cq.Workplane("XY").box(10, 10, 10).translate((5, 0, 0)))
    (gap,) = measure.measure_step(_step(overlapping, tmp_path, "overlap.step"), cq)["gaps"]
    assert gap["gap_mm"] == 0 and gap["direction"] is None
    # No surface of one meets the other, yet they share material: the kernel's distance is 4 mm here.
    nested = _bodies(cq.Workplane("XY").box(20, 20, 20), cq.Workplane("XY").box(4, 4, 4))
    (gap,) = measure.measure_step(_step(nested, tmp_path, "nested.step"), cq)["gaps"]
    assert gap["gap_mm"] == 0 and gap["direction"] is None


def test_far_apart_bodies_still_report_their_smallest_gap(tmp_path):
    two = cq.Workplane("XY").box(10, 10, 10).union(cq.Workplane("XY").box(10, 10, 10).translate((30, 0, 0)))
    (gap,) = measure.measure_step(_step(two, tmp_path), cq)["gaps"]
    assert gap["gap_mm"] == pytest.approx(20.0, abs=1e-6) and gap["bodies"] == [0, 1]
    assert _near(gap["direction"], (1, 0, 0), 1e-6) or _near(gap["direction"], (-1, 0, 0), 1e-6)


def row_of_cubes(count, narrow):
    # 2 mm cubes 1 mm apart along x, except the pair after cube *narrow*, which is 0.4 mm apart
    cubes, x = [], 0.0
    for index in range(count):
        cubes.append(cq.Workplane("XY").box(2, 2, 2).translate((x, 0, 0)))
        x += 2 + (0.4 if index == narrow else 1.0)
    return _bodies(*cubes)


def test_many_bodies_find_the_smallest_gap_and_list_only_the_close_pairs(tmp_path):
    measured = measure.measure_step(_step(row_of_cubes(30, 17), tmp_path), cq)
    gaps = measured["gaps"]
    assert gaps[0]["gap_mm"] == pytest.approx(0.4, abs=1e-6)
    left, right = gaps[0]["bodies"]
    lows = [body["bbox_min_mm"][0] for body in measured["bodies"]]
    assert sorted((lows[left], lows[right])) == pytest.approx([17 * 3 - 1, 17 * 3 + 1.4], abs=1e-4)
    # 29 neighbouring pairs are under GAP_NEAR_MM; the list keeps the smallest MAX_GAPS_LISTED
    assert len(gaps) == measure.MAX_GAPS_LISTED and all(gap["gap_mm"] <= measure.GAP_NEAR_MM for gap in gaps)
    assert [gap["gap_mm"] for gap in gaps] == sorted(gap["gap_mm"] for gap in gaps)
    assert "gaps_incomplete" not in measured


def test_measuring_gaps_stops_at_its_pair_cap_and_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(measure, "MAX_GAP_PAIRS", 3)
    measured = measure.measure_step(_step(row_of_cubes(30, 17), tmp_path), cq)
    assert measured["gaps_incomplete"] is True and len(measured["gaps"]) <= 3


def test_the_sampled_wall_of_a_one_millimetre_shell(tmp_path):
    shell = cq.Workplane("XY").box(40, 30, 20).faces(">Z").shell(-1)
    wall = measure.sampled_wall(measure.step_solids(_step(shell, tmp_path), cq))
    assert wall["thinnest_wall_sampled_mm"] == pytest.approx(1.0, abs=0.05)
    assert wall["wall_sampling_complete"] is True and wall["wall_samples"] > 0
    assert len(wall["thinnest_wall_at_mm"]) == 3


def test_the_sampled_wall_of_a_t_shape_and_of_a_tube(tmp_path):
    tee = cq.Workplane("XY").box(10, 10, 4).union(cq.Workplane("XY").box(40, 10, 4).translate((0, 0, 4)))
    assert measure.sampled_wall(measure.step_solids(_step(tee, tmp_path, "tee.step"), cq))["thinnest_wall_sampled_mm"] == pytest.approx(4.0, abs=0.05)
    tube = top(cq.Workplane("XY").cylinder(20, 8)).hole(10)
    assert measure.sampled_wall(measure.step_solids(_step(tube, tmp_path, "tube.step"), cq))["thinnest_wall_sampled_mm"] == pytest.approx(3.0, abs=0.05)


def test_the_sampled_wall_takes_the_thinnest_body_and_keeps_to_its_time(tmp_path):
    import time

    solids = measure.step_solids(_step(_bodies(cq.Workplane("XY").box(10, 10, 10), cq.Workplane("XY").box(10, 10, 1.5).translate((20, 0, 0))), tmp_path, "two.step"), cq)
    assert measure.sampled_wall(solids)["thinnest_wall_sampled_mm"] == pytest.approx(1.5, abs=0.05)
    enclosure = top(cq.Workplane("XY").box(120, 80, 40).edges("|Z").fillet(6).edges(">Z").fillet(4).faces("<Z").shell(-2)).rarray(8, 6, 10, 10).hole(3)
    solids = measure.step_solids(_step(enclosure, tmp_path, "enclosure.step"), cq)
    started = time.monotonic()
    wall = measure.sampled_wall(solids)
    assert time.monotonic() - started < measure.WALL_SECONDS + 0.5
    assert wall["thinnest_wall_sampled_mm"] == pytest.approx(2.0, abs=0.05)
    started = time.monotonic()
    rushed = measure.sampled_wall(solids, seconds=0.0)
    assert time.monotonic() - started < 0.5 and rushed["wall_sampling_complete"] is False


# --- measure_cli: one STEP measured and judged outside the Gateway ------------------


def _cli(*args, code=None):
    import subprocess
    import sys

    command = [sys.executable, "-I", *(["-c", code] if code else ["-m", "deerflow_extension_cad.measure_cli"]), *map(str, args)]
    return subprocess.run(command, capture_output=True, text=True, timeout=120)


def _holed_plate(tmp_path):
    return _step(top(plate()).pushPoints([(-15, 0), (15, 5)]).hole(4), tmp_path, "plate.step")


def test_measure_cli_prints_what_the_tool_measures(tmp_path):
    path = _holed_plate(tmp_path)
    done = _cli(path)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {"measured": measure.measure_step(path, cq)}


def test_measure_cli_judges_a_step_against_its_truth(tmp_path):
    from deerflow_extension_cad import measure_cli

    path = _holed_plate(tmp_path)
    truth = {"bbox_xyz_mm": [60, 40, 6], "volume_min_max_mm3": [14000, 14500], "hole_diameters_mm": [4, 4]}
    judged = measure_cli.report(path, truth)
    assert judged["passed"] is True and judged["expected"] == truth and judged["measured"] == measure.measure_step(path, cq)
    assert [check["check"] for check in judged["checks"]] == ["one closed solid", "bounding box", "volume", "holes"]
    (tmp_path / "truth.json").write_text(json.dumps({**truth, "bbox_xyz_mm": [61, 40, 6]}))
    done = _cli(path, tmp_path / "truth.json")
    assert done.returncode == 1, done.stderr
    failed = json.loads(done.stdout)
    assert failed["passed"] is False and [check["check"] for check in failed["checks"] if not check["passed"]] == ["bounding box"]


def test_measure_cli_reports_several_bodies_with_the_tools_notes(tmp_path):
    from deerflow_extension_cad import measure_cli

    judged = measure_cli.report(_step(hinge(), tmp_path), {"bbox_xyz_mm": [20, 20, 10.5]})
    assert judged["passed"] is False and len(judged["measured"]["bodies"]) == 3
    assert any("3 separate bodies" in note for note in judged["notes"])


def test_measure_cli_keeps_standard_output_for_its_answer(tmp_path):
    # The kernel prints its STEP reader's errors to standard output; the answer must still parse.
    broken = tmp_path / "broken.step"
    broken.write_text("ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\n#1=FOO(;\nENDSEC;\nEND-ISO-10303-21;\n")
    done = _cli(broken)
    assert done.returncode == 2
    assert set(json.loads(done.stdout)) == {"error"} and "ERR" in done.stderr


def test_measure_cli_refuses_arguments_it_cannot_use(tmp_path):
    path = _holed_plate(tmp_path)
    (tmp_path / "list.json").write_text("[60, 40, 6]")
    (tmp_path / "nobox.json").write_text('{"hole_diameters_mm": [4]}')
    (tmp_path / "badvolume.json").write_text('{"bbox_xyz_mm": [60, 40, 6], "volume_min_max_mm3": "big"}')
    for args in ((), (path, tmp_path / "list.json", "extra"), (tmp_path / "missing.step",), (path, tmp_path / "missing.json"), (path, tmp_path / "list.json"), (path, tmp_path / "nobox.json"), (path, tmp_path / "badvolume.json")):
        done = _cli(*args)
        assert done.returncode == 2, (args, done.stdout, done.stderr)
        assert list(json.loads(done.stdout)) == ["error"], args


def test_measure_cli_measures_under_the_workers_ceilings(tmp_path):
    from deerflow_extension_cad import measure_cli

    probe = (
        "import resource, sys\n"
        "from deerflow_extension_cad import measure_cli\n"
        "measure_cli.report = lambda step, truth: {'limits': [resource.getrlimit(getattr(resource, name))[0] for name in ('RLIMIT_AS', 'RLIMIT_CPU', 'RLIMIT_FSIZE')]}\n"
        "sys.exit(measure_cli.main(sys.argv[1:]))\n"
    )
    done = _cli(_holed_plate(tmp_path), code=probe)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {"limits": [measure_cli.MEMORY_MB * 1024 * 1024, measure_cli.CPU_SECONDS, measure_cli.MAX_OUTPUT_BYTES]}


def test_importing_measure_cli_loads_neither_the_kernel_nor_the_gateway():
    done = _cli(code="import sys, deerflow_extension_cad.measure_cli\nprint(sorted({m.split('.')[0] for m in sys.modules} & {'cadquery', 'OCP', 'app', 'deerflow'}))")
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]"

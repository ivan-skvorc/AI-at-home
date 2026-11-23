from deerflow_extension_cad_design.scad import capped_diff, parse_params


def test_top_level_numbers_and_booleans_are_parameters():
    code = """// a plate
width = 40; // [10:1:100]
depth=20.5;
holes = true;
neg = -3e1;
name = "plate";
module plate(t = 2) {
  inner = 5;
  cube([width, depth, t]);
}
/* skipped = 9;
   also = 1; */
after = 7;
"""
    assert parse_params(code) == {"width": 40, "depth": 20.5, "holes": True, "neg": -30.0, "after": 7}


def test_nested_brackets_and_strings_do_not_confuse_depth():
    code = 'echo("{ not a brace");\nlist = [1,\n  inside = 3;\n  2];\nx = 1;\n'
    assert parse_params(code) == {"x": 1}


def test_the_diff_is_cut_on_a_line_boundary():
    before = "\n".join(f"a{i} = {i};" for i in range(100))
    after = "\n".join(f"a{i} = {i + 1};" for i in range(100))
    text, whole = capped_diff(before, after, 200)
    assert not whole and len(text) <= 200 and text.endswith("\n")
    text, whole = capped_diff("x = 1;\n", "x = 2;\n", 200)
    assert whole and "-x = 1;" in text and "+x = 2;" in text

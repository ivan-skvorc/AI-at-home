"""What the model is told about the design.

The brief rides the system message only on design runs (middleware.py), so
ordinary conversations pay nothing for it. It is static text: the version
folders are the record, and the brief tells the model to read the newest one
instead of repeating it, which also keeps the system message cacheable.
"""

from __future__ import annotations

from .constants import FOLDER, WORKING_FILE

DESIGN_BRIEF = f"""## Design page
This conversation is a design on the user's Designs page. The page shows the newest version folder under {FOLDER}: its bodies in 3D, the view images, the checks and the files.
Follow the cad-modeling skill (read /mnt/skills/public/cad-modeling/SKILL.md first) with these fixed paths:
- Edit {WORKING_FILE} in place.
- Render with `cadkit.py render {WORKING_FILE} --design {FOLDER} --print-layout`: each render is the next version the page shows.
- Run check, views and print on {FOLDER}; export when the user asks for files or is happy.
- Before you change anything, read the newest version's report.json.
End each turn with what changed, which checks pass and what is left."""

#: Added when the run cannot render in a per-thread CAD container (no container mode, or
#: no bash tool): the page cannot work, and the model must not pretend it does or run the
#: CAD code anywhere else.
NO_CONTAINER = (
    "This server runs no per-thread CAD container for this conversation, and the Designs page needs one, so run no CAD code. "
    "Tell the user to set it up: `make sandbox-cad-image`, then `make sandbox-enable MODE=container IMAGE=cad`, then restart the Gateway. Then stop."
)

#: Appended to the user's message when the page shows an older version than the newest.
VIEWING_SUFFIX = "\n\n[Designs page: the user is looking at v{seq} ({folder}/v{seq}), not the newest version.]"

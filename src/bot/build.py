"""Building as a joined client: ``DirectoryData("Construction", jobs)``.

From the binary (journal2 "How a client builds"): a client's build tool queues
jobs and sends them to the host as a ``Construction`` tree::

    Construction {pn=<actor number>}
      Jobs {Size=N}
        [i 0] {Type='Foundations', Material=59, PosX, PosY, SizeX, SizeY, ...}

The host re-checks each job (its own ``Status``), so a bad spot is refused
there. Job fields mirror the host's own ``PlayerData`` jobs (captures).
Names and ids come from :mod:`src.protocol.enums`.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.protocol import rpc
from src.protocol.enums import MATERIALS, OBJECTS, ROOMS, id_of
from src.protocol.snapshot import Node, compress, encode_tree

DIRECTORY_DATA = 9
CONSTRUCTION = "Construction"
VALID = 1  # Job.Status of a valid preview (the host re-checks it)

ORIENTATIONS = {
    "down": (0.0, 1.0),
    "up": (0.0, -1.0),
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
}
"""Object facing -> (``OrX``, ``OrY``); the captures place with ``OrY=1``."""


@dataclass(frozen=True)
class Job:
    """One build job: tool name, material/object/room id, area, facing."""

    type: str
    material: int
    x: int
    y: int
    width: int = 1
    height: int = 1
    facing: str = "down"

    def node(self, index: int) -> Node:
        """The job as an ``[i N]`` node."""
        or_x, or_y = ORIENTATIONS[self.facing]
        fields = [
            ("Type", self.type),
            ("Material", self.material),
            ("PosX", self.x),
            ("PosY", self.y),
            ("SizeX", self.width),
            ("SizeY", self.height),
            ("OrX", or_x),
            ("OrY", or_y),
            ("Status", VALID),
        ]
        return Node(f"[i {index}]", fields)


def foundation(
    x: int, y: int, width: int, height: int, material: str = "BuildingConcrete"
) -> Job:
    """A foundation (floor + walls round the edge) over ``width`` x ``height``."""
    return Job("Foundations", id_of(MATERIALS, material), x, y, width, height)


def wall(
    x: int, y: int, width: int = 1, height: int = 1, material: str = "ConcreteWall"
) -> Job:
    """A wall line/area (``flooring`` tool with a wall material, as captured)."""
    return Job("flooring", id_of(MATERIALS, material), x, y, width, height)


def floor(
    x: int, y: int, width: int, height: int, material: str = "ConcreteFloor"
) -> Job:
    """A floor area (``flooring`` tool)."""
    return Job("flooring", id_of(MATERIALS, material), x, y, width, height)


def room(x: int, y: int, width: int, height: int, kind: str = "Cell") -> Job:
    """Zone a room (``Designation`` tool; ``Material`` is the room type)."""
    return Job("Designation", id_of(ROOMS, kind), x, y, width, height)


def place(obj: str, x: int, y: int, facing: str = "down") -> Job:
    """Install an object (``Objects`` tool; ``Material`` is the object type)."""
    return Job("Objects", id_of(OBJECTS, obj), x, y, facing=facing)


def construction_tree(jobs: list[Job], actor: int) -> Node:
    """The ``Construction`` tree a client sends."""
    items = Node("Jobs", [("Size", len(jobs))], [j.node(i) for i, j in enumerate(jobs)])
    return Node(CONSTRUCTION, [("pn", actor)], [items])


def construction_data(jobs: list[Job], actor: int) -> bytes:
    """The ``DirectoryData`` RPC payload for ``jobs``."""
    blob = compress(encode_tree(construction_tree(jobs, actor)))
    return rpc.build(DIRECTORY_DATA, CONSTRUCTION, blob)

"""A small transfer on a Hamilton STARlet deck, used by `steadyhand demo` and by the tests.

Eight channels pick up tips, take 100 uL from column 1 of a source plate, put it in column 1
of a destination plate, and return the tips. Two deliberate mistakes can be switched on to
show what a rehearsal catches.
"""

from __future__ import annotations

import warnings
from typing import Tuple

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.resources import Coordinate, set_tip_tracking, set_volume_tracking
from pylabrobot.resources.corning import Cor_96_wellplate_360ul_Fb
from pylabrobot.resources.hamilton import (
  PLT_CAR_L5AC_A00,
  TIP_CAR_480_A00,
  STARLetDeck,
  hamilton_96_tiprack_300uL_filter,
)

from .record import RecordingBackend

FAULTS = {
  "none": "the protocol as intended",
  "offset": "aspirate 4.5 mm to the right of each well's centre, onto the wall between wells",
  "depth": "aspirate 3 mm below each well's floor",
}


def build_deck() -> STARLetDeck:
  """A STARlet deck with one tip rack and two 96-well plates."""
  deck = STARLetDeck()

  tip_carrier = TIP_CAR_480_A00(name="tip_carrier")
  tip_carrier[0] = hamilton_96_tiprack_300uL_filter(name="tips")
  deck.assign_child_resource(tip_carrier, rails=1)

  plate_carrier = PLT_CAR_L5AC_A00(name="plate_carrier")
  plate_carrier[0] = Cor_96_wellplate_360ul_Fb(name="source")
  plate_carrier[1] = Cor_96_wellplate_360ul_Fb(name="destination")
  deck.assign_child_resource(plate_carrier, rails=7)
  return deck


async def run_demo(fault: str = "none") -> Tuple[STARLetDeck, RecordingBackend]:
  """Run the transfer against a recording backend. Returns the deck and the backend."""
  if fault not in FAULTS:
    raise ValueError(f"unknown fault {fault!r}; choose from {sorted(FAULTS)}")

  set_volume_tracking(True)
  set_tip_tracking(True)

  deck = build_deck()
  backend = RecordingBackend(num_channels=8)
  with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    handler = LiquidHandler(backend=backend, deck=deck)
    await handler.setup()

    tips = deck.get_resource("tips")
    source = deck.get_resource("source")
    destination = deck.get_resource("destination")
    for well in source["A1:H1"]:
      well.tracker.set_liquids([(None, 200.0)])

    offsets = None
    if fault == "offset":
      offsets = [Coordinate(4.5, 0, 0)] * 8
    elif fault == "depth":
      offsets = [Coordinate(0, 0, -3.0)] * 8

    await handler.pick_up_tips(tips["A1:H1"])
    await handler.aspirate(source["A1:H1"], vols=[100.0] * 8, offsets=offsets)
    await handler.dispense(destination["A1:H1"], vols=[100.0] * 8)
    await handler.return_tips()
    await handler.stop()

  return deck, backend

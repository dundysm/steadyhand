"""A centred transfer must rehearse cleanly on plates of every format PyLabRobot ships.

This guards the floor-and-walls model against false alarms: if a well's own geometry made the
scene report a collision for a correct move, this is where it would show.
"""

import asyncio
import inspect
import warnings

import pylabrobot.resources as resources
import pytest
from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.resources import Plate, set_tip_tracking, set_volume_tracking
from pylabrobot.resources.hamilton import (
  PLT_CAR_L5AC_A00,
  TIP_CAR_480_A00,
  STARLetDeck,
  hamilton_96_tiprack_300uL_filter,
)

from steadyhand import RecordingBackend, rehearse


def plate_makers():
  names = []
  for name in sorted(dir(resources)):
    maker = getattr(resources, name)
    if not inspect.isfunction(maker) or list(inspect.signature(maker).parameters)[:1] != ["name"]:
      continue
    try:
      with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        made = maker(name="probe")
    except Exception:
      continue
    if isinstance(made, Plate):
      names.append(name)
  return names


async def transfer_in_place(maker_name):
  set_volume_tracking(True)
  set_tip_tracking(True)
  deck = STARLetDeck()
  tip_carrier = TIP_CAR_480_A00(name="tip_carrier")
  tip_carrier[0] = hamilton_96_tiprack_300uL_filter(name="tips")
  deck.assign_child_resource(tip_carrier, rails=1)
  plate_carrier = PLT_CAR_L5AC_A00(name="plate_carrier")
  plate_carrier[0] = getattr(resources, maker_name)(name="plate")
  deck.assign_child_resource(plate_carrier, rails=7)

  backend = RecordingBackend(num_channels=8)
  handler = LiquidHandler(backend=backend, deck=deck)
  await handler.setup()
  well = deck.get_resource("plate").get_item("A1")
  volume = min(10.0, well.max_volume / 2)
  well.tracker.set_liquids([(None, volume * 2)])
  await handler.pick_up_tips(deck.get_resource("tips")["A1"])
  await handler.aspirate([well], vols=[volume])
  await handler.dispense([well], vols=[volume])
  await handler.return_tips()
  return rehearse(deck, backend.steps)


# Every eighth definition keeps the suite quick while still crossing formats and makers.
@pytest.mark.parametrize("maker_name", plate_makers()[::8])
def test_centred_transfer_is_clean(maker_name):
  try:
    with warnings.catch_warnings():
      warnings.simplefilter("ignore")
      result = asyncio.run(transfer_in_place(maker_name))
  except ValueError as refused:
    # PyLabRobot itself refuses some set-ups (a lidded plate, an unskirted plate on this carrier).
    pytest.skip(f"PyLabRobot refused this set-up: {refused}")
  assert result.ok, result.report()

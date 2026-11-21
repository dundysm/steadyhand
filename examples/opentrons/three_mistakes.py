"""An Opentrons Flex protocol that Opentrons' own analysis accepts, with three mistakes in it.

    steadyhand rehearse examples/opentrons/three_mistakes.py

finds all three: a reagent well asked for more than it holds, a plate well filled past its rim,
and a volume below what the pipette is specified to move.
"""

from opentrons import protocol_api

metadata = {"protocolName": "Three mistakes Opentrons' analysis lets through"}
requirements = {"robotType": "Flex", "apiLevel": "2.19"}


def run(protocol: protocol_api.ProtocolContext):
    protocol.load_trash_bin("A3")
    tips = protocol.load_labware("opentrons_flex_96_tiprack_200ul", "C1")
    plate = protocol.load_labware("corning_96_wellplate_360ul_flat", "D1", "assay plate")
    trough = protocol.load_labware("nest_12_reservoir_15ml", "D2", "reagents")
    pipette = protocol.load_instrument("flex_1channel_1000", "left", tip_racks=[tips])

    buffer = protocol.define_liquid("buffer", "wash buffer", "#4477aa")
    trough["A1"].load_liquid(buffer, 500)  # 500 uL, where the six transfers below need 600

    # 1. The sixth transfer finds the well empty, and the fifth draws with the tip above what is left.
    pipette.transfer(100, trough["A1"], [plate[w] for w in ("A1", "A2", "A3", "A4", "A5", "A6")], new_tip="once")

    # 2. Four more 100 uL into a well that holds 360 uL and already has 100 in it.
    pipette.pick_up_tip()
    for _ in range(4):
        pipette.aspirate(100, trough["A2"])  # no liquid is declared for A2: steadyhand says how much it needs
        pipette.dispense(100, plate["A1"])

    # 3. 2 uL with a pipette specified for 5 uL and up.
    pipette.aspirate(2, plate["A1"])
    pipette.dispense(2, plate["B1"])
    pipette.drop_tip()

'''
When communicating with a UIM342 motor directly over CAN, the protocol used is
called SimpleCAN3.0. This file implements that protocol.

It differs slightly from the TCP-based protocol. For example, there is no
checksum or start-/end-of-message byte. Some fields are packed into existing
CAN message fields.
'''

import dataclasses


@dataclasses.dataclass
class SimpleCANIdentifier:
    '''
    The SimpleCAN3.0 protocol packs fields into the message's Arbitration ID
    according to the following scheme. (A color-coded diagram is also available
    in the UIM342 manual.)

                          Producer ID          Control
                       low bits  high bits      Word
                        ,-'         ,-'           '-,
                        v           v               v
                      ppppp ccccc 0 PP CC 000000 wwwwwwww
                              ^        ^
                            ,-'      ,-'
                        low bits  high bits
                           Consumer ID

    The Arbitration ID itself is split across two fields of the CAN message, the
    Standard Identifier (SID; 11 bits) and Extended Identifier (EID; 18 bits).

                          Standard       Extended
                         Identifier     Identifier
                           ,-'            ,-'
                           v              v
                      sssssssssss eeeeeeeeeeeeeeeeee
                      pppppccccc0 PPCC000000wwwwwwww

    Because Python supports arbitrary-precision integers, we can pack and unpack
    the Arbitration ID directly.
    '''

    producer_id: int
    consumer_id: int
    control_word: int

    @property
    def arbitration_id(self) -> int:
        p_lo = self.producer_id & 0x1F
        p_hi = (self.producer_id >> 5) & 0x03
        c_lo = self.consumer_id & 0x1F
        c_hi = (self.consumer_id >> 5) & 0x03

        return (
            (p_lo << 24) | (c_lo << 19) |
            (p_hi << 16) | (c_hi << 14) |
            (self.control_word & 0xFF)
        )

    @classmethod
    def from_arbitration_id(cls, aid: int) -> 'SimpleCANIdentifier':
        p_lo = (aid >> 24) & 0x1F
        p_hi = (aid >> 16) & 0x03
        c_lo = (aid >> 19) & 0x1F
        c_hi = (aid >> 14) & 0x03

        return SimpleCANIdentifier(
            producer_id=(p_hi << 5) | p_lo,
            consumer_id=(c_hi << 5) | c_lo,
            control_word=aid & 0xFF
        )

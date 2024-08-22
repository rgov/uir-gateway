'''
Ths file implements the UIMessage protocol used by the UIROBOT CAN gateways. The
gateway speaks UIMessage on the USB/serial/Ethernet side and SimpleCAN3.0 on the
CAN side.
'''

import dataclasses
import struct


PACKET_FORMAT = '<BBBB8sBHB'
PACKET_LENGTH = struct.calcsize(PACKET_FORMAT)
assert PACKET_LENGTH == 16  # "The length of a UIMessage is fixed to 16 bytes."


def crc16(data: bytes, poly: int = 0xA001) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ poly if (crc & 1) else crc >> 1
    return crc


@dataclasses.dataclass
class UIMessage:
    device_id: int
    function_code: int
    data: bytes
    need_checksum: bool = True
    need_ack: bool = False
    aux_byte: int = 0x00
    checksum: int = 0x0000

    def serialize(self) -> bytes:
        def pack(checksum: int) -> bytes:
            return struct.pack(
                PACKET_FORMAT,
                0xAA if self.need_checksum else 0xAD,
                self.device_id,
                (int(self.need_ack) << 7) | int(self.function_code),
                len(self.data),
                self.data,
                self.aux_byte,
                checksum,
                0xCC
            )

        out = pack(self.checksum)

        if self.need_checksum:
            out = pack(crc16(out[1:-3]))

        return out

    @staticmethod
    def deserialize(packet: bytes) -> 'UIMessage':
        (
            start_of_message,
            device_id,
            control_word,
            data_length,
            data,
            aux_byte,
            checksum,
            end_of_message
        ) = struct.unpack(PACKET_FORMAT, packet)

        assert start_of_message in (0xAA, 0xAC, 0xAD)  # TODO: What is 0xAC?
        assert end_of_message == 0xCC

        assert 0 <= data_length <= 8
        data = data[:data_length]

        need_checksum = (start_of_message == 0xAA)
        need_ack = bool(control_word & 0x80)

        # Note: We don't convert this to a FunctionCode enum because it might
        # not be a member of the subset we have defined.
        function_code = control_word & 0x7F

        return UIMessage(
            device_id,
            function_code,
            data,
            need_checksum,
            need_ack,
            aux_byte,
            checksum
        )

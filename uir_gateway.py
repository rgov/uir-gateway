import enum
import select
import socket
import struct

from dataclasses import dataclass


PACKET_FORMAT = '<BBBB8sBHB'
PACKET_LENGTH = struct.calcsize(PACKET_FORMAT)
assert PACKET_LENGTH == 16  # "The length of a UIMessage is fixed to 16 bytes."


# Function codes (modulo ACK bit)
class FunctionCode(enum.IntEnum):
    PROTOCOL_PARAMETER = 0x01
    MODEL = 0x0B
    SERIAL_NUMBER = 0x0C
    ERROR_REPORT = 0x0F
    SYSTEM_OPERATION = 0x7E

    # Undocumented but sent by StepEva-3. The data is `0A00`.
    WAKE_NODE = 0x06


# Gateway device model numbers
ML_UIM2513 = [0x19, 0x0D]
ML_UIM2522 = [0x19, 0x16]
ML_UIM2523 = [0x19, 0x17]
ML_MMC90X  = [0x5A, 0x00]  # MMC901S, MMC901M, MMC902S, etc. - set second digit

# Gateway default node ID (<= 4)
class GatewayNodeID(enum.IntEnum):
    UIM2513 = 3
    UIM2523 = 2

# Protocol parameter indices
class ProtocolParameter(enum.IntEnum):
    RS232_BAUD = 1
    CAN_BITRATE = 5
    NODE_ID = 7

# System operation subcommands
class SystemOperation(enum.IntEnum):
    REBOOT = 1
    RESTORE_FACTORY_DEFAULTS = 2

    # Undocumented. Second data byte is on/off.
    SYNC_TIME = 4

    # XXX
    # There is an undocumented SystemOperation message that is sent by
    # SdkStartCanNet(UseConstLink=1). This described as "Debug Mode" in the
    # manual. The message is sent to device ID 0xFF with a data length of 0.

# RS-232 baud
class RS232Baud(enum.IntEnum):
    BAUD_4800 = 0
    BAUD_9600 = 1
    BAUD_19200 = 2
    BAUD_38400 = 3
    BAUD_57600 = 4
    BAUD_115200 = 5

# CAN bitrates
class CANBitrate(enum.IntEnum):
    KBPS_1000 = 0
    KBPS_800 = 1
    KBPS_500 = 2
    KBPS_250 = 3
    KBPS_125 = 4


gateway_node_id = GatewayNodeID.UIM2523
can_bitrate = CANBitrate.KBPS_500
serial_number = 1234512345
manufacturer_id = 0x4141
vendor_id = 0x4242


@dataclass
class Packet:
    device_id: int
    function_code: int | FunctionCode
    data_length: int
    data: bytes
    need_checksum: bool = True
    need_ack: bool = False
    aux_byte: int = 0x00
    checksum: int = 0x0000

    def serialize(self, checksum=None) -> bytes:
        out = struct.pack(
            PACKET_FORMAT,
            0xAA if self.need_checksum else 0xAD,
            self.device_id,
            (int(self.need_ack) << 7) | int(self.function_code),
            self.data_length,
            self.data,
            self.aux_byte,
            checksum if checksum is not None else 0xFFFF,
            0xCC
        )

        if checksum is None and packet.need_checksum:
            checksum = crc16(out[1:-3])
            return self.serialize(checksum)

        return out

    @staticmethod
    def deserialize(buffer: bytes) -> 'Packet':
        (
            start_of_message,
            device_id,
            control_word,
            data_length,
            data,
            aux_byte,
            checksum,
            end_of_message
        ) = struct.unpack(PACKET_FORMAT, buffer)

        assert start_of_message in (0xAA, 0xAC, 0xAD)  # TODO: What is 0xAC?
        assert end_of_message == 0xCC

        need_checksum = (start_of_message == 0xAA)
        need_ack = bool(control_word & 0x80)

        # Note: We don't convert this to a FunctionCode enum because it might
        # not be a member of the subset we have defined.
        function_code = control_word & 0x7F

        return Packet(
            device_id,
            function_code,
            data_length,
            data,
            need_checksum,
            need_ack,
            aux_byte,
            checksum
        )


def crc16(data: bytes, poly: int = 0xA001):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ poly if (crc & 1) else crc >> 1
    return crc


server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(('0.0.0.0', 8888))
server.listen()
clients = []

print("[*] Listening on port 8888...")

def write_packet(s, p):
    serialized = p.serialize()
    print(f'[*] Sending {p} => {serialized.hex()}')
    s.send(serialized)


while True:
    readable, _, _ = select.select([server] + clients, [], [])
    for s in readable:
        if s is server:
            client, addr = s.accept()
            clients.append(client)
            print(f"[*] Connection from {addr}")
            continue

        data = s.recv(PACKET_LENGTH)
        if not data:  # TODO: Handle partial packets
            print("[*] Connection closed")
            s.close()
            clients.remove(s)
            continue

        packet = Packet.deserialize(data)
        print(f"[*] Received packet: {packet} => {data.hex()}")

        if packet.need_checksum and crc16(data[1:-3]) != packet.checksum:
            print(f"[-] Packet has invalid checksum, ignoring")
            continue

        if packet.device_id not in (0, gateway_node_id):
            print(f'[*] Ignoring packet not addressed to us')
            continue

        if packet.function_code == FunctionCode.MODEL:
            print('[*] Responding to GET MODEL command')
            assert packet.need_ack
            write_packet(s, Packet(
                device_id = gateway_node_id,
                function_code = FunctionCode.MODEL,
                data_length = 8,
                data = bytes(
                    ML_UIM2523 + [0x00, 0x00, 0x69, 0x7A, 0x00, 0x00]
                )
            ))

        if packet.function_code == FunctionCode.PROTOCOL_PARAMETER:
            index = packet.data[0]
            if index == ProtocolParameter.CAN_BITRATE:
                if packet.data_length == 1:
                    print('[*] Responding to GET CAN BITRATE command')
                elif packet.data_length == 2:
                    _, bitrate, = struct.unpack_from('<BB', packet.data)
                    print('[*] Set bitrate to', bitrate)  # TODO: user friendly

                    print('[*] Acknowledging SET CAN BITRATE command')
                else:
                    print('[-] Invalid length on PP command, ignoring')
                    continue

                write_packet(s, Packet(
                    device_id = gateway_node_id,
                    function_code = FunctionCode.PROTOCOL_PARAMETER,
                    data_length = 2,
                    data = bytes([
                        ProtocolParameter.CAN_BITRATE, can_bitrate,
                        0x00, 0x00, 0x00, 0x00, 0x00, 0x00
                    ])
                ))
            else:
                raise NotImplementedError(f'Protocol parameter {index} not implemented')


        if packet.function_code == FunctionCode.SERIAL_NUMBER:
            if packet.need_ack:
                print('[*] Responding to GET SERIAL NUMBER command')
            else:
                assert packet.data_length == struct.calcsize('<L')
                serial_number, = struct.unpack_from('<L', packet.data)
                print('[*] Set serial number to', serial_number)

                # Not documented, but I think we should acknowledge
                print('[*] Acknowledging SET SERIAL NUMBER command')

            write_packet(s, Packet(
                device_id = gateway_node_id,
                function_code = FunctionCode.SERIAL_NUMBER,
                data_length = 8,
                data = struct.pack('<LHH', serial_number, manufacturer_id,
                                    vendor_id)
            ))

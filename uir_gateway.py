import select
import socket
import struct

from dataclasses import dataclass


PACKET_FORMAT = '<BBBB8sBHB'
PACKET_LENGTH = struct.calcsize(PACKET_FORMAT)
assert PACKET_LENGTH == 16  # "The length of a UIMessage is fixed to 16 bytes."

# Function codes (modulo ACK bit)
FC_PROTOCOL_PARAMETER = 0x01
FC_WAKE_NODE = 0x06  # Undocumented. Like `0A00`, sent to specified node
FC_MODEL = 0x0B
FC_SERIAL_NUMBER = 0x0C
FC_ERROR_REPORT = 0x0F
FC_SYSTEM_OPERATION = 0x7E

# Gateway device model numbers
ML_UIM2513 = [0x19, 0x0D]
ML_UIM2522 = [0x19, 0x16]
ML_UIM2523 = [0x19, 0x17]
ML_MMC90X  = [0x5A, 0x00]  # MMC901S, MMC901M, MMC902S, etc. - set second digit

# Gateway default node ID (<= 4)
ID_UIM2513 = 3
ID_UIM2523 = 2

# Protocol parameter indices
PP_RS232_BAUD = 1
PP_CAN_BITRATE = 5
PP_NODE_ID = 7

# System operation subcommands
SY_REBOOT = 1
SY_RESTORE_FACTORY_DEFAULTS = 2
SY_SYNC_TIME = 4  # Undocumented. Second byte is on/off.

# RS-232 baud
RB_4800 = 0
RB_9600 = 1
RB_19200 = 2
RB_38400 = 3
RB_57600 = 4
RB_115200 = 5

# CAN bitrates
CR_1000K = 0
CR_800K = 1
CR_500K = 2
CR_250K = 3
CR_125K = 4


gateway_node_id = ID_UIM2523
can_bitrate = CR_500K
serial_number = 1234512345
manufacturer_id = 0x4141
vendor_id = 0x4242


@dataclass
class Packet:
    need_checksum: bool
    device_id: int
    need_ack: bool
    function_code: int
    data_length: int
    data: bytes
    aux_byte: int
    checksum: int

def crc16(data: bytes, poly: int = 0xA001):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ poly if (crc & 1) else crc >> 1
    return crc

def parse_packet(packet_bytes: bytes):
    (
        start_of_message,
        device_id,
        control_word,
        data_length,
        data,
        aux_byte,
        checksum,
        end_of_message
    ) = struct.unpack(PACKET_FORMAT, packet_bytes)

    assert start_of_message in (0xAA, 0xAC, 0xAD)  # TODO: What is 0xAC?
    assert end_of_message == 0xCC

    need_checksum = (start_of_message == 0xAA)
    need_ack = bool(control_word & 0x80)
    function_code = control_word & 0x7F

    return Packet(
        need_checksum,
        device_id,
        need_ack,
        function_code,
        data_length,
        data,
        aux_byte,
        checksum
    )


def serialize_packet(packet: Packet, checksum=None):
    serialized = struct.pack(
        PACKET_FORMAT,
        0xAA if packet.need_checksum else 0xAD,
        packet.device_id,
        (int(packet.need_ack) << 7) | packet.function_code,
        packet.data_length,
        packet.data,
        packet.aux_byte,
        checksum if checksum is not None else 0xFF,
        0xCC
    )

    if checksum is None and packet.need_checksum:
        checksum = crc16(serialized[1:-3])
        return serialize_packet(packet, checksum)

    return serialized


server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(('0.0.0.0', 8888))
server.listen()
clients = []

print("[*] Listening on port 8888...")

def write_packet(s, p):
    serialized = serialize_packet(p)
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

        packet = parse_packet(data)
        print(f"[*] Received packet: {packet} => {data.hex()}")

        if packet.need_checksum and crc16(data[1:-3]) != packet.checksum:
            print(f"[-] Packet has invalid checksum, ignoring")
            continue

        if packet.device_id not in (0, gateway_node_id):
            print(f'[*] Ignoring packet not addressed to us')
            continue

        if packet.function_code == FC_MODEL:
            print('[*] Responding to GET MODEL command')
            assert packet.need_ack
            write_packet(s, Packet(
                need_checksum = True,
                device_id = gateway_node_id,
                need_ack = False,
                function_code = FC_MODEL,
                data_length = 8,
                data = bytes(
                    ML_UIM2523 + [0x00, 0x00, 0x69, 0x7A, 0x00, 0x00]
                ),
                aux_byte = 0x00,
                checksum = 0xFF
            ))

        if packet.function_code == FC_PROTOCOL_PARAMETER:
            index = packet.data[0]
            if index == PP_CAN_BITRATE:
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
                    need_checksum = True,
                    device_id = gateway_node_id,
                    need_ack = False,
                    function_code = FC_MODEL,
                    data_length = 2,
                    data = bytes([
                        PP_CAN_BITRATE, can_bitrate,
                        0x00, 0x00, 0x00, 0x00, 0x00, 0x00
                    ]),
                    aux_byte = 0x00,
                    checksum = 0xFF
                ))
            else:
                raise NotImplementedError(f'Protocol parameter {index} not implemented')


        if packet.function_code == FC_SERIAL_NUMBER:
            if packet.need_ack:
                print('[*] Responding to GET SERIAL NUMBER command')
            else:
                assert packet.data_length == struct.calcsize('<L')
                serial_number, = struct.unpack_from('<L', packet.data)
                print('[*] Set serial number to', serial_number)

                # Not documented, but I think we should acknowledge
                print('[*] Acknowledging SET SERIAL NUMBER command')

            write_packet(s, Packet(
                need_checksum = True,
                device_id = gateway_node_id,
                need_ack = False,
                function_code = FC_SERIAL_NUMBER,
                data_length = 8,
                data = struct.pack('<LHH', serial_number, manufacturer_id,
                                    vendor_id),
                aux_byte = 0x00,
                checksum = 0xFF
            ))


        if packet.function_code == FC_SYSTEM_OPERATION:
            # XXX
            # There is an undocumented SY packet where device_id = 0xFF and
            # data_length = 0 when UseConstLink=1 via the API. This is described
            # as "Debug Mode".

            pass
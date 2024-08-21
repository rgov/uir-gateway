import dataclasses
import enum
import select
import socket
import struct


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
class GatewayModel(bytes, enum.Enum):
    UIM2513 = [0x19, 0x0D]
    UIM2522 = [0x19, 0x16]
    UIM2523 = [0x19, 0x17]
    MMC90X  = [0x5A, 0x00]  # MMC901S, MMC901M, MMC902S, etc. - set second digit

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


@dataclasses.dataclass
class UIMessage:
    device_id: int
    function_code: int
    data_length: int
    data: bytes
    need_checksum: bool = True
    need_ack: bool = False
    aux_byte: int = 0x00
    checksum: int = 0x0000

    def serialize(self, checksum: int | None = None) -> bytes:
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

        if checksum is None and self.need_checksum:
            checksum = crc16(out[1:-3])
            return self.serialize(checksum)

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

        need_checksum = (start_of_message == 0xAA)
        need_ack = bool(control_word & 0x80)

        # Note: We don't convert this to a FunctionCode enum because it might
        # not be a member of the subset we have defined.
        function_code = control_word & 0x7F

        return UIMessage(
            device_id,
            function_code,
            data_length,
            data,
            need_checksum,
            need_ack,
            aux_byte,
            checksum
        )


def crc16(data: bytes, poly: int = 0xA001) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ poly if (crc & 1) else crc >> 1
    return crc


def send_message(s: socket.socket, msg: UIMessage) -> None:
    serialized = msg.serialize()
    print(f'[*] Sending {msg} => {serialized.hex()}')
    s.send(serialized)


@dataclasses.dataclass
class UIDevice:
    node_id: int
    group_ids: list[int] = dataclasses.field(default_factory=list)
    can_bitrate: int = CANBitrate.KBPS_500
    serial_number: int = 1234512345
    manufacturer_id: int = 0x4141
    vendor_id: int = 0x4242

    def __post_init__(self) -> None:
        if not self.group_ids:
            self.group_ids = [0, self.node_id]

    def handle_message(self, transport: socket.socket, msg: UIMessage) -> None:
        if msg.device_id not in self.group_ids:
            print(f'[*] Ignoring message not addressed to us')
            return

        if msg.function_code == FunctionCode.MODEL:
            print('[*] Responding to GET MODEL command')
            assert msg.need_ack
            send_message(transport, UIMessage(
                device_id = self.node_id,
                function_code = FunctionCode.MODEL,
                data_length = 8,
                data = (GatewayModel.UIM2523 + bytes([
                    0x00, 0x00,  # reserved
                    0x69, 0x7A,  # firmware version
                    0x00, 0x00,  # reserved
                ]))
            ))

        if msg.function_code == FunctionCode.PROTOCOL_PARAMETER:
            index = msg.data[0]
            if index == ProtocolParameter.CAN_BITRATE:
                if msg.data_length == 1:
                    print('[*] Responding to GET CAN BITRATE command')
                elif msg.data_length == 2:
                    _, bitrate, = struct.unpack_from('<BB', msg.data)
                    print('[*] Set bitrate to', bitrate)  # TODO: user friendly

                    print('[*] Acknowledging SET CAN BITRATE command')
                else:
                    print('[-] Invalid length on PP command, ignoring')
                    return

                send_message(transport, UIMessage(
                    device_id = self.node_id,
                    function_code = FunctionCode.PROTOCOL_PARAMETER,
                    data_length = 2,
                    data = bytes([
                        ProtocolParameter.CAN_BITRATE, self.can_bitrate,
                        0x00, 0x00, 0x00, 0x00, 0x00, 0x00
                    ])
                ))
            else:
                raise NotImplementedError(f'Protocol parameter {index} not implemented')

        if msg.function_code == FunctionCode.SERIAL_NUMBER:
            if msg.need_ack:
                print('[*] Responding to GET SERIAL NUMBER command')
            else:
                assert msg.data_length == struct.calcsize('<L')
                serial_number, = struct.unpack_from('<L', msg.data)
                print('[*] Set serial number to', serial_number)

                # Not documented, but I think we should acknowledge
                print('[*] Acknowledging SET SERIAL NUMBER command')

            send_message(transport, UIMessage(
                device_id = self.node_id,
                function_code = FunctionCode.SERIAL_NUMBER,
                data_length = 8,
                data = struct.pack(
                    '<LHH',
                    self.serial_number,
                    self.manufacturer_id,
                    self.vendor_id
                )
            ))


def main() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', 8888))
    server.listen()
    clients: list[socket.socket] = []

    devices: list[UIDevice] = [
        UIDevice(
            node_id = GatewayNodeID.UIM2523
        ),
    ]

    print('[*] Listening on port 8888...')


    while True:
        readable, _, _ = select.select([server] + clients, [], [])
        for s in readable:
            if s is server:
                client, addr = s.accept()
                clients.append(client)
                print(f'[*] Connection from {addr}')
                continue

            packet = s.recv(PACKET_LENGTH)
            if not packet:  # TODO: Handle partial packets
                print('[*] Connection closed')
                s.close()
                clients.remove(s)
                continue

            msg = UIMessage.deserialize(packet)
            print(f'[*] Received message: {msg} => {packet.hex()}')

            if msg.need_checksum and crc16(packet[1:-3]) != msg.checksum:
                print(f'[-] Message has invalid checksum, ignoring')
                continue

            for device in devices:
                device.handle_message(s, msg)


if __name__ == '__main__':
    main()

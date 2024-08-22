#!/usr/bin/env python
import asyncio
import dataclasses
import typing

import can

from . import crc16, GatewayNodeID, UIDevice, UIMessage


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
        c_lo = (aid >> 19) & 0x1F
        p_hi = (aid >> 16) & 0x03
        c_hi = (aid >> 14) & 0x03

        return SimpleCANIdentifier(
            producer_id=(p_hi << 5) | p_lo,
            consumer_id=(c_hi << 5) | c_lo,
            control_word=aid & 0xFF
        )


# All CAN messages sent from the "user master controller" are to use ID = 4,
# according to the manual.
MASTER_PRODUCER_ID = 4



gateway = UIDevice(
    node_id = GatewayNodeID.UIM2523
)

can_bus = can.Bus()

tcp_sinks: list[typing.BinaryIO] = []


class Socketlike:
    def __init__(self, f: typing.BinaryIO):
        self.f = f

    def send(self, data: bytes) -> None:
        self.f.write(data)
        if hasattr(self.f, 'flush'):
            self.f.flush()

    def recv(self, length: int = -1) -> bytes:
        return self.f.read(length)


def on_can_message(msg: can.Message) -> None:
    # Extract fields from the arbitration ID
    msg_id = SimpleCANIdentifier.from_arbitration_id(msg.arbitration_id)

    # Extract the control word and function code
    need_ack = bool(msg_id.control_word & 0x80)
    function_code = msg_id.control_word & 0x7F

    # Extract the data
    assert 0 <= msg.dlc <= 8
    data = msg.data[:msg.dlc]

    # Reconstitute as a UIMessage
    tcp_msg = UIMessage(
        device_id=msg_id.producer_id,
        function_code=function_code,
        data=data,
        need_ack=need_ack
    )

    print(f'[*] Received a CAN message: {tcp_msg}')

    # Forward the message to all of the TCP sinks
    for sink in tcp_sinks:
        sink.write(tcp_msg.serialize())


async def tcp_server(reader, writer):
    tcp_sinks.append(writer)

    try:
        while True:
            packet = await reader.read(16)
            if not packet:
                break

            print(f'[*] Received a TCP packet: {packet.hex()}')

            # Ask the virtual device to handle
            msg = UIMessage.deserialize(packet)
            print(f'[*] Received message: {msg} => {packet.hex()}')

            if msg.need_checksum and crc16(packet[1:-3]) != msg.checksum:
                print('[-] Message has invalid checksum, ignoring')
                continue

            # TODO: Use a transport that fans the message out to everyone
            gateway.handle_message(Socketlike(writer), msg)

            # Compute the SID and EID components of the arbitration ID according
            # to UIM342 scheme, see manual section "Direct CAN Communication".
            msg_id = SimpleCANIdentifier(
                producer_id=MASTER_PRODUCER_ID,
                consumer_id=msg.device_id,
                control_word=(int(msg.need_ack) << 7) | msg.function_code
            )
            
            # Forward the message to the CAN bus
            can_bus.send(can.Message(
                is_extended_id=True,
                arbitration_id=msg_id.arbitration_id,
                dlc=len(msg.data),
                data=msg.data
            ))

    finally:
        tcp_sinks.remove(writer)
        writer.close()
        await writer.wait_closed()


async def main() -> None:
    server = await asyncio.start_server(tcp_server, '0.0.0.0', 8888)

    # Create Notifier with an explicit loop to use for scheduling of callbacks
    notifier = can.Notifier(
        can_bus,
        listeners=[on_can_message],
        loop=asyncio.get_running_loop()
    )

    try:
        await server.serve_forever()
    except asyncio.CancelledError:
        pass
    finally:
        notifier.stop()
        can_bus.shutdown()


def sync_main():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    sync_main()

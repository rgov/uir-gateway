#!/usr/bin/env python
import asyncio
import functools
import typing

import can

from . import crc16, GatewayNodeID, UIDevice, UIMessage


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
    # Split the arbitration ID into SID and EID
    eid = msg.arbitration_id & ((1<<18)-1)
    sid = msg.arbitration_id >> 18

    # Extract the sender's node ID. Note! The UIM342 manual has an invalid
    # formula for this.
    sender_id = ((eid >> 11) & 0x0060) | ((sid >> 6) & 0x001F)

    # Extract the control word and function code
    control_word = eid & 0xFF
    need_ack = bool(control_word & 0x80)
    function_code = control_word & 0x7F

    # Extract the data
    assert 0 <= msg.dlc <= 8
    data = msg.data[:msg.dlc]

    # Reconstitute as a UIMessage
    tcp_msg = UIMessage(
        device_id=sender_id,
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
            sid = ((msg.device_id << 1) & 0x003F)
            eid = (((msg.device_id << 1) & 0x00C0) << 8)
            eid |= int(msg.need_ack) << 7
            eid |= msg.function_code
            
            # Forward the message to the CAN bus
            can_bus.send(can.Message(
                is_extended_id=True,
                arbitration_id=(sid << 18) | eid,
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

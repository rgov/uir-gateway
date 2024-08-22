#!/usr/bin/env python
import asyncio
import os
import typing

import can

from ..constants import ReservedNodeIDs
from ..device import SimUIGateway
from ..simplecan import SimpleCANIdentifier
from ..uimessage import UIMessage

# FIXME: Move message validation to UIMessage deserialize()
from ..uimessage import crc16


if os.environ.get('CAN_INTERFACE') is None:
    print('Please set python-can environment variables (CAN_INTERFACE, etc.).')
    print()
    print('https://python-can.readthedocs.io/en/stable/'
          'configuration.html#environment-variables')
    quit(1)


gateway = SimUIGateway(node_id=ReservedNodeIDs.UIM2523)

can_bus = can.Bus()

tcp_sinks: list[typing.BinaryIO] = []


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


async def tcp_server(reader, writer) -> None:
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
            gateway.handle_message(writer, msg)

            # Compute the SID and EID components of the arbitration ID according
            # to UIM342 scheme, see manual section "Direct CAN Communication".
            msg_id = SimpleCANIdentifier(
                producer_id=gateway.node_id,
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


def sync_main() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    sync_main()

'''
This file implements a minimal

'''
import struct
import typing

from .constants import (
    CANBitrate,
    FunctionCode,
    GatewayModel,
    ProtocolParameter,
    ReservedGroupIDs
)
from .uimessage import UIMessage


# Type definitions
class SupportsSend(typing.Protocol):
    def send(self, data: bytes) -> int:
        return -1

class SupportsWrite(typing.Protocol):
    def write(self, data: bytes) -> int:
        return -1

Transport: typing.TypeAlias = SupportsSend | SupportsWrite


class SimUIGateway:
    def __init__(
            self,
            node_id: int,
            group_id: int | None = None,
            can_bitrate: int = CANBitrate.KBPS_500,
            serial_number: int = 1234512345,
            manufacturer_id: int = 0x4141,
            vendor_id: int = 0x4242
    ):
        self.node_id = node_id
        self.group_id = group_id if group_id is not None else node_id

        self.can_bitrate = can_bitrate
        self.serial_number, self.manufacturer_id, self.vendor_id = \
            serial_number, manufacturer_id, vendor_id

    def send_message(self, transport: Transport, msg: UIMessage) -> None:
        # Use whichever the transport supports, .send() or .write()
        if hasattr(transport, 'send'):
            transport.send(msg.serialize())
        else:
            transport.write(msg.serialize())
            if hasattr(transport, 'flush'):
                transport.flush()

    def handle_message(self, transport: Transport, msg: UIMessage) -> None:
        # Ignore messages not addressed to us
        if msg.device_id not in (
            ReservedGroupIDs.GLOBAL,
            self.node_id,
            self.group_id
        ):
            return

        if msg.function_code == FunctionCode.MODEL:
            if msg.need_ack:
                self.handle_get_model(transport, msg)
                return

        if msg.function_code == FunctionCode.SERIAL_NUMBER:
            if msg.need_ack:
                self.handle_get_serial_number(transport, msg)
                return
            else:
                # There is technically a set serial number command that receives
                # includes a 4 byte value (excluding manufacturer and vendor).
                #
                # It is unclear whether the recipient needs to echo it back in
                # acknowledgement.
                pass

        if msg.function_code == FunctionCode.PROTOCOL_PARAMETER:
            self.handle_protocol_parameter(transport, msg)
            return

        # Unimplemented function code
        pass


    def handle_get_model(self, transport: Transport, msg: UIMessage) -> None:
        print('[*] Responding to GET MODEL command')
        self.send_message(transport, UIMessage(
            device_id = self.node_id,
            function_code = FunctionCode.MODEL,
            data = (GatewayModel.UIM2523 + bytes([
                0x00, 0x00,  # reserved
                0x69, 0x7A,  # firmware version
                0x00, 0x00,  # reserved
            ]))
        ))

    def handle_get_serial_number(self, transport: Transport,
                                 msg: UIMessage) -> None:
        print('[*] Responding to GET SERIAL NUMBER command')
        self.send_message(transport, UIMessage(
            device_id = self.node_id,
            function_code = FunctionCode.SERIAL_NUMBER,
            data = struct.pack(
                '<LHH',
                self.serial_number,
                self.manufacturer_id,
                self.vendor_id
            )
        ))

    def handle_protocol_parameter(self, transport: Transport,
                                  msg: UIMessage) -> None:
        param, value = msg.data[0], msg.data[1:]
        is_write = (len(msg.data) > 1)

        if param == ProtocolParameter.CAN_BITRATE:
            if is_write:
                self.can_bitrate, = struct.unpack_from('<B', value)
                print('[*] Set bitrate to', CANBitrate(self.can_bitrate).name)

            # For either a read or write, send the current value
            self.send_message(transport, UIMessage(
                device_id = self.node_id,
                function_code = FunctionCode.PROTOCOL_PARAMETER,
                data = struct.pack(
                    '<BB',
                    ProtocolParameter.CAN_BITRATE,
                    self.can_bitrate
                )
            ))
            return

        # Unimplemented protocol parameter
        pass

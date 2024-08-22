'''
This file defines several constants used by UIM342 motors and UIROBOT CAN
gateway devices (e.g., UIM2513 and UIM2523).

For the most complete list of constants, refer to the uirSDKgen3.h header file.
'''

import enum


# Function codes (modulo ACK bit)
class FunctionCode(enum.IntEnum):
    PROTOCOL_PARAMETER = 0x01
    WAKE_NODE = 0x06
    MODEL = 0x0B
    SERIAL_NUMBER = 0x0C
    ERROR_REPORT = 0x0F
    SYSTEM_OPERATION = 0x7E


# Gateway device model numbers
class GatewayModel(bytes, enum.Enum):
    UIM2513 = [0x19, 0x0D]
    UIM2522 = [0x19, 0x16]
    UIM2523 = [0x19, 0x17]
    MMC90X  = [0x5A, 0x00]  # MMC901S, MMC901M, MMC902S, etc. - set second digit


# Reserved node IDs (<= 4) for special devices like gateways
class ReservedNodeIDs(enum.IntEnum):
    # The UIM342 manual calls this the "user master controller". I assume this
    # is for whatever computer/microcontroller is directly talking CAN.
    MASTER = 4

    # Gateway devices. These are documented in their respective manuals.
    UIM2523 = 2
    UIM2513 = 3


# Reserved group IDs
class ReservedGroupIDs(enum.IntEnum):
    GLOBAL = 0


# Protocol parameter indices
class ProtocolParameter(enum.IntEnum):
    RS232_BAUD = 1
    CAN_BITRATE = 5
    NODE_ID = 7


# System operation subcommands
class SystemOperation(enum.IntEnum):
    REBOOT = 1
    RESTORE_FACTORY_DEFAULTS = 2
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

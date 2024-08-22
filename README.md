# Network Bridge for UIROBOT Stepper Motors

> [!CAUTION]
> This is a *work in progress* which is currently paused.


This Python package partially implements the protocols for communicating with [UIROBOT][] UIM342 motors and CAN gateways.

  [UIROBOT]: https://www.uirobot.com/


## Gateway Emulator

The included `uir-gateway` tool emulates a [UIM2523][] TCP-CAN bus gateway for communicating with UIM342 Servo Stepper Motors using any interface supported by [python-can][], such as the [CANable][] USB adapter.

First, install the `uir` package to a virtual environment. Set the [python-can configuration environment variables][python-can-env], then run the `uir-gateway` tool.

    export CAN_INTERFACE=slcan
    export CAN_CHANNEL=/dev/tty.usbmodem2101
    export CAN_BITRATE=500000
    uir-gateway

  [UIM2523]: https://www.uirobot.com/?products_17/42.html
  [python-can]: https://python-can.readthedocs.io/
  [python-can-env]: https://python-can.readthedocs.io/en/stable/configuration.html#environment-variables
  [CANable]: https://canable.io/


## Motor Control

This script does not directly control motors, but the packet dissectors serve as blueprints for constructing such programs.

For details on message formats, refer to product manuals, and search for "SimpleCAN 3 Instruction" in the official uirSDK3.0 `uirSDKgen3.h` header. The StepEva3 program's UIMCreator feature can synthesize and dissect UIMessages.

The `src/uir/util/gateway.py` script demonstrates how to translate between UIMessage (used to communicate with a gateway) and SimpleCAN3.0 messages (used to communicate directly over CAN).

Lastly, TCP traffic capture of StepEva3 may be useful for seeing real messages sent to a motor.

from .modem import  FreeselcallRX
import sys


def rx(data):
    print(f"{data['target']}:{data['source']}:{data['snr']}")
modem = FreeselcallRX(callback=rx)

while True:
    input_data = sys.stdin.buffer.read(1024)
    if not input_data:
        break
    modem.write(input_data)
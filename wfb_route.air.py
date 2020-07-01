import argparse
import asyncio
import string
import sys
import struct
import time

# import uvloop

#from pymavlink.dialects.v20 import common

#mav = common.MAVLink(None, srcSystem=1, srcComponent=1)


class UDPProxyProtocol:

    def __init__(self, output_proto):
        self.output_proto = output_proto
        self.ra = None

    def connection_made(self, transport):
        print('Connection made', transport)
        self.transport = transport

    def datagram_received(self, data, addr):
        if addr != self.ra:
            self.ra = addr
            print("New connection:", addr)
        self.output_proto.send(data)

    def send(self, data):
        if self.ra:
           self.transport.sendto(data, self.ra) 
        elif self.transport._address:
            self.transport.sendto(data)
            # import pdb; pdb.set_trace()
        else:
            print("No RA")

    def connection_lost(self, exc):
        print("Connection lost:", self.ra, exc)

    def error_received(self, exc):
        print("Error received:", self.ra, exc)


async def main(inport, outport, listen, connect):   
    print("Starting WFB UDP router")

    # Get a reference to the event loop as we plan to use
    # low-level APIs.   
    loop = asyncio.get_running_loop()

    _, output_proto = await loop.create_datagram_endpoint(
        lambda: UDPProxyProtocol(None),
        remote_addr=('127.0.0.1', outport))

    if connect:
        _, proto = await loop.create_datagram_endpoint(
            lambda: UDPProxyProtocol(output_proto),
            remote_addr=('127.0.0.1', connect))

    elif listen:
        _, proto = await loop.create_datagram_endpoint(
            lambda: UDPProxyProtocol(output_proto),
            local_addr=('127.0.0.1', listen))
    else:
        print("connect or listen required")
        exit(1)

    _, input_proto = await loop.create_datagram_endpoint(
        lambda: UDPProxyProtocol(proto),
        local_addr=('127.0.0.1', inport))


    # asyncio.ensure_future(report(loop, gs_proto, downlink_proto, status_proto, gs_link))
    while True:
        await asyncio.sleep(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Process some integers.')

    parser.add_argument('--inport', type=int, required=True, help='WFB UDP input port')
    parser.add_argument('--outport', type=int, required=True, help='WFB UDP out port')
    parser.add_argument('--listen', type=int, default=0, help='UDP port to listen')
    parser.add_argument('--connect', type=int, default=0, help='UDP port to connect')


    args = parser.parse_args()

    # uvloop.install()
    
    main_coro = main(
        inport=args.inport,
        outport=args.outport,
        listen=args.listen,
        connect=args.connect,
    )

    asyncio.run(main_coro)

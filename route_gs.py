import asyncio

from pymavlink.dialects.v20 import common

mav = common.MAVLink(None, srcSystem=1, srcComponent=1)

class UDPUplinkProtocol:

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        # message = data.decode()
        print('Up Received %r from %s' % (len(data), addr))
        # self.transport.sendto(data, addr)


class UDPDownlinkProtocol:

    def __init__(self, gcs):
        self.gcs = gcs
        self.bytes_cnt = 0

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        self.bytes_cnt += len(data)
        self.gcs.sendto(data)



class GCSLinkProtocol:

    def __init__(self, uplink):
        self.uplink = uplink
        self.bytes_cnt = 0

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        self.bytes_cnt += len(data)
        self.uplink.sendto(data, ('127.0.0.1', 5557))

    def error_received(self, exc):
        pass


class LinkStatusProtocol:

    def __init__(self):
        self.rssi = 0

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        msg = data.decode()
        fields = msg.split(',')
        if fields[0] == 'ground':
            self.rssi = float(fields[-1])


async def report(loop, up, down, stat, gcs):
    ts = loop.time()
    while True:
        await asyncio.sleep(1)
        dt = loop.time() - ts
        ts = loop.time()
        print('---->', dt)
        print("UP:   ", up.bytes_cnt / dt)
        print("DOWN: ", down.bytes_cnt / dt)
        print("RSSI: ", stat.rssi)
        up.bytes_cnt = 0
        down.bytes_cnt = 0
        radio_rssi = 127 + 128 + int(stat.rssi)

        msg = common.MAVLink_radio_status_message(
            rssi=radio_rssi,
            remrssi=0,
            txbuf=0,
            noise=0,
            remnoise=0,
            rxerrors=0,
            fixed=0)
        data = msg.pack(mav)
        gcs.sendto(data)


async def main():
    print("Starting UDP server")

    # Get a reference to the event loop as we plan to use
    # low-level APIs.
    loop = asyncio.get_running_loop()

    uplink, _ = await loop.create_datagram_endpoint(
        lambda: UDPUplinkProtocol(),
        remote_addr=('127.0.0.1', 5557))

    gs_link, gs_proto = await loop.create_datagram_endpoint(
        lambda: GCSLinkProtocol(uplink),
        remote_addr=('192.168.4.8', 14550), local_addr=('0.0.0.0', 5999))

    _, downlink_proto = await loop.create_datagram_endpoint(
        lambda: UDPDownlinkProtocol(gs_link),
        local_addr=('127.0.0.1', 5556))

    _, status_proto = await loop.create_datagram_endpoint(
        lambda: LinkStatusProtocol(),
        local_addr=('127.0.0.1', 5800))

    asyncio.ensure_future(report(loop, gs_proto, downlink_proto, status_proto, gs_link))
    try:
        await asyncio.sleep(3600)  # Serve for 1 hour.
    finally:
        transport.close()


asyncio.run(main())

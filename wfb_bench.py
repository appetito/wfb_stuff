import argparse
import asyncio
import string
import sys
import struct
import time

"""
Run at ~ 150kB/s [ground]
python3 wfb_bench.py --inport=5556 --outport=5557 --statport=5800 --packetsize=240 --sendpause=0.0001

Run at ~ 150kB/s [air]
python3 wfb_bench.py --inport=5558 --outport=5555 --statport=5801 --packetsize=240 --sendpause=0.0001
"""


data = 30 * (string.ascii_letters + string.digits)
enc_data = data.encode()


class Stat:
    def __init__(self):
        self.packets_recv_cnt = 0
        self.bytes_recv_cnt = 0
        self.packets_send_cnt = 0
        self.bytes_send_cnt = 0
        self.lost_cnt = 0
        self.rssi = -125
        self.latency = 0

    def update(self, proto=None, **data):
        if proto:
            self.packets_recv_cnt = proto.packets_recv_cnt
            self.bytes_recv_cnt = proto.bytes_recv_cnt
            self.packets_send_cnt = proto.packets_send_cnt
            self.bytes_send_cnt = proto.bytes_send_cnt
            self.lost_cnt = proto.lost_cnt
            self.latency = proto.latency
        else:
            self.packets_recv_cnt = data['packets_recv_cnt']
            self.bytes_recv_cnt = data['bytes_recv_cnt']
            self.packets_send_cnt = data['packets_send_cnt']
            self.bytes_send_cnt = data['bytes_send_cnt']
            self.lost_cnt = data['lost_cnt']
            self.rssi = data['rssi']
            self.latency = data['latency']


class BaseProtocol:

    transport = None

    def __init__(self, other=None):
        self.other = other
        self.packets_recv_cnt = 0
        self.bytes_recv_cnt = 0
        self.packets_send_cnt = 0
        self.bytes_send_cnt = 0
        self.lost_cnt = 0
        self.packet_no = 0
        self.ping_no = 0
        self.latency = 0
        self.recv_packet_no = 0
        self.remote_addr = None
        self.stat = Stat()
        self.remote_stat = Stat()
        self.local_stat = Stat()

    def connection_made(self, transport):
        self.transport = transport

    def error_received(self, exc):
        pass

    def send(self, payload, to_addr=None):
        if not self.transport:
            raise RuntimeError('Cant send, no transport')
        data = struct.pack('I', self.packet_no) + payload
        if to_addr:
            self.transport.sendto(data, to_addr)
        else:
            self.transport.sendto(data)
        self.packet_no += 1
        self.packets_send_cnt += 1
        self.bytes_send_cnt += len(data)

    def send_local_stat(self):
        # print('Lat', self.local_stat.latency, self.local_stat.rssi)
        payload = struct.pack('LLLLLQi',
            self.local_stat.packets_recv_cnt,
            self.local_stat.bytes_recv_cnt,
            self.local_stat.packets_send_cnt,
            self.local_stat.bytes_send_cnt,
            self.local_stat.lost_cnt,
            self.local_stat.latency,
            self.local_stat.rssi,
            )
        self.transport.sendto(b'stat:' + payload)

    def send_ping(self):
        payload = struct.pack('>LQ', self.ping_no, time.monotonic_ns())
        self.ping_no += 1
        self.transport.sendto(b'ping:' + payload)

    def datagram_received(self, data, addr):
        self.remote_addr = addr

        if data[:5] == b'ping:':
            payload = data[5:]
            if self.other:
                self.other.transport.sendto(b'pong:' + payload)
            return 

        if data[:5] == b'pong:':
            now_ts = time.monotonic_ns()
            payload = data[5:]
            ping_no, ping_ts = struct.unpack('>LQ', payload)
            self.latency = (now_ts - ping_ts)
            return
        
        if data[:5] == b'stat:':
            pr, br, ps, bs, loss, latency, rssi = struct.unpack('LLLLLQi', data[5:])
            self.remote_stat.update(
                packets_recv_cnt = pr,
                bytes_recv_cnt = br,
                packets_send_cnt = ps,
                bytes_send_cnt = bs,
                lost_cnt = loss,
                latency = latency,
                rssi = rssi,
            )
            return

        self.packets_recv_cnt += 1
        self.bytes_recv_cnt += len(data)
        packet_no = struct.unpack('I', data[:4])[0]
        if packet_no > (self.recv_packet_no + 1):
            missed = packet_no - self.recv_packet_no - 1
            self.lost_cnt += missed
            
        self.recv_packet_no = packet_no

        self.on_data_received(data)

    def on_data_received(self, data):
        pass

    def update_stat_and_reset(self):
        self.stat.update(proto=self)
        self.local_stat.update(proto=self)
        self.packets_recv_cnt = 0
        self.bytes_recv_cnt = 0
        self.packets_send_cnt = 0
        self.bytes_send_cnt = 0
        self.lost_cnt = 0
        self.latency = 0


class InputProtocol(BaseProtocol):
    pass


class OutputProtocol(BaseProtocol):
    pass


class LinkStatusProtocol:

    def __init__(self, mode):
        self.rssi = -120
        self.mode = mode # air or ground

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        try:
            msg = data.decode()
        except:
            pass
        else:
            fields = msg.split(',')
            if fields[0] == self.mode:
                self.rssi = int(float(fields[-1]))


async def send_loop(loop, out_proto, packetsize, sendpause):
    payload = enc_data[:packetsize]
    while True:
        out_proto.send(payload)
        await asyncio.sleep(sendpause)


async def send_stat_loop(out_proto):
    while True:
        out_proto.send_local_stat()
        await asyncio.sleep(0.05)
        out_proto.send_ping()
        await asyncio.sleep(0.05)


def format_bytes_count(bytes_cnt):
    if bytes_cnt > 1024 * 9:
        r = '{:8.1f}kB/s'.format(bytes_cnt / 1024)
    else:
        r = '{:>9}B/s'.format(bytes_cnt)
    return r


async def report(loop, out_proto, in_proto, stat_proto):
    while True:
        await asyncio.sleep(1)
        out_proto.update_stat_and_reset()
        in_proto.update_stat_and_reset()
        out_proto.local_stat.bytes_recv_cnt = in_proto.stat.bytes_recv_cnt
        out_proto.local_stat.packets_recv_cnt = in_proto.stat.packets_recv_cnt
        out_proto.local_stat.lost_cnt = in_proto.stat.lost_cnt
        out_proto.local_stat.latency = in_proto.stat.latency
        print()

        print("{:8d} {:>12} {:>12} {:>9} {:>9} {:>9}".format(
              int(loop.time()), "Recieve", "Send", "Loss", "Latency", "RSSI"))

        r = format_bytes_count(in_proto.stat.bytes_recv_cnt)
        s = format_bytes_count(out_proto.stat.bytes_send_cnt)

        l = 0
        if in_proto.stat.packets_recv_cnt > 0:
            l = in_proto.stat.lost_cnt / (in_proto.stat.packets_recv_cnt + in_proto.stat.lost_cnt) * 100

        rssi = stat_proto.rssi
        out_proto.local_stat.rssi = rssi
        latency = in_proto.local_stat.latency / 1e6
        print("{:>8} {} {} {:8.1f}% {:8.3f}ms {:8d}dbm".format('LOCAL', r, s, l, latency, rssi))

        r = format_bytes_count(in_proto.remote_stat.bytes_recv_cnt)
        s = format_bytes_count(in_proto.remote_stat.bytes_send_cnt)

        l = 0
        if in_proto.remote_stat.packets_recv_cnt > 0:
            l = in_proto.remote_stat.lost_cnt / (in_proto.remote_stat.packets_recv_cnt + in_proto.remote_stat.lost_cnt) * 100
        latency = in_proto.remote_stat.latency / 1e6
        rssi = in_proto.remote_stat.rssi
        print("{:>8} {} {} {:8.1f}% {:8.3f}ms {:8d}dbm".format('REMOTE', r, s, l, latency, rssi))



async def main(inport, outport, statport, packetsize, sendpause, mode):
    print("Starting UDP traffic gen")

    # Get a reference to the event loop as we plan to use
    # low-level APIs.
    loop = asyncio.get_running_loop()


    _, out_proto = await loop.create_datagram_endpoint(
        OutputProtocol,
        remote_addr=('127.0.0.1', outport))

    _, in_proto = await loop.create_datagram_endpoint(
        lambda: InputProtocol(out_proto),
        local_addr=('127.0.0.1', inport))

    _, stat_proto = await loop.create_datagram_endpoint(
        lambda: LinkStatusProtocol(mode),
        local_addr=('127.0.0.1', statport))

    send_task = asyncio.ensure_future(send_loop(loop, out_proto, packetsize, sendpause))
    send_stat_task = asyncio.ensure_future(send_stat_loop(out_proto))
    report_task = asyncio.ensure_future(report(loop, out_proto, in_proto, stat_proto))

    try:
        await asyncio.sleep(3600)  # Serve for 1 hour.
    finally:
        transport.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Process some integers.')

    parser.add_argument('--inport', type=int, required=True, help='UDP input port')
    parser.add_argument('--outport', type=int, required=True, help='UDP out port')
    parser.add_argument('--statport', type=int, required=True, help='UDP WFB status port')
    parser.add_argument('--packetsize', type=int, required=True, help='Send packet size')
    parser.add_argument('--sendpause', type=float, required=True, help='Send packet pause')
    parser.add_argument('--mode', type=str, required=True, help='Instance mode - air or ground')

    args = parser.parse_args()
    
    main_coro = main(
        inport=args.inport,
        outport=args.outport,
        statport=args.statport,
        packetsize=args.packetsize,
        sendpause=args.sendpause,
        mode=args.mode,
    )

    asyncio.run(main_coro)
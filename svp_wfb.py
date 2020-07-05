import argparse
import sys
import asyncio
import logging
from asyncio import subprocess

"""
# air
## bench
sudo wfb_tx -K /etc/drone.key -p 1 -u 7555 -k 4 -n 12 wlan0
sudo wfb_rx -K /etc/drone.key -p 2 -u 7558 -k 4 -n 12 wlan0
## ft
sudo wfb_tx -K /etc/drone.key -p 1 -u 6555 -k 4 -n 12 wlan0
sudo wfb_rx -K /etc/drone.key -p 2 -u 6558 -k 4 -n 12 wlan0

# -k 8 -n 12 - default Reed-Solomin parameter
# Reed-Solomon parameter "k" -- default 8
# Reed-Solomon parameter "n" -- default 12. This means that FEC block size is 12 packets and up to 4 (12 - 8) can be recovered if lost

# ground
## bench
sudo wfb_rx -K /etc/gs.key -p 1 -u 7556 -k 4 -n 12 wlan0
sudo wfb_tx -K /etc/gs.key -p 2 -u 7557 -k 4 -n 12 wlan0
## ft
sudo wfb_rx -K /etc/gs.key -p 1 -u 6556 -k 4 -n 12 wlan0
sudo wfb_tx -K /etc/gs.key -p 2 -u 6557 -k 4 -n 12 wlan0

RX
Local receiver: wfb_rx [-K rx_key] [-k RS_K] [-n RS_N] [-c client_addr] [-u client_port] [-p radio_port] [-l log_interval] interface1 [interface2] ...
Remote (forwarder): wfb_rx -f [-c client_addr] [-u client_port] [-p radio_port] interface1 [interface2] ...
Remote (aggregator): wfb_rx -a server_port [-K rx_key] [-k RS_K] [-n RS_N] [-c client_addr] [-u client_port] [-l log_interval]
Default: K='rx.key', k=8, n=12, connect=127.0.0.1:5600, radio_port=1, log_interval=1000

TX
Usage: wfb_tx [-K tx_key] [-k RS_K] [-n RS_N] [-u udp_port] [-p radio_port] [-B bandwidth] [-G guard_interval] [-S stbc] [-L ldpc] [-M mcs_index] interface1 [interface2] ...
Default: K='tx.key', k=8, n=12, udp_port=5600, radio_port=1 bandwidth=20 guard_interval=long stbc=0 ldpc=0 mcs_index=1
Radio MTU: 1446
WFB version 19.2.16.44936-212f5c1d
"""

logger = logging.getLogger('main')
logging.basicConfig(level='DEBUG', format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")


class DummyProto:

    def connection_made(self, transport):
        print('Dummy connection_made:', transport)

    def datagram_received(self, data, addr):
        print('Dummy datagram_received:', addr)

    def error_received(self, exc):
        print('Dummy Error received:', exc)

    def connection_lost(self, exc):
        print("Dummy Connection closed", exc)
        

class Channel:
    """
    WFB Channel
    """

    def __init__(self, name, mode, iface, num, fec, udp_in, udp_out):
        self.name = name
        self.mode = mode
        self.iface = iface
        self.num = num
        self.fec = fec
        self.udp_in = udp_in
        self.udp_out = udp_out

        self.rx_proc = None
        self.tx_proc = None
        self.stat_transport = None

    async def start(self):
        params = {
            'iface': self.iface,
            'mode': self.mode,
            'udp_in': self.udp_in,
            'udp_out': self.udp_out,
            'k': int(self.fec.split('/')[0]),
            'n': int(self.fec.split('/')[1]),
            'rx_port': self.num[0] if self.mode == 'ground' else self.num[1],
            'tx_port': self.num[1] if self.mode == 'ground' else self.num[0],
            'key': 'gs' if self.mode == 'ground' else 'drone'
        }
        rx_proc_cmd = 'wfb_rx -K /etc/{key}.key -p {rx_port} -u {udp_out} -k {k} -n {n} {iface}'.format(**params)
        tx_proc_cmd = 'wfb_tx -K /etc/{key}.key -p {tx_port} -u {udp_in} -k {k} -n {n} {iface}'.format(**params)
        
        logger.info("Chan %s starting RX subprocess: %s", self.name, rx_proc_cmd)
        self.rx_proc = await asyncio.create_subprocess_shell(
            rx_proc_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)

        logger.info("Chan %s starting TX subprocess: %s", self.name, tx_proc_cmd)
        self.tx_proc = await asyncio.create_subprocess_shell(
            tx_proc_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)

        loop = asyncio.get_running_loop()
        self.stat_transport, _ = await loop.create_datagram_endpoint(
            DummyProto,
            remote_addr=('127.0.0.1', 5800))

        asyncio.create_task(self.report())

    async def report(self):
        logger.info("Chan %s starting report task", self.name)
        while True:
            raw_data = await self.rx_proc.stdout.readline()
            raw_data = raw_data.decode()
            #logger.info("STAT: %s", raw_data)
            # 9638071\tANT\t0\t411:-75:-71:-68
            if 'ANT' in raw_data:
                rssi_avg = raw_data.split(':')[-2]
                logger.info("Chan %s RX avg RSSI: %s", self.name, rssi_avg)
                if self.stat_transport:
                    data = '{},{}'.format(self.mode, rssi_avg)
                    self.stat_transport.sendto(data.encode())

    async def stop(self):
        logger.info("Chan %s Stopping subprocesses", self.name)
        self.rx_proc.terminate()
        self.tx_proc.terminate()


async def main(args):
    bench_chan = Channel('bench', args.mode, args.iface, [1,2], args.fec, 7557, 7556)
    ft_chan = Channel('ft', args.mode, args.iface, [3, 4], args.fec, 6557, 6556)
    telem_chan = Channel('telem', args.mode, args.iface, [5, 6], args.fec, 5557, 5556)
    await bench_chan.start()
    await ft_chan.start()
    await telem_chan.start()
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await bench_chan.stop()
        await ft_chan.stop()
        await telem_chan.stop()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='SVP WFB Launcher')

    parser.add_argument('--fec', type=str, required=True, help='fec params k/n (8/12 default, 1/2 for telemetry)')
    parser.add_argument('--mode', type=str, required=True, help='Instance mode - ground or air')
    parser.add_argument('iface', type=str, help='Wlan interface to use')

    args = parser.parse_args()

    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print('Stopping all')
    finally:
        print('FIN!')

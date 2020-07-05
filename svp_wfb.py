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
logger = logging.getLogger(__name__)
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

    def __init__(self, mode, fec, iface):
        self.rx_proc = None
        self.tx_proc = None
        self.stat_transport = None
        self.counter = 0
        self.mode = mode
        self.fec = fec
        self.iface = iface

    # async def send_command(self, cmd, single_read=True, fin=False):
    #     self.proc.stdin.write(cmd.encode() + b'\n')
    #     await self.proc.stdin.drain()
    #     ret = await self.proc.stdout.readline()
    #     logger.info("Cmd: %s, ret 1:%s", cmd, ret)
    #     if single_read is False:
    #         ret = await self.proc.stdout.readline()
    #         logger.info("Cmd: %s, ret 2:%s", cmd, ret)
    #     if fin:
    #         logger.info("Cmd read 3: %s", cmd)
    #         await self.proc.stdout.readline()
    #         logger.info("Cmd: %s, ret 3:%s", cmd, ret)

    #     logger.info("Cmd: %s, ret: %s", cmd, ret)
    #     return ret

    async def start(self):
        params = {
            'iface': self.iface,
            'mode': self.mode,
            'k': int(self.fec.split('/')[0]),
            'n': int(self.fec.split('/')[1]),
            'rx_port': 1 if self.mode == 'gs' else 2,
            'tx_port': 2 if self.mode == 'gs' else 1,
        }
        rx_proc_cmd = 'wfb_rx -K /etc/{mode}.key -p {rx_port} -u 7556 -k {k} -n {n} {iface}'.format(**params)
        tx_proc_cmd = 'wfb_tx -K /etc/{mode}.key -p {tx_port} -u 7557 -k {k} -n {n} {iface}'.format(**params)
        
        logger.info("Starting RX subprocess: %s", rx_proc_cmd)
        self.rx_proc = await asyncio.create_subprocess_shell(
            rx_proc_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)

        logger.info("Starting TX subprocess: %s", tx_proc_cmd)
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
        logger.info("Starting report task")
        while True:
            raw_data = await self.rx_proc.stdout.readline()
            raw_data = raw_data.decode()
            #logger.info("STAT: %s", raw_data)
            # 9638071\tANT\t0\t411:-75:-71:-68
            if 'ANT' in raw_data:
                rssi_avg = raw_data.split(':')[-2]
                logger.info("RX AVG RSSI: %s", rssi_avg)
                if self.stat_transport:
                    self.stat_transport.sendto(rssi_avg.encode())

    async def stop(self):
        self.rx_proc.terminate()
        self.tx_proc.terminate()


async def main(args):
    chan = Channel(args.mode, args.fec, args.iface)
    await chan.start()
    while True:
        await asyncio.sleep(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='SVP WFB Launcher')

    parser.add_argument('--fec', type=str, required=True, help='fec params k/n (8/12 default, 1/2 for telemetry)')
    parser.add_argument('--mode', type=str, required=True, help='Instance mode - gs or drone')
    parser.add_argument('iface', type=str, help='Wlan interface to use')

    args = parser.parse_args()

    try:
        asyncio.run(main(args))
    finally:
        print('FIN!')

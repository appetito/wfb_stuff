import argparse
import sys
import asyncio
import logging
from asyncio import subprocess
import os

from pymavlink.dialects.v20 import common

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
Local receiver: wfb_rx [-K rx_key] [-k RS_K] [-n RS_N] [-c client_addr] [-u client_port] [-p radio_port] [-l log_interval] iface1 [iface2] ...
Remote (forwarder): wfb_rx -f [-c client_addr] [-u client_port] [-p radio_port] iface1 [iface2] ...
Remote (aggregator): wfb_rx -a server_port [-K rx_key] [-k RS_K] [-n RS_N] [-c client_addr] [-u client_port] [-l log_interval]
Default: K='rx.key', k=8, n=12, connect=127.0.0.1:5600, radio_port=1, log_interval=1000

TX
Usage: wfb_tx [-K tx_key] [-k RS_K] [-n RS_N] [-u udp_port] [-p radio_port] [-B bandwidth] [-G guard_interval] [-S stbc] [-L ldpc] [-M mcs_index] iface1 [iface2] ...
Default: K='tx.key', k=8, n=12, udp_port=5600, radio_port=1 bandwidth=20 guard_interval=long stbc=0 ldpc=0 mcs_index=1
Radio MTU: 1446
WFB version 19.2.16.44936-212f5c1d






!!!!!!!!!


EniSy, [04.07.20 19:09]
я с мощностью у синих стиков так и не разобрался, параметр ,который мы  выставляем, мне показалось погоду на марсе регулирует

EniSy, [04.07.20 19:10]
например на 53-700мвт на 30-500мВт а на 17снова 700

EniSy, [04.07.20 19:11]
около 23 я получал ~300



RF loss vegetation:
https://www.itu.int/dms_pubrec/itu-r/rec/p/R-REC-P.833-9-201609-I!!PDF-E.pdf

L(dB) = 0.25*(f**0.39)*(d**0.25) * (a**0.05)

!!!!!!!!!
"""

logger = logging.getLogger('main')
logging.basicConfig(level='DEBUG', format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")


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



class MavProxy:

    def __init__(self, telem_chan):
        self.telem_chan = telem_chan
        self.mav = common.MAVLink(None, srcSystem=1, srcComponent=1)

    async def report(self, loop, up, down, gcs):
        loop = asyncio.get_running_loop()
        ts = loop.time()
        while True:
            await asyncio.sleep(1)
            dt = loop.time() - ts
            ts = loop.time()
            radio_rssi = 127 + 128 + int(self.telem_chan.rssi.rssi)
            logger.info("MAV UP: %s", up.bytes_cnt / dt)
            logger.info("MAV DOWN: %s", down.bytes_cnt / dt)
            logger.info("MAV RSSI: %s (%s)", self.telem_chan.rssi, radio_rssi)
            up.bytes_cnt = 0
            down.bytes_cnt = 0

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

    async def start(self):
        logger.info("Starting MAV Proxy")
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

        asyncio.create_task(self.report(gs_proto, downlink_proto, gs_link))


class DummyProto:

    def connection_made(self, transport):
        pass

    def datagram_received(self, data, addr):
        pass

    def error_received(self, exc):
        pass

    def connection_lost(self, exc):
        pass
        

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
        self.rssi = -100

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
        
        logger.info("Chan [%s] starting RX subprocess: %s", self.name, rx_proc_cmd)
        self.rx_proc = await asyncio.create_subprocess_shell(
            rx_proc_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)

        logger.info("Chan [%s] starting TX subprocess: %s", self.name, tx_proc_cmd)
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
        logger.info("Chan [%s] starting report task", self.name)
        while True:
            await asyncio.sleep(0.1)
            raw_data = await self.rx_proc.stdout.readline()
            raw_data = raw_data.decode()
            logger.info("REPORT %s %s", self.name, raw_data)
            #logger.info("STAT: %s", raw_data)
            # 9638071\tANT\t0\t411:-75:-71:-68
            if 'ANT' in raw_data:
                rssi_avg = raw_data.split(':')[-2]
                self.rssi = rssi_avg
                logger.info("Chan %s RX avg RSSI: %s", self.name, rssi_avg)
                if self.stat_transport:
                    data = '{},{}'.format(self.mode, rssi_avg)
                    self.stat_transport.sendto(data.encode())

    async def stop(self):
        logger.info("Chan [%s] Stopping subprocesses", self.name)
        self.rx_proc.terminate()
        self.tx_proc.terminate()


async def main(args):
    bench_chan = Channel('bench', args.mode, args.iface, [1, 2], args.fec, 7557, 7556)
    ft_chan = Channel('ft', args.mode, args.iface, [3, 4], args.fec, 6557, 6556)
    telem_chan = Channel('telem', args.mode, args.iface, [5, 6], args.fec, 5557, 5556)

    mav_proxy = MavProxy(telem_chan)

    await bench_chan.start()
    await ft_chan.start()
    await telem_chan.start()

    if args.mode == 'ground':
        await mav_proxy.start()

    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await bench_chan.stop()
        await ft_chan.stop()
        await telem_chan.stop()


def ath9k_configure(iface, freq, txpower, bitrate):
    logging.info("Configuring iface %s: %sMhz %sMbs %sTxPwr", iface, freq, bitrate, txpower)

    # Try to bring up the iface
    try:
        os.system("ifconfig " + iface + " up")
    except Exception as e:
        logging.error("Error bringing the iface up: " + iface)
        logging.error(e)
        return False

    # Configure the bitrate for this card
    if bitrate != 0:
        try:
            logging.info("Setting the bitrate on iface " + iface + " to " + str(bitrate))
            if os.system("iw dev " + iface + " set bitrates legacy-2.4 " + str(bitrate)) != 0:
                logging.error("Error setting the bitrate for: " + iface)
        except Exception as e:
            logging.error("Error setting the bitrate for: " + iface)
            logging.error(e)

    # Bring the card down
    try:
        os.system("ifconfig " + iface + " down")
    except Exception as e:
        logging.error("Error bringing the iface down: " + iface)
        logging.error(e)
        return False

    # Configure the transmit power level
    try:
        logging.info("Setting txpower on iface " + iface + " to " + str(txpower))
        with open("/sys/module/ath9k_hw/parameters/txpower", "w") as fp:
            fp.write(str(txpower))
    except Exception as e:
        logging.warning("Could not set txpower on " + iface)
        logging.warning(e)

    # Configure the card in monitor mode
    try:
        os.system("iw dev " + iface + " set monitor none")
    except:
        logging.error(iface + " does not support monitor mode")
        return None

    # Try to bring up the iface
    try:
        os.system("ifconfig " + iface + " up")
    except Exception as e:
        logging.error("Error bringing the iface up: " + iface)
        logging.error(e)
        return False

    # Configure the freq
    try:
        logging.info("Setting the freq on iface " + iface + " to " +
                     str(freq) + " using iw")
        os.system("iw dev %s set freq %s" % (iface, str(freq)))
    except Exception as e:
        logging.error("Error setting the wifi freq on: " + iface)
        logging.error(e)
        return False

    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='SVP WFB Launcher')

    parser.add_argument('--mode', type=str, required=True, help='Instance mode - ground or air')
    parser.add_argument('--fec', type=str, required=True, help='fec params k/n (8/12 default, 1/2 for telemetry)')
    parser.add_argument('--freq', type=int, default=2432, help='WiFi frequency default 2432')
    parser.add_argument('--txpower', type=int, default=58, help='TX power (20-63) default  58')
    parser.add_argument('--bitrate', type=float, default=11, help='bitrate (2, 5.5, 11) default 11')
    parser.add_argument('iface', type=str, help='Wlan iface to use')

    args = parser.parse_args()

    ath9k_configure(args.iface, args.freq, args.txpower, args.bitrate)

    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print('Stopping all')
    finally:
        print('FIN!')


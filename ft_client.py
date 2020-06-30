import argparse
import asyncio
import logging

from wfb_ft import FtpClient


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='WFB FT client - file download')

    parser.add_argument('--inport', type=int, required=True, help='WFB UDP input port')
    parser.add_argument('--outport', type=int, required=True, help='WFB UDP out port')
    parser.add_argument('--log-level', help='Log level', default='INFO')
    parser.add_argument('filename', help='file to download')

    args = parser.parse_args()
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    
    client = FtpClient(args.inport, args.outport)
    # loop = asyncio.get_event_loop()
    # asyncio.create_task(client.start())

    asyncio.run(client.get_file(args.filename))


import argparse
import asyncio
import logging

from wfb_ft import FtpServer


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='WFB FT client - file download')

    parser.add_argument('--inport', type=int, required=True, help='WFB UDP input port')
    parser.add_argument('--outport', type=int, required=True, help='WFB UDP out port')
    parser.add_argument('--log-level', help='Log level', default='INFO')
    parser.add_argument('--root-dir', type=str, required=True, help='Root directory to serve')

    args = parser.parse_args()
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    
    server = FtpServer(args.inport, args.outport, args.root_dir)

    asyncio.run(server.start())

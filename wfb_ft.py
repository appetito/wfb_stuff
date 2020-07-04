"""
File transfer util for WFB bridge
"""

import argparse
import asyncio
import string
import sys
import struct
import time
import pathlib
import logging
import random


logger = logging.getLogger(__name__)


MAX_sequence = 4294967294


class Command:
    GET_LIST = 1
    SEND_LIST_ITEM = 2
    GET_FILE = 3
    SEND_CHUNK = 4
    ACK = 5
    NACK = 6
    TRANSFER_COMPLETE = 7


class Header:

    def __init__(self, cmd, node_id, sequence):
        self.cmd = cmd
        self.node_id = node_id
        self.sequence = sequence

    @classmethod
    def unpack(cls, header_data):
        cmd, node_id, sequence = struct.unpack('>BHI', header_data)
        return cls(cmd=cmd, node_id=node_id, sequence=sequence)

    def pack(self):
        return struct.pack('>BHI', self.cmd, self.node_id, self.sequence)

    def __repr__(self):
        return 'c:{} n:{} s:{}'.format(self.cmd, self.node_id, self.sequence)


class Message:

    def __init__(self, sequence, node_id, **fields):
        self.header = Header(cmd=self.COMMAND, sequence=sequence, node_id=node_id)
        for k, v in fields.items():
            if k in self.fields:
                setattr(self, k, v)
            else:
                raise ValueError("Uncknown filed {} for {}", k, self)

    def fields_list(self):
        return [getattr(self, fname) for fname in self.fields]

    def pack(self):
        return self.header.pack() + struct.pack(self.struct_format, *self.fields_list())

    @classmethod
    def unpack(cls, data):
        header_data = data[:7]
        payload = data[7:] 
        header = Header.unpack(header_data)
        fields_values = struct.unpack(cls.struct_format, payload)
        fields = dict(zip(cls.fields, fields_values))
        return cls(header.sequence, header.node_id, **fields)

    def __repr__(self):
        fields_repr = []
        for f in self.fields:
            fr = '{}={}'.format(f, getattr(self, f))
            if len(fr) > 20:
                fr = fr[:20] + '...'
            fields_repr.append(fr)
        return "{}({}) {}".format(self.__class__.__name__, self.header, ', '.join(fields_repr))


class GetListMessage(Message):
    COMMAND = Command.GET_LIST
    struct_format = ''
    fields = []


class AckMessage(Message):
    COMMAND = Command.ACK
    struct_format = '>I?'
    fields = ['ack_sequence', 'ack']


class SendListItemMessage(Message):
    COMMAND = Command.SEND_LIST_ITEM
    struct_format = '>I50s'
    fields = ['size', 'name']


class GetFileMessage(Message):
    COMMAND = Command.GET_FILE
    struct_format = '>I50s'
    fields = ['session_id', 'name']


class TransferCompleteMessage(Message):
    COMMAND = Command.TRANSFER_COMPLETE
    struct_format = '>I'
    fields = ['session_id']


class SendChunkMessage(Message):
    COMMAND = Command.SEND_CHUNK
    struct_format = '>IHI'
    fields = ['session_id', 'offset', 'size', 'data']

    def pack(self):
        return self.header.pack() + struct.pack(self.struct_format, self.session_id, self.offset, self.size) + self.data

    @classmethod
    def unpack(cls, data):
        msg = super().unpack(data[:7+10])
        msg.data = data[7+10:]
        return msg


messages = {
    Command.GET_LIST: GetListMessage,
    Command.SEND_LIST_ITEM: SendListItemMessage,
    Command.GET_FILE: GetFileMessage,
    Command.SEND_CHUNK: SendChunkMessage,
    Command.ACK: AckMessage,
    Command.TRANSFER_COMPLETE: TransferCompleteMessage,
} 


class WFBNodeProtocol:

    def __init__(self, server):
        self.server = server

    def connection_made(self, transport):
        logging.info('Connection made: %s', transport)
        self.transport = transport

    def datagram_received(self, data, addr):
        # print('data', data[:1])
        cmd, = struct.unpack('>B', data[:1])
        message_cls = messages[cmd]
        message = message_cls.unpack(data)
        logger.debug("Message received: %s", message)
        self.server.handle_message(message)

    def send(self, data):
        self.transport.sendto(data)

    def connection_lost(self, exc):
        logging.info("Connection lost: %s",  exc)

    def error_received(self, exc):
        logging.info("Error received: %s",  exc)


class WFBNode:

    def __init__(self, inport, outport):
        self.inport = inport
        self.outport = outport
        self.out_proto = WFBNodeProtocol(self)
        self.in_proto = WFBNodeProtocol(self)
        self.sequence = 1
        self.session_requests = {}

    def next_sequence(self):
        self.sequence += 1
        return self.sequence

    def next_session(self):
        return random.randint(10000, 4294967295)

    async def start(self):
        loop = asyncio.get_running_loop()

        await loop.create_datagram_endpoint(
            lambda: self.out_proto,
            remote_addr=('127.0.0.1', self.outport))

        await loop.create_datagram_endpoint(
            lambda: self.in_proto,
            local_addr=('127.0.0.1', self.inport))

        logging.info("WFBNode started, in: %s, out: %s", self.inport, self.outport)
        while True:
            await asyncio.sleep(1)

    def send_message(self, msg):
        data = msg.pack()
        logger.debug("Sending message: %s", msg)
        self.out_proto.send(data)

    def handle_message(self, message):
        raise NotImplemented()


class FtpServer(WFBNode):

    ACK_TIMEOUT = 0.05
    SEND_FILE_TIMEOUT = 10
    CHUNK_SIZE = 1424

    def __init__(self, inport, outport, root_dir):
        super().__init__(inport, outport)
        self.root_dir = pathlib.Path(root_dir)
        self.ack_events = {}
        self.nack_events = {}
        self.sessions = {}

    def handle_message(self, message):
        if message.header.cmd == Command.GET_LIST:
            self.do_list()
        elif message.header.cmd == Command.ACK:
            logger.debug('Ack received %s', message.ack_sequence)
            if message.ack_sequence in self.ack_events:
                self.ack_events[message.ack_sequence].set()
        elif message.header.cmd == Command.GET_FILE:
            asyncio.create_task(self.do_get_file(message))

    # def do_list(self):
    #     for p in self.root_dir.glob("*"):
    #         asyncio.create_task(self.do_send_list_item(p.name))

    # async def do_send_list_item(self, item):
    #     ack_event = asyncio.Event()
    #     sequence = self.next_sequence()
    #     self.ack_events[sequence] = ack_event
    #     while True:
    #         msg = SendListItemMessage(...)
    #         self.send_message(msg)
    #         try:
    #             await asyncio.wait_for(ack_event.wait(), timeout=self.ACK_TIMEOUT)
    #         except asyncio.TimeoutError:
    #             continue
    #         else:
    #             break
    #     del self.ack_event[sequence]

    async def do_get_file(self, message):
        if message.session_id in self.sessions:
            logger.info('Session %s already opened', message.session_id)
            return
        self.sessions[message.session_id] = True
        name = message.name.decode().strip('\x00')
        file_path = self.root_dir / name
        # import pdb; pdb.set_trace()
        if not file_path.exists():
            logger.info("File not exists: %s", file_path)
            # FIXME!!!
            msg = AckMessage(self.next_sequence(), node_id=0, ack_sequence=message.header.sequence, ack=False)
            self.send_message(msg)
            return
        start_time = time.monotonic()
        with open(file_path, 'rb') as f:
            tasks = []
            offset = 0
            while True:
                chunk = f.read(self.CHUNK_SIZE)
                if chunk:
                    tasks.append(asyncio.create_task(self.send_chunk(message.session_id, offset, chunk)))
                    offset += self.CHUNK_SIZE
                else:
                    break
        done, pending = await asyncio.wait(tasks, timeout=self.SEND_FILE_TIMEOUT)

        if pending:
            for t in pending:
                t.cancel()
            raise TimeoutError("File transfer timeout")
        else:
            fin_msg = TransferCompleteMessage(self.next_sequence(), node_id=0, session_id=message.session_id)
            await self.send_and_wait_ack(fin_msg)
            transfer_time = time.monotonic() - start_time
            logger.info("File %s trasnsfered is %ss", file_path, transfer_time)

    async def send_chunk(self, session_id, offset, chunk):
        ack_event = asyncio.Event()
        sequence = self.next_sequence()
        self.ack_events[sequence] = ack_event
        msg = SendChunkMessage(sequence, node_id=0, session_id=session_id,
                               offset=offset, size=len(chunk), data=chunk)
        while True:
            logger.debug('Sending chunk %s, %s', sequence, offset)
            self.send_message(msg)
            self.send_message(msg)
            try:
                await asyncio.wait_for(ack_event.wait(), timeout=self.ACK_TIMEOUT)
            except asyncio.TimeoutError:
                continue
            else:
                break
        logger.debug('Chunk sent: %s, %s', sequence, offset)
        del self.ack_events[sequence]

    async def send_and_wait_ack(self, msg):
        ack_event = asyncio.Event()
        self.ack_events[msg.header.sequence] = ack_event
        while True:
            logger.debug('Sending message %s until ack', msg)
            self.send_message(msg)
            self.send_message(msg)
            try:
                await asyncio.wait_for(ack_event.wait(), timeout=self.ACK_TIMEOUT)
            except asyncio.TimeoutError:
                continue
            else:
                break
        logger.debug('Message sent, ack received: %s', msg)
        del self.ack_events[msg.header.sequence]
            
    # async def do_send_list_item(self, item):
    #     ack_event = asyncio.Event()
    #     sequence = self.next_sequence()
    #     self.ack_events[sequence] = ack_event
    #     while True:
    #         self.send_message(msg)
    #         try:
    #             await asyncio.wait_for(ack_event.wait(), timeout=self.ACK_TIMEOUT)
    #         except asyncio.TimeoutError:
    #             continue
    #         else:
    #             break
    #     del self.ack_event[sequence]


class FtpClient(WFBNode):

    ACK_TIMEOUT = 0.05

    def __init__(self, inport, outport):
        super().__init__(inport, outport)
        self.ack_events = {}
        self.requests_events = {}
        self.file_handlers = {}
        self.nack_events = {}
        self.transfer_complete_events = {}

    def handle_message(self, message):
        if message.header.cmd == Command.SEND_CHUNK:
            logger.debug("Receiced chunk: %s, %s", message.session_id, message.offset)
            if message.session_id in self.requests_events:
                self.requests_events[message.session_id].set()
            
            ack = AckMessage(self.next_sequence(), node_id=1, ack_sequence=message.header.sequence, ack=True)
            if message.header.sequence in self.session_requests[message.session_id]:
                # chunk processed, just send ack
                logger.debug("Just ACK: %s, %s, %s", message.header.sequence, message.session_id, message.offset)
                self.send_message(ack)
                self.send_message(ack)
                return

            if message.session_id in self.file_handlers:
                logger.debug("Writing chunk: %s, %s", message.session_id, message.offset)
                fd = self.file_handlers[message.session_id]
                fd.seek(message.offset)
                fd.write(message.data)
                self.session_requests[message.session_id].add(message.header.sequence)
            self.send_message(ack)
            self.send_message(ack)
        elif message.header.cmd == Command.TRANSFER_COMPLETE:
            if message.session_id in self.transfer_complete_events:
                self.transfer_complete_events[message.session_id].set()
            ack = AckMessage(self.next_sequence(), node_id=1, ack_sequence=message.header.sequence, ack=True)
            self.send_message(ack)
            self.send_message(ack)

    async def get_file(self, name):
        name = name.encode()
        logger.info("Getting file %s...", name)
        asyncio.create_task(self.start())  # FIXME!!!!
        await asyncio.sleep(0.5)
        start_time = time.monotonic()
        sequence = self.next_sequence()
        session_id = self.next_session()
        msg = GetFileMessage(sequence, node_id=1, session_id=session_id, name=name)
        event = asyncio.Event()
        self.requests_events[session_id] = event
        self.session_requests[session_id] = set()
        self.file_handlers[session_id] = open(name, 'wb')
        self.transfer_complete_events[session_id] = asyncio.Event()
        while not event.is_set():
            self.send_message(msg)
            await asyncio.sleep(0.05)
        logger.info("Session confirmed: %s, %s", session_id, name)
        del self.requests_events[session_id]

        await self.transfer_complete_events[session_id].wait()
        del self.transfer_complete_events[session_id]
        transfer_time = time.monotonic() - start_time
        logger.info("File %s received is %ss", name, transfer_time)
        await asyncio.sleep(3) # give time to send last ACK


    async def get_list(self):
        pass

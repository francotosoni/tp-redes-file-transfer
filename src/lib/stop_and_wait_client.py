from pathlib import Path
from lib.message import Message, MessageType
from lib.file_hashing import hashing
from lib.client import Client
from lib.constants import (
    INVALID_FILE_HASHING,
    PAYLOAD_SIZE,
    MAX_CONSECUTIVE_LOSTS,
    SOCKET_TIME_OUT,
    WRITE_BINARY_MODE,
    READ_BINARY_MODE,
    RECV_BUFFER_SIZE,
)
import logging


class StopAndWaitClient(Client):
    def download_loop(self, last_packet_number, full_path_to_file, progress_bar):
        remote_file_hash = None
        handshake_res_pos = last_packet_number
        consecutive_hr_losts = 0

        self.socket.settimeout(SOCKET_TIME_OUT * MAX_CONSECUTIVE_LOSTS)

        with open(full_path_to_file, WRITE_BINARY_MODE) as file:
            while True:
                recv_bytes, real_server_address = self.socket.recvfrom(RECV_BUFFER_SIZE)
                message = Message.decode(recv_bytes)

                logging.info(f"Received packet with seq={message.pos}")

                if message.type == MessageType.FIN:
                    remote_file_hash = message.payload
                    break

                if message.pos <= last_packet_number:
                    ack = Message(MessageType.ACK, pos=message.pos)
                    self.socket.sendto(ack.encode(), real_server_address)

                    if message.pos == handshake_res_pos:
                        consecutive_hr_losts += 1

                    if consecutive_hr_losts >= MAX_CONSECUTIVE_LOSTS:
                        raise ConnectionAbortedError
                    continue

                last_packet_number = message.pos
                ack = Message(MessageType.ACK, pos=last_packet_number)
                self.socket.sendto(ack.encode(), real_server_address)

                file.write(message.payload)
                progress_bar.update(len(message.payload))
                progress_bar.refresh()

        local_file_hash = hashing(full_path_to_file)

        error_code = INVALID_FILE_HASHING
        message = (
            Message(
                MessageType.ERROR,
                pos=message.pos,
                payload=error_code.to_bytes(1, "big"),
            )
            if remote_file_hash and (local_file_hash != remote_file_hash)
            else Message(MessageType.ACK, pos=message.pos)
        )

        self.socket.settimeout(SOCKET_TIME_OUT * 7)
        while True:
            self.socket.sendto(message.encode(), real_server_address)
            try:
                _, real_server_address = self.socket.recvfrom(RECV_BUFFER_SIZE)
            except TimeoutError:
                break

        if message.type == MessageType.ERROR:
            raise EOFError

    def upload_loop(
        self, upload_file_path, packet_number, real_server_address, progress_bar
    ):
        consecutive_losts = 0
        file_hash = hashing(upload_file_path)

        with open(upload_file_path, READ_BINARY_MODE) as file:
            payload = file.read(PAYLOAD_SIZE)
            packet_number += 1

            while True:
                if consecutive_losts >= MAX_CONSECUTIVE_LOSTS:
                    raise ConnectionAbortedError

                if not payload:
                    break

                message = Message(MessageType.OK, packet_number, payload)
                self.socket.sendto(message.encode(), real_server_address)

                logging.info(f"Sent {message}")

                try:
                    recv_bytes, real_server_address = self.socket.recvfrom(
                        RECV_BUFFER_SIZE
                    )
                except TimeoutError:
                    logging.info(
                        f"Packet lost, resending packet with seq={message.pos}"
                    )
                    consecutive_losts += 1
                    continue

                ack = Message.decode(recv_bytes)

                if ack.type == MessageType.ERROR:
                    raise ConnectionAbortedError

                if ack.pos != packet_number:
                    logging.info(
                        f"Packet lost, resending packet with seq={message.pos}"
                    )
                    consecutive_losts += 1
                    continue

                logging.info(f"Received packet with ack={message.pos}")

                progress_bar.update(len(message.payload))
                progress_bar.refresh()
                payload = file.read(PAYLOAD_SIZE)
                packet_number += 1
                consecutive_losts = 0

        self.socket.settimeout(SOCKET_TIME_OUT)
        message = Message(MessageType.FIN, packet_number, file_hash)
        self.socket.sendto(message.encode(), real_server_address)

        consecutive_losts = 0
        while True:
            if consecutive_losts >= MAX_CONSECUTIVE_LOSTS:
                raise ConnectionAbortedError
            try:
                recv_bytes, real_server_address = self.socket.recvfrom(RECV_BUFFER_SIZE)
            except TimeoutError:
                logging.info(f"FIN packet lost, resending it {message.pos}")
                consecutive_losts += 1
                self.socket.sendto(message.encode(), real_server_address)
            else:
                break

        message = Message.decode(recv_bytes)
        payload = int.from_bytes(message.payload, byteorder="big")

        if message.type == MessageType.ERROR and payload == INVALID_FILE_HASHING:
            raise EOFError

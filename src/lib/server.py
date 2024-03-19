from lib.connection_registry import ConnectionRegistry
from lib.constants import (
    MAX_CONSECUTIVE_LOSTS,
    RECV_BUFFER_SIZE,
    MAX_CONNECTIONS,
    SOCKET_TIME_OUT,
)
from concurrent.futures import ThreadPoolExecutor
from socket import socket, AF_INET, SOCK_DGRAM
from lib.message import Message, MessageType
from abc import ABC, abstractmethod
from random import randint
from pathlib import Path
from math import ceil
import logging


class Server(ABC):
    def __init__(self, address, port, storage_path):
        self.address = address
        self.port = port
        self.storage_path = storage_path
        Path(storage_path).mkdir(parents=True, exist_ok=True)
        self.socket = socket(AF_INET, SOCK_DGRAM)
        self.socket.bind((address, port))
        self.connections = ConnectionRegistry()

    def start(self):
        logging.warn(f"🚀 Server is listening on port {self.port}")
        thread_pool = ThreadPoolExecutor(max_workers=MAX_CONNECTIONS)
        tasks = {
            MessageType.DOWNLOAD: self.handle_download,
            MessageType.UPLOAD: self.handle_upload,
        }

        try:
            while True:
                bytes, client_address = self.socket.recvfrom(RECV_BUFFER_SIZE)
                if self.connections.is_open_for(client_address):
                    print("Ya hay una conexion")
                    continue

                self.connections.open(client_address)
                handshake_req = Message.decode(bytes)
                incoming_task = tasks[handshake_req.type]
                thread_pool.submit(incoming_task, client_address, handshake_req)
        except KeyboardInterrupt:
            logging.warn("🛑 Shutting down server")
            thread_pool.shutdown()
            self.socket.close()
        except Exception as e:
            logging.error(e)

    def handle_download_handshake(self, comm_socket, handshake_req, client_address):
        filename = handshake_req.payload.decode()
        download_file_path = Path(self.storage_path + "/" + filename)

        if not download_file_path.is_file():
            raise FileNotFoundError

        file_size = download_file_path.stat().st_size

        packet_number = randint(0, 10000)
        min_bytes_to_encode = ceil(file_size.bit_length() / 8)

        handshake_res = Message(
            MessageType.OK,
            pos=packet_number,
            payload=file_size.to_bytes(length=min_bytes_to_encode, byteorder="big"),
        )

        consecutive_losts = 0

        while True:
            comm_socket.sendto(handshake_res.encode(), client_address)
            print("Enviando handshake download")
            try:
                recv_bytes, client_address = comm_socket.recvfrom(RECV_BUFFER_SIZE)
            except TimeoutError:
                print("Perdimos handshake download")
                consecutive_losts += 1
                if consecutive_losts >= MAX_CONSECUTIVE_LOSTS:
                    raise ConnectionAbortedError
            else:
                break

        handshake_end = Message.decode(recv_bytes)
        print("Terminando handshake download")
        if handshake_end.type != MessageType.ACK or handshake_end.pos != packet_number:
            raise ConnectionAbortedError

        logging.warn(
            f"📤 {client_address[0]}:{client_address[1]} started downloading {download_file_path}"
        )

        return download_file_path, packet_number

    def handle_upload_handshake(self, comm_socket, handshake_req, client_address):
        last_packet_number = handshake_req.pos
        filename = handshake_req.payload.decode()

        ack = Message(
            MessageType.ACK,
            pos=last_packet_number,
        )
        # Si cliente manda request y se pierde response, cliente se queda reenviando UPLOAD REQUEST al
        # socket principal, agregar timeout aca?
        comm_socket.settimeout(SOCKET_TIME_OUT)
        consecutive_losts = 0

        while True:
            comm_socket.sendto(ack.encode(), client_address)
            print("Enviando handshake upload")
            try:
                recv_bytes, client_address = comm_socket.recvfrom(RECV_BUFFER_SIZE)
            except TimeoutError:
                print("Perdimos handshake upload")

                consecutive_losts += 1
                if consecutive_losts >= MAX_CONSECUTIVE_LOSTS:
                    raise ConnectionAbortedError
            else:
                break
        message = Message.decode(recv_bytes)
        comm_socket.settimeout(SOCKET_TIME_OUT * MAX_CONSECUTIVE_LOSTS)
        return filename, last_packet_number, message

    @abstractmethod
    def handle_download(self, client_address, handshake_req):
        raise NotImplementedError()

    @abstractmethod
    def handle_upload(self, client_address, handshake_req):
        raise NotImplementedError()

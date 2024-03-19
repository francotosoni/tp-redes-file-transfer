from lib.constants import (
    FILE_NOT_FOUND_ERROR,
    INVALID_FILE_HASHING,
    PAYLOAD_SIZE,
    RECV_BUFFER_SIZE,
    SOCKET_TIME_OUT,
    MAX_CONSECUTIVE_LOSTS,
    WINDOW_SIZE,
)
from socket import socket, AF_INET, SOCK_DGRAM
from lib.message import Message, MessageType
from lib.file_hashing import hashing
from lib.server import Server
from pathlib import Path
import threading
import asyncio
import logging
import heapq


class SelectiveRepeatServer(Server):
    def handle_download(self, client_address, handshake_req):
        comm_socket = socket(AF_INET, SOCK_DGRAM)
        comm_socket.settimeout(SOCKET_TIME_OUT)

        try:
            download_file_path, last_packet_number = self.handle_download_handshake(
                comm_socket, handshake_req, client_address
            )
        except FileNotFoundError:
            error_code = FILE_NOT_FOUND_ERROR
            error = Message(
                MessageType.ERROR, pos=0, payload=error_code.to_bytes(1, "big")
            )
            comm_socket.sendto(error.encode(), client_address)
            comm_socket.close()
            self.connections.close(client_address)
            return
        except Exception:
            error = Message(MessageType.ERROR, pos=0)
            comm_socket.sendto(error.encode(), client_address)
            comm_socket.close()
            self.connections.close(client_address)
            return

        loop = asyncio.new_event_loop()

        window: list[Message] = []
        ack: set[int] = set()

        t = threading.Thread(target=self.loop, args=(loop,))
        t.start()
        comm_socket.settimeout(SOCKET_TIME_OUT * MAX_CONSECUTIVE_LOSTS)
        with open(download_file_path, "rb") as file:
            while True:
                if not t.is_alive():
                    raise ConnectionAbortedError

                if len(window) < WINDOW_SIZE:
                    payload = file.read(PAYLOAD_SIZE)

                    if not payload:
                        if len(window) == 0:
                            remote_file_hash = hashing(download_file_path)
                            fin = Message(
                                MessageType.FIN,
                                pos=last_packet_number + 1,
                                payload=remote_file_hash,
                            )
                            comm_socket.sendto(fin.encode(), client_address)
                            break
                    else:
                        last_packet_number += 1
                        message = Message(
                            MessageType.OK,
                            pos=last_packet_number,
                            payload=payload,
                        )
                        comm_socket.sendto(message.encode(), client_address)
                        window.append(message)

                        loop.call_soon_threadsafe(
                            loop.call_later,
                            SOCKET_TIME_OUT,
                            self.callback,
                            ack,
                            window,
                            client_address,
                            loop,
                            comm_socket,
                            last_packet_number,
                        )
                        continue

                recv_bytes, client_address = comm_socket.recvfrom(RECV_BUFFER_SIZE)
                recv_ack: Message = Message.decode(recv_bytes)
                logging.info(
                    f"{client_address[0]}:{client_address[1]} Received ACK {recv_ack.pos}"
                )
                ack.add(recv_ack.pos)

                if recv_ack.type == MessageType.ERROR:
                    logging.warn(
                        f"🛑 {client_address[0]}:{client_address[1]} closed the connection"
                    )
                    comm_socket.close()
                    loop.close()
                    self.connections.close(client_address)
                    return

                while len(window) > 0 and window[0].pos in ack:
                    window.pop(0)

        loop.stop()
        consecutive_losts = 0
        comm_socket.settimeout(SOCKET_TIME_OUT)

        while True:
            if consecutive_losts >= MAX_CONSECUTIVE_LOSTS:
                raise ConnectionAbortedError
            try:
                recv_bytes, client_address = comm_socket.recvfrom(RECV_BUFFER_SIZE)
            except TimeoutError:
                logging.info(f"FIN packet lost, resending it {fin.pos}")
                consecutive_losts += 1
                comm_socket.sendto(fin.encode(), client_address)
            else:
                break

        message = Message.decode(recv_bytes)
        payload = int.from_bytes(message.payload, byteorder="big")

        if (
            message.type == MessageType.ERROR
            and payload == INVALID_FILE_HASHING
            and message.pos == fin.pos
        ):
            logging.error(
                f"❌ Downloaded {download_file_path} file has invalid checksum"
            )
        elif message.type == MessageType.ACK and message.pos == fin.pos:
            logging.warn(
                f"✅ {client_address[0]}:{client_address[1]} finished downloading {download_file_path}"
            )

        comm_socket.close()
        self.connections.close(client_address)

    def callback(
        self,
        ack: set,
        window: list[Message],
        client_address,
        loop,
        socket: socket,
        expected_ack,
        i=0,
    ):
        if i >= MAX_CONSECUTIVE_LOSTS:
            loop.stop()
        if expected_ack not in ack:
            for msg in window:
                if msg.pos == expected_ack:
                    try:
                        socket.sendto(msg.encode(), client_address)
                        loop.call_soon_threadsafe(
                            loop.call_later,
                            SOCKET_TIME_OUT,
                            self.callback,
                            ack,
                            window,
                            client_address,
                            loop,
                            socket,
                            expected_ack,
                            i + 1,
                        )
                    except OSError:
                        print("OSError")

    def loop(self, loop):
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def handle_upload(self, client_address, handshake_req):
        comm_socket = socket(AF_INET, SOCK_DGRAM)

        try:
            filename, last_packet_number, first_message = self.handle_upload_handshake(
                comm_socket, handshake_req, client_address
            )
        except Exception as e:
            logging.error("Error ", e)
            error = Message(MessageType.ERROR, pos=0)
            comm_socket.sendto(error.encode(), client_address)
            comm_socket.close()
            self.connections.close(client_address)
            return

        Path(self.storage_path).mkdir(parents=True, exist_ok=True)
        upload_file_path = Path(self.storage_path + "/" + filename)

        logging.warn(
            f"📥 {client_address[0]}:{client_address[1]} started uploading {upload_file_path}"
        )
        is_first_message = True
        buffer = []
        window_seq = handshake_req.pos

        # packet_recv: set[int] = set()

        with open(upload_file_path, "wb") as file:
            while True:
                message = None
                if not is_first_message:
                    recv_bytes, client_address = comm_socket.recvfrom(RECV_BUFFER_SIZE)
                    message = Message.decode(recv_bytes)
                else:
                    is_first_message = False
                    message = first_message

                logging.info(f"Received packet {message.pos}")

                if message.type == MessageType.FIN:
                    remote_file_hash = message.payload
                    break

                ack = Message(MessageType.ACK, pos=message.pos)
                comm_socket.sendto(ack.encode(), client_address)

                # Agregamos el mensaje recibido a un set si, o si ya lo recibimos
                # lo ignoramos
                # if message.pos in packet_recv:
                #     continue
                # else:
                #     packet_recv.add(message.pos)

                logging.info(
                    f"{client_address[0]}:{client_address[1]} Sent ACK packet {ack.pos}"
                )

                if message.pos <= window_seq:
                    continue

                if message.pos > window_seq + 1:
                    lost_ack = False
                    for m in buffer:
                        if message.pos == m.pos:
                            lost_ack = True
                            break
                    if lost_ack:
                        continue
                    heapq.heappush(buffer, message)
                    continue

                file.write(message.payload)

                window_seq += 1

                while len(buffer) > 0 and buffer[0].pos <= window_seq + 1:
                    message = heapq.heappop(buffer)
                    window_seq += 1

                    file.write(message.payload)

        local_file_hash = hashing(upload_file_path)

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

        comm_socket.settimeout(SOCKET_TIME_OUT * 7)
        while True:
            comm_socket.sendto(message.encode(), client_address)
            try:
                _, real_server_address = comm_socket.recvfrom(RECV_BUFFER_SIZE)
            except TimeoutError:
                break

        if message.type == MessageType.ACK:
            logging.warn(
                f"✅ {client_address[0]}:{client_address[1]} finished uploading {upload_file_path}"
            )
        elif message.type == MessageType.ERROR:
            Path.unlink(upload_file_path, missing_ok=True)
            logging.error(f"❌ Uploaded {upload_file_path} file has invalid checksum")

        comm_socket.close()
        self.connections.close(client_address)

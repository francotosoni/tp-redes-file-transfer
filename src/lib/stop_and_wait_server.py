from socket import socket, AF_INET, SOCK_DGRAM
from lib.message import Message, MessageType
from lib.file_hashing import hashing
from lib.server import Server
from pathlib import Path
from lib.constants import (
    FILE_NOT_FOUND_ERROR,
    INVALID_FILE_HASHING,
    PAYLOAD_SIZE,
    RECV_BUFFER_SIZE,
    MAX_CONSECUTIVE_LOSTS,
    READ_BINARY_MODE,
    WRITE_BINARY_MODE,
    SOCKET_TIME_OUT,
)
import logging


class StopAndWaitServer(Server):
    def handle_download(self, client_address, handshake_req):
        comm_socket = socket(AF_INET, SOCK_DGRAM)
        comm_socket.settimeout(SOCKET_TIME_OUT)

        try:
            download_file_path, packet_number = self.handle_download_handshake(
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

        consecutive_losts = 0
        file_hash = hashing(download_file_path)

        with open(download_file_path, READ_BINARY_MODE) as file:
            payload = file.read(PAYLOAD_SIZE)
            packet_number += 1

            while True:
                if consecutive_losts >= MAX_CONSECUTIVE_LOSTS:
                    # Se deberia mandar ERROR igual para avisar al cliente? O es contradictorio?
                    logging.info(
                        f"{client_address[0]}:{client_address[1]} Too many lost packets, closing connection..."
                    )
                    comm_socket.close()
                    # Deberia tirar una excepcion mejor
                    self.connections.close(client_address)
                    return

                message = (
                    Message(MessageType.OK, packet_number, payload)
                    if payload
                    else Message(MessageType.FIN, packet_number, file_hash)
                )

                comm_socket.sendto(message.encode(), client_address)
                logging.info(f"Sent {message}")

                try:
                    recv_bytes, client_address = comm_socket.recvfrom(RECV_BUFFER_SIZE)
                except TimeoutError:
                    consecutive_losts += 1
                    continue

                ack = Message.decode(recv_bytes)

                if ack.type == MessageType.ERROR:
                    payload = int.from_bytes(ack.payload, byteorder="big")
                    if payload == INVALID_FILE_HASHING:
                        logging.error(
                            f"❌ Downloaded {download_file_path} file has invalid checksum"
                        )
                    else:
                        logging.warn(
                            f"🛑 {client_address[0]}:{client_address[1]} closed the connection"
                        )

                    comm_socket.close()
                    self.connections.close(client_address)
                    return

                if ack.pos != packet_number:
                    logging.info(
                        f"{client_address[0]}:{client_address[1]} Packet {packet_number} lost, resending..."
                    )
                    consecutive_losts += 1
                    continue

                logging.info(
                    f"{client_address[0]}:{client_address[1]} Received ACK packet {ack.pos}"
                )

                if not payload:
                    break

                payload = file.read(PAYLOAD_SIZE)
                packet_number += 1
                consecutive_losts = 0

        logging.warn(
            f"✅ {client_address[0]}:{client_address[1]} finished downloading {download_file_path}"
        )
        comm_socket.close()
        self.connections.close(client_address)

    def handle_upload(self, client_address, handshake_req):
        comm_socket = socket(AF_INET, SOCK_DGRAM)

        try:
            filename, last_packet_number, first_message = self.handle_upload_handshake(
                comm_socket, handshake_req, client_address
            )
        except Exception:
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

        # if upload_file_path.is_open() al nombre agregarle "(1)"
        upload_failed = False
        remote_file_hash = None
        handshake_req_pos = last_packet_number
        is_first_message = True
        with open(upload_file_path, WRITE_BINARY_MODE) as file:
            while True:
                message = None
                if not is_first_message:
                    recv_bytes, client_address = comm_socket.recvfrom(RECV_BUFFER_SIZE)
                    message = Message.decode(recv_bytes)
                else:
                    is_first_message = False
                    message = first_message

                if message.type == MessageType.FIN:
                    remote_file_hash = message.payload
                    break

                ack = Message(MessageType.ACK, pos=message.pos)
                comm_socket.sendto(ack.encode(), client_address)
                logging.info(f"{client_address[0]}:{client_address[1]} {ack}")

                if message.type == MessageType.ERROR:
                    file.close()
                    Path.unlink(upload_file_path, missing_ok=True)
                    logging.warn(
                        f"🛑 {client_address[0]}:{client_address[1]} closed the connection"
                    )
                    comm_socket.close()
                    self.connections.close(client_address)
                    return

                if (
                    message.type == MessageType.UPLOAD
                    and message.pos == handshake_req_pos
                ):
                    continue

                if message.pos <= last_packet_number:
                    continue

                file.write(message.payload)
                last_packet_number = message.pos

                logging.info(
                    f"{client_address[0]}:{client_address[1]} Received OK packet {message.pos}"
                )

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
            logging.info(f"{client_address[0]}:{client_address[1]} {ack}")
            try:
                _, real_server_address = comm_socket.recvfrom(RECV_BUFFER_SIZE)
            except TimeoutError:
                break

        print(message)
        if message.type == MessageType.ACK:
            logging.warn(
                f"✅ {client_address[0]}:{client_address[1]} finished uploading {upload_file_path}"
            )
        elif message.type == MessageType.ERROR:
            Path.unlink(upload_file_path, missing_ok=True)
            logging.error(f"❌ Uploaded {upload_file_path} file has invalid checksum")

        comm_socket.close()
        self.connections.close(client_address)

from lib.constants import (
    FILE_NOT_FOUND_ERROR,
    MAX_CONSECUTIVE_LOSTS,
    SOCKET_TIME_OUT,
    RECV_BUFFER_SIZE,
)
from socket import socket, AF_INET, SOCK_DGRAM
from lib.message import Message, MessageType
from shutil import disk_usage
from random import randint
from pathlib import Path
from tqdm import tqdm
from abc import ABC
import logging


class NullProgressBar:
    def refresh(*args, **_):
        return

    def update(*args, **_):
        return

    def close(*args, **_):
        return


class Client(ABC):
    def __init__(self, server_address, server_port, print_progress_bar):
        self.server_address = server_address
        self.server_port = server_port
        self.socket = socket(AF_INET, SOCK_DGRAM)
        self.socket.settimeout(SOCKET_TIME_OUT)
        self.print_progress_bar = print_progress_bar

    def full_server_address(self):
        return (self.server_address, self.server_port)

    def establish_download_connection(self, filename):
        packet_number = 0
        consecutive_losts = 0

        handshake_req = Message(
            MessageType.DOWNLOAD,
            pos=packet_number,
            payload=filename.encode(),
        )

        while True:
            self.socket.sendto(handshake_req.encode(), self.full_server_address())
            print("Enviando solicitud")
            try:
                recv_bytes, real_server_address = self.socket.recvfrom(RECV_BUFFER_SIZE)
            except TimeoutError:
                consecutive_losts += 1
                if consecutive_losts >= MAX_CONSECUTIVE_LOSTS:
                    raise ConnectionAbortedError
            else:
                break

        handshake_res = Message.decode(recv_bytes)
        payload = int.from_bytes(handshake_res.payload, byteorder="big")

        if handshake_res.type == MessageType.ERROR and payload == FILE_NOT_FOUND_ERROR:
            self.socket.close()
            raise FileNotFoundError

        if handshake_res.type != MessageType.OK:
            error = Message(MessageType.ERROR, pos=0)
            self.socket.sendto(error.encode(), real_server_address)
            self.socket.close()
            raise ConnectionAbortedError

        packet_number = handshake_res.pos
        handshake_end = Message(MessageType.ACK, pos=packet_number)
        self.socket.sendto(handshake_end.encode(), real_server_address)

        logging.info("✅ Connected successfuly to the server")

        return packet_number, real_server_address, payload

    def start_progress_bar(self, filename, file_size):
        if self.print_progress_bar:
            return tqdm(
                total=file_size,
                desc=f"Loading {filename}",
                dynamic_ncols=True,
                colour="magenta",
                leave=False,
            )
        return NullProgressBar()

    """
    Download
    En caso de no recibir el paquete de datos, se reenvia el ACK para
    solicitar el reintento.

    El archivo descargado lo guarda en la ruta de destino
    especificada
    """

    def download(self, filename: str, destination_path: str):
        Path(destination_path).mkdir(parents=True, exist_ok=True)
        full_path_to_file = destination_path + "/" + filename

        (
            packet_number,
            real_server_address,
            file_size,
        ) = self.establish_download_connection(filename)

        total, used, free = disk_usage(destination_path)
        if free < file_size:
            error = Message(MessageType.ERROR, pos=0)
            self.socket.sendto(error.encode(), real_server_address)
            self.socket.close()
            raise SystemError

        progress_bar = self.start_progress_bar(filename, file_size)

        try:
            self.download_loop(packet_number, full_path_to_file, progress_bar)
        except EOFError:
            logging.error(f"❌ Downloaded {filename} file has invalid checksum")
            Path.unlink(Path(full_path_to_file), missing_ok=True)
        except (TimeoutError, KeyboardInterrupt):
            Path.unlink(Path(full_path_to_file), missing_ok=True)
            error = Message(MessageType.ERROR, pos=0)
            self.socket.sendto(error.encode(), real_server_address)
            logging.error(f"❌ Download of file \033[1m{filename}\033[0;0m cancelled")
        else:
            logging.warn(f"✅ File \033[1m{filename}\033[0;0m successfuly downloaded")
        finally:
            progress_bar.close()
            self.socket.close()

    """
    Upload
    En caso de no recibir el paquete de datos, se reenvia el ACK para
    solicitar el reintento.
    """

    def upload(self, filename: str, source_path: str):
        upload_file_path = Path(source_path + "/" + filename)
        if not upload_file_path.is_file():
            self.socket.close()
            raise FileNotFoundError

        packet_number = randint(0, 10000)
        handshake_req = Message(
            MessageType.UPLOAD,
            pos=packet_number,
            payload=filename.encode(),
        )

        consecutive_losts = 0

        while True:
            self.socket.sendto(handshake_req.encode(), self.full_server_address())
            try:
                recv_bytes, real_server_address = self.socket.recvfrom(RECV_BUFFER_SIZE)
            except TimeoutError:
                consecutive_losts += 1
                if consecutive_losts >= MAX_CONSECUTIVE_LOSTS:
                    raise ConnectionAbortedError
            else:
                break

        handshake_end = Message.decode(recv_bytes)

        if handshake_end.type != MessageType.ACK or handshake_end.pos != packet_number:
            error = Message(MessageType.ERROR, pos=0)
            self.socket.sendto(error.encode(), real_server_address)
            self.socket.close()
            raise ConnectionAbortedError

        file_size = upload_file_path.stat().st_size
        progress_bar = self.start_progress_bar(filename, file_size)
        logging.info("✅ Connected successfuly to the server")

        try:
            self.upload_loop(
                upload_file_path, packet_number, real_server_address, progress_bar
            )
        except EOFError:
            logging.error(f"❌ Uploaded {upload_file_path} file has invalid checksum")
        except ConnectionAbortedError:
            logging.error(
                f"🚧 Connection aborted during upload of file \033[1m{filename}\033[0;0m"
            )
        except KeyboardInterrupt:
            error = Message(MessageType.ERROR, pos=0)
            self.socket.sendto(error.encode(), real_server_address)
            logging.error(f"❌ Upload of file \033[1m{filename}\033[0;0m cancelled")
        else:
            logging.warn(f"✅ File \033[1m{filename}\033[0;0m successfuly uploaded")
        finally:
            progress_bar.close()
            self.socket.close()

from lib.constants import (
    INVALID_FILE_HASHING,
    PAYLOAD_SIZE,
    RECV_BUFFER_SIZE,
    WINDOW_SIZE,
    SOCKET_TIME_OUT,
    MAX_CONSECUTIVE_LOSTS,
)
from lib.message import Message, MessageType
from lib.file_hashing import hashing
from lib.client import Client
from socket import socket
import threading
import logging
import asyncio
import heapq


class SelectiveRepeatClient(Client):
    def download_loop(self, last_packet_recv, full_path_to_file, progress_bar):
        self.socket.settimeout(20)
        buffer = []
        # Espacio finito para el buffer, no agregar mensajes repetidos (Se puede dar si se perdio el ACK)
        window_seq = last_packet_recv
        # packet_recv: set[int] = set()
        with open(full_path_to_file, "wb") as file:
            while True:
                recv_bytes, real_server_address = self.socket.recvfrom(RECV_BUFFER_SIZE)
                message = Message.decode(recv_bytes)

                logging.info(f"Received packet with seq={message.pos}")

                # if random.randint(0, 100) < 10 and message.type != MessageType.FIN:
                #     continue

                if message.type == MessageType.FIN:
                    remote_file_hash = message.payload
                    progress_bar.refresh()
                    break

                # Se pueden perder los ACKs, lo que implicaria que el server nos envia un paquete
                # que nosotros ya tenemos. Entonces, no debemos ni escribirlo ni ponerlo en el buffer.
                # pero si mandar ACK de vuelta.
                # Simulamos la perdida de paquetes de ACK con un numero random
                # if random.randint(0, 100) > 10:
                #     logging.warn(f"Packet with ack={message.pos} lost")
                ack = Message(MessageType.ACK, pos=message.pos)
                self.socket.sendto(ack.encode(), real_server_address)
                logging.info(f"Sent {ack}")

                # Agregamos el mensaje recibido a un set si, o si ya lo recibimos
                # lo ignoramos
                # if message.pos in packet_recv:
                #     continue
                # else:
                #     packet_recv.add(message.pos)

                # Un mensaje repetido y que ya escribimos
                if message.pos <= window_seq:
                    continue

                if message.pos > window_seq + 1:
                    # (Debe haber una manera mas facil)
                    # Buscamos si el elemento ya existe en el buffer debido a un ACK perdido
                    # Si existe, no lo agregamos.
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
                progress_bar.update(message.length)
                progress_bar.refresh()

                window_seq += 1
                while len(buffer) > 0 and buffer[0].pos <= window_seq + 1:
                    message = heapq.heappop(buffer)
                    window_seq += 1

                    file.write(message.payload)
                    progress_bar.update(message.length)
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
            logging.info(f"Sent {message}")
            try:
                recv_bytes, real_server_address = self.socket.recvfrom(RECV_BUFFER_SIZE)
            except TimeoutError:
                break
            received = Message.decode(recv_bytes)
            logging.info(f"Received {received}")

        if message.type == MessageType.ERROR:
            raise EOFError

    def upload_loop(
        self, upload_file_path, last_packet_number, real_server_address, progress_bar
    ):
        loop = asyncio.new_event_loop()

        window: list[Message] = []
        ack: set[int] = set()

        t = threading.Thread(target=self.loop, args=(loop,))
        t.start()
        self.socket.settimeout(SOCKET_TIME_OUT * MAX_CONSECUTIVE_LOSTS)
        with open(upload_file_path, "rb") as file:
            while True:
                if not t.is_alive():
                    raise ConnectionAbortedError

                if len(window) < WINDOW_SIZE:
                    payload = file.read(PAYLOAD_SIZE)

                    if not payload:
                        if len(window) == 0:
                            remote_file_hash = hashing(upload_file_path)
                            fin = Message(
                                MessageType.FIN,
                                pos=last_packet_number + 1,
                                payload=remote_file_hash,
                            )
                            self.socket.sendto(fin.encode(), real_server_address)
                            break
                    else:
                        last_packet_number += 1
                        message = Message(
                            MessageType.OK,
                            pos=last_packet_number,
                            payload=payload,
                        )
                        self.socket.sendto(message.encode(), real_server_address)
                        window.append(message)

                        # logging.info("Sent message with ack=", last_packet_number)

                        loop.call_soon_threadsafe(
                            loop.call_later,
                            SOCKET_TIME_OUT,
                            self.callback,
                            ack,
                            window,
                            real_server_address,
                            loop,
                            self.socket,
                            last_packet_number,
                        )
                        continue
                recv_bytes, real_server_address = self.socket.recvfrom(RECV_BUFFER_SIZE)
                recv_ack: Message = Message.decode(recv_bytes)
                logging.info(f"Received packet with ack={message.pos}")
                ack.add(recv_ack.pos)

                if recv_ack.type == MessageType.ERROR:
                    logging.error("❌ Server closed the connection")
                    loop.close()
                    self.socket.close()
                    raise ConnectionAbortedError

                while len(window) > 0 and window[0].pos in ack:
                    m = window.pop(0)
                    progress_bar.update(m.length)
                    progress_bar.refresh()

        loop.stop()
        consecutive_losts = 0
        self.socket.settimeout(SOCKET_TIME_OUT)

        while True:
            if consecutive_losts >= MAX_CONSECUTIVE_LOSTS:
                raise ConnectionAbortedError
            try:
                recv_bytes, real_server_address = self.socket.recvfrom(RECV_BUFFER_SIZE)
            except TimeoutError:
                logging.info(f"FIN packet lost, resending it {fin.pos}")
                consecutive_losts += 1
                self.socket.sendto(fin.encode(), real_server_address)
            else:
                break

        message = Message.decode(recv_bytes)
        payload = int.from_bytes(message.payload, byteorder="big")

        if message.type == MessageType.ERROR and payload == INVALID_FILE_HASHING:
            raise EOFError

    def callback(
        self,
        ack: set,
        window: list[Message],
        real_server_address,
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
                    logging.info(
                        f"Packet lost, resending packet with seq={expected_ack}"
                    )
                    try:
                        socket.sendto(msg.encode(), real_server_address)

                        loop.call_soon_threadsafe(
                            loop.call_later,
                            SOCKET_TIME_OUT,
                            self.callback,
                            ack,
                            window,
                            real_server_address,
                            loop,
                            socket,
                            expected_ack,
                            i + 1,
                        )
                    except OSError:
                        logging.error("OSError")

    def loop(self, loop):
        asyncio.set_event_loop(loop)
        loop.run_forever()

from threading import Lock


class ConnectionRegistry:
    def __init__(self):
        self.lock = Lock()
        self.active_connections = {}
        self.total_connections = 0

    def is_open_for(self, client_address):
        with self.lock:
            return client_address in self.active_connections

    def open(self, client_address):
        with self.lock:
            self.total_connections += 1
            self.active_connections[client_address] = self.total_connections

    def close(self, client_address):
        with self.lock:
            self.active_connections.pop(client_address)

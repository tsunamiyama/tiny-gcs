import threading
import time
import queue
import socket
import select
from pymavlink import mavutil
from pymavlink.mavutil import mavfile
from typing import cast


class MavLinker:

    _QUEUED_TYPES={'COMMAND_ACK'}

    def __init__(self, conn='udpin:localhost:14540'):
        self.master = cast(mavfile, mavutil.mavlink_connection(conn))
        self.master.wait_heartbeat()

        print(f"connected: system {self.master.target_system}, "
              f"component {self.master.target_component}")

        self._running = False
        self._lock = threading.Lock()
        self._thread = None
        self._latest = {}
        self._outbox = queue.Queue()
        self._acks = queue.Queue()
        self._last_heartbeat = 0.0

        self._wake_r, self._wake_w = socket.socketpair()
        self._wake_r.setblocking(False)

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

        try:
            self._wake_w.send(b'\x00')
        except OSError:
            pass

        if self._thread:
            self._thread.join(timeout=2)
        self._wake_r.close()
        self._wake_w.close()

    def send(self, method_name, *args):
        if not self._running:
            raise RuntimeError("not running; call start() first")
        self._outbox.put((method_name, args))
        self._wake_w.send(b'\x00')

    def get(self, msg_type):
        with self._lock:
            return self._latest.get(msg_type)

    def snapshot(self):
        with self._lock:
            return dict(self._latest)

    def link_alive(self, timeout=3.0):
        return (time.time() - self._last_heartbeat) < timeout

    def wait_ack(self, command, timeout=3.0):
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            try:
                ack = self._acks.get(timeout=remaining)
            except queue.Empty:
                return None
            if ack.command == command:
                return ack

    def command(self, cmd, *params):
        p = list(params) + [0] * (7-len(params))
        self.send('command_long_send', 
                  self.master.target_system,
                  self.master.target_component,
                  cmd, 0, *p)
        return self.wait_ack(cmd)

    def arm(self, force=False):
        return self.command(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                            1, 21196 if force else 0)

    def disarm(self, force=False):
        return self.command(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                            0, 21196 if force else 0)

    def takeoff(self, altitude=10.0):
        return self.command(mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0,0,0,0,0,0, altitude)

    def land(self):
        return self.command(mavutil.mavlink.MAV_CMD_NAV_LAND)

    def _loop(self):
        fd = self.master.fd
        if fd is None:
            self._loop_no_fd()
            return
        
        while self._running:
            readable, _, _ = select.select([fd, self._wake_r], [], [], 0.5)
            if self._wake_r in readable:
                self._drain_wake()
            if fd in readable:
                self._drain_socket()
            self._flush_outbox()

    def _loop_no_fd(self):
        while self._running:
            msg = self.master.recv_match(blocking=True, timeout=0.1)
            if msg:
                self._store(msg)
            self._flush_outbox()

    def _drain_wake(self):
        try:
            while self._wake_r.recv(1024):
                pass
        except BlockingIOError:
            pass

    def _drain_socket(self):
        while True:
            msg = self.master.recv_match(blocking=False)
            if msg is None:
                break
            self._store(msg)

    def _store(self, msg):
        mtype = msg.get_type()
        if mtype == "HEARTBEAT":
            self._last_heartbeat = time.time()  
        if mtype in self._QUEUED_TYPES:
            self._acks.put(msg)
        else:
            with self._lock:
                self._latest[mtype] = msg

    def _flush_outbox(self):
        try:
            while True:
                method_name, args = self._outbox.get_nowait()
                getattr(self.master.mav, method_name)(*args)
        except queue.Empty:
            pass
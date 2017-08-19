import asyncio
import functools
import pickle


class IAMMsg():

    def __init__(self, pid):

        self.pid = pid


class DoneMsg():

    def __init__(self, pid, task_name):

        self.pid = pid
        self.task_name = task_name


class FailMsg():
    # TODO
    pass


class SalmonProtocol(asyncio.Protocol):
    # defines what messages salmon peers can send to each other

    def __init__(self, peer):

        self.peer = peer
        self.buffer = b""
        self.transport = None

    def connection_made(self, transport):

        self.transport = transport

    def data_received(self, data):

        self.buffer += data
        self.handle_lines()

    def parse_line(self, line):

        msg = None
        try:
            msg = pickle.loads(line)
        except Exception as e:
            print(e)
        return msg

    def _handle_iam_msg(self, iam_msg):

        other_pid = iam_msg.pid
        if other_pid not in self.peer.peer_connections:
            raise Exception(
                "Unknown peer attempting to register: " + str(other_pid))
        conn = self.peer.peer_connections[other_pid]
        if isinstance(conn, asyncio.Future):
            conn.set_result((self.transport, self))
        else:
            raise Exception("Unexpected peer registration attempt")

    def _handle_done_msg(self, done_msg):

        if self.peer.dispatcher:
            self.peer.dispatcher.receive_msg(done_msg)
        else:
            raise Exception("No dispatcher registered")

    def handle_msg(self, msg):

        if isinstance(msg, IAMMsg):
            self._handle_iam_msg(msg)
        elif isinstance(msg, DoneMsg):
            self._handle_done_msg(msg)
        else:
            raise Exception("Weird message: " + str(msg))

    def handle_lines(self):

        # using delimiters for now
        # TODO: switch to sending length flags
        while b"\n\n\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n\n\n", 1)
            parsed = self.parse_line(line)
            if parsed:
                self.handle_msg(parsed)
            else:
                print("failed to parse line:", line)


class SalmonPeer():
    # handles communication with other peers

    def __init__(self, loop, config):

        self.pid = config["pid"]
        self.parties = config["parties"]
        self.host = self.parties[self.pid]["host"]
        self.port = self.parties[self.pid]["port"]
        self.peer_connections = {}
        self.dispatcher = None
        self.server = loop.create_server(
            lambda: SalmonProtocol(self),
            host=self.host, port=self.port)
        self.loop = loop

    def connect_to_others(self):

        def _create_connection_retry(f, other_host, other_port):

            def retry(conn, res):

                if res.exception():
                    c = asyncio.async(self.loop.create_connection(
                        f, other_host, other_port))
                    c.add_done_callback(functools.partial(retry, conn))
                else:
                    conn.set_result(res.result())

            complete_conn = asyncio.Future()
            conn = asyncio.async(self.loop.create_connection(
                f, other_host, other_port))
            conn.add_done_callback(functools.partial(retry, complete_conn))

            return complete_conn

        def _send_IAM(pid, conn):

            msg = IAMMsg(pid)
            formatted = pickle.dumps(msg) + b"\n\n\n"
            transport, protocol = conn.result()
            transport.write(formatted)

        to_wait_on = []
        for other_pid in self.parties.keys():
            if other_pid < self.pid:
                other_host = self.parties[other_pid]["host"]
                other_port = self.parties[other_pid]["port"]
                print("Will connect to {} at {}:{}".format(
                    other_pid, other_host, other_port))
                # create connection
                # using deprecated asyncio.async for 3.4.3 support
                conn = _create_connection_retry(
                    lambda: SalmonProtocol(self), other_host, other_port)
                self.peer_connections[other_pid] = conn
                # once connection is ready, register own ID with other peer
                conn.add_done_callback(functools.partial(_send_IAM, self.pid))
                # TODO: figure out way to wait on message delivery
                # instead of on connection
                to_wait_on.append(conn)
            elif other_pid > self.pid:
                print("Will wait for {} to connect".format(other_pid))
                # expect connection from other peer
                connection_made = asyncio.Future()
                self.peer_connections[other_pid] = connection_made
                to_wait_on.append(connection_made)
        self.loop.run_until_complete(asyncio.gather(
            *to_wait_on))
        # done connecting
        # unwrap futures that hold ready connections
        for pid in self.peer_connections:
            completed_future = self.peer_connections[pid]
            # the result is a (transport, protocol) tuple
            # we only want the transport
            self.peer_connections[pid] = completed_future.result()[0]

    def _send_msg(self, receiver, msg):

        # sends formatted message
        formatted = pickle.dumps(msg) + b"\n\n\n"
        self.peer_connections[receiver].write(formatted)

    def send_done_msg(self, receiver, task_name):

        # sends message indicating task completion
        done_msg = DoneMsg(self.pid, task_name)
        self._send_msg(receiver, done_msg)


def setup_peer(config):

    loop = asyncio.get_event_loop()
    peer = SalmonPeer(loop, config)
    loop.run_until_complete(peer.server)
    peer.connect_to_others()
    return peer

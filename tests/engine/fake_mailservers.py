"""시험용 가짜 메일 서버(이 컴퓨터 안 127.0.0.1, 암호화 없음). 진짜 메일은 오가지 않는다.

FakeIMAP: LOGIN · SELECT · UID SEARCH(ALL/UNSEEN) · UID FETCH(BODY.PEEK[] FLAGS) · UID STORE · UID COPY · EXPUNGE · APPEND
FakeSMTP: EHLO · AUTH PLAIN/LOGIN · MAIL · RCPT · DATA (받은 메일을 sent 에 모음)
"""
import re
import socket
import socketserver
import threading


def _mutf7_decode(name: str) -> str:
    """IMAP 폴더 이름(수정된 UTF-7) → 글자."""
    import base64
    out, i = [], 0
    while i < len(name):
        if name[i] == "&":
            j = name.index("-", i)
            chunk = name[i + 1:j]
            if not chunk:
                out.append("&")
            else:
                b = chunk.replace(",", "/")
                b += "=" * (-len(b) % 4)
                out.append(base64.b64decode(b).decode("utf-16-be"))
            i = j + 1
        else:
            out.append(name[i])
            i += 1
    return "".join(out)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class FakeIMAP:
    def __init__(self, user="me", password="pw", folders=None):
        self.user, self.password = user, password
        self.folders = folders or {"INBOX": []}         # 폴더 → [{"uid", "raw", "flags": set()}]
        self.next_uid = 100
        self.logins = []
        outer = self

        class H(socketserver.StreamRequestHandler):
            def w(self, s):
                self.wfile.write((s + "\r\n").encode("utf-8"))

            def handle(self):
                sel = None
                self.w("* OK fake imap ready")
                while True:
                    line = self.rfile.readline()
                    if not line:
                        return
                    line = line.decode("utf-8", "replace").rstrip("\r\n")
                    tag, _, rest = line.partition(" ")
                    cmd, _, args = rest.partition(" ")
                    cmd = cmd.upper()
                    if cmd == "CAPABILITY":
                        self.w("* CAPABILITY IMAP4rev1 AUTH=PLAIN")
                        self.w(f"{tag} OK done")
                    elif cmd == "LOGIN":
                        u, p = [x.strip('"') for x in args.split(" ", 1)]
                        outer.logins.append(u)
                        self.w(f"{tag} OK logged in" if (u, p) == (outer.user, outer.password) else f"{tag} NO bad login")
                    elif cmd == "SELECT":
                        name = _mutf7_decode(args.strip('"'))
                        if name not in outer.folders:
                            self.w(f"{tag} NO no such folder")
                            continue
                        sel = name
                        self.w(f"* {len(outer.folders[sel])} EXISTS")
                        self.w(f"{tag} OK [READ-WRITE] selected")
                    elif cmd == "UID":
                        sub, _, a2 = args.partition(" ")
                        sub = sub.upper()
                        box = outer.folders.get(sel, [])
                        if sub == "SEARCH":
                            ids = [str(m["uid"]) for m in box if "UNSEEN" not in a2.upper() or "\\Seen" not in m["flags"]]
                            self.w("* SEARCH " + " ".join(ids))
                            self.w(f"{tag} OK search done")
                        elif sub == "FETCH":
                            uid = a2.split(" ", 1)[0]
                            for i, m in enumerate(box, 1):
                                if str(m["uid"]) == uid:
                                    raw = m["raw"]
                                    fl = " ".join(sorted(m["flags"]))
                                    self.wfile.write(f"* {i} FETCH (UID {uid} FLAGS ({fl}) BODY[] {{{len(raw)}}}\r\n".encode())
                                    self.wfile.write(raw)
                                    self.wfile.write(b")\r\n")
                            self.w(f"{tag} OK fetch done")
                        elif sub == "STORE":
                            uid, op, fl = a2.split(" ", 2)
                            for m in box:
                                if str(m["uid"]) == uid:
                                    for f in re.findall(r"\\\w+", fl):
                                        (m["flags"].add if op.startswith("+") else m["flags"].discard)(f)
                            self.w(f"{tag} OK store done")
                        elif sub == "COPY":
                            uid, dest = a2.split(" ", 1)
                            dest = _mutf7_decode(dest.strip('"'))
                            if dest not in outer.folders:
                                self.w(f"{tag} NO no such folder")
                                continue
                            for m in box:
                                if str(m["uid"]) == uid:
                                    outer.next_uid += 1
                                    outer.folders[dest].append({"uid": outer.next_uid, "raw": m["raw"], "flags": set(m["flags"])})
                            self.w(f"{tag} OK copy done")
                    elif cmd == "EXPUNGE":
                        outer.folders[sel] = [m for m in outer.folders.get(sel, []) if "\\Deleted" not in m["flags"]]
                        self.w(f"{tag} OK expunged")
                    elif cmd == "APPEND":
                        m = re.match(r'"?([^"]+?)"? \(([^)]*)\) "[^"]*" \{(\d+)\}', args)
                        box, flags, n = _mutf7_decode(m.group(1)), m.group(2), int(m.group(3))
                        self.w("+ go ahead")
                        raw = self.rfile.read(n)
                        self.rfile.readline()
                        if box not in outer.folders:
                            self.w(f"{tag} NO no such folder")
                            continue
                        outer.next_uid += 1
                        outer.folders[box].append({"uid": outer.next_uid, "raw": raw, "flags": set(flags.split())})
                        self.w(f"{tag} OK appended")
                    elif cmd == "LOGOUT":
                        self.w("* BYE")
                        self.w(f"{tag} OK bye")
                        return
                    else:
                        self.w(f"{tag} BAD unknown {cmd}")

        self.server = _Server(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def add(self, folder, raw: bytes, seen=False):
        self.next_uid += 1
        self.folders.setdefault(folder, []).append({"uid": self.next_uid, "raw": raw, "flags": {"\\Seen"} if seen else set()})

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class FakeSMTP:
    def __init__(self):
        self.sent = []
        self.auth = []
        outer = self

        class H(socketserver.StreamRequestHandler):
            def w(self, s):
                self.wfile.write((s + "\r\n").encode())

            def handle(self):
                self.w("220 fake smtp")
                rcpt = []
                while True:
                    line = self.rfile.readline()
                    if not line:
                        return
                    cmd = line.decode("utf-8", "replace").strip()
                    up = cmd.upper()
                    if up.startswith("EHLO") or up.startswith("HELO"):
                        self.w("250-fake")
                        self.w("250 AUTH PLAIN LOGIN")
                    elif up.startswith("AUTH"):
                        outer.auth.append(cmd)
                        self.w("235 ok")
                    elif up.startswith("MAIL FROM"):
                        rcpt = []
                        self.w("250 ok")
                    elif up.startswith("RCPT TO"):
                        rcpt.append(cmd[8:].strip("<> "))
                        self.w("250 ok")
                    elif up == "DATA":
                        self.w("354 go")
                        data = b""
                        while True:
                            l2 = self.rfile.readline()
                            if l2 in (b".\r\n", b".\n", b""):
                                break
                            data += l2
                        outer.sent.append({"rcpt": rcpt, "data": data})
                        self.w("250 queued")
                    elif up == "QUIT":
                        self.w("221 bye")
                        return
                    else:
                        self.w("250 ok")

        self.server = _Server(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p

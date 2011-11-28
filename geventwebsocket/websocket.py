from gevent.coros import Semaphore
import struct
from codecs import utf_8_encode


class WebSocket(object):
    def __init__(self, sock, rfile, environ):
        self.rfile = rfile
        self.socket = sock
        self.origin = environ.get('HTTP_ORIGIN')
        self.protocol = environ.get('HTTP_SEC_WEBSOCKET_PROTOCOL', 'unknown')
        self.path = environ.get('PATH_INFO')
        self._writelock = Semaphore(1)

    def send(self, message):

        message = utf_8_encode(unicode(message, 'latin-1'))[0] 
        msglen = len(message)
        frameheader = 0x81
        maskbit = 0
        if msglen <= 125: masklen = chr(maskbit | msglen)
        elif msglen < (1 << 16): masklen = chr(maskbit | 126) + struct.pack('!H', msglen)
        elif msglen < (1 << 63): masklen = chr(maskbit | 127) + struct.pack('!Q', msglen)

        framebytes = chr(frameheader) + masklen + message
        with self._writelock:
            self.socket.sendall(framebytes)

    def fileno(self):
        return self.socket.fileno()

    def detach(self):
        self.socket = None
        self.rfile = None
        self.handler = None

    def close(self):
        # TODO implement graceful close with 0xFF frame
        if self.socket is not None:
            try:
                self.socket.close()
            except Exception:
                pass
            self.detach()


    def _extended_length(self,length):
        if length == 126:
            (length,) = struct.unpack("!H",self.rfile.read(2))
        elif length == 127:
            (length,) = struct.unpack("!Q",self.rfile.read(8))[0]
        return length

    def _read_until(self):
        bytes = []

        while True:
            byte = self.rfile.read(1)
            if ord(byte) != 0xff:
                bytes.append(byte)
            else:
                break

        return ''.join(bytes)

    def apply_mask(self,data,mask):
        output = ''
        for i,val in enumerate(data):
            off = i % 4
            output += chr(ord(mask[off]) ^ ord(val))

        return output


    def receive(self):
        if self.socket is not None:
            frame_str = self.rfile.read(1)
            if not frame_str:
                # Connection lost?
                self.close()
                return None
            else:
                frame_type = ord(frame_str)

            if (frame_type & 0x80) == 0x00: # most significant byte is not set, Old version
                if frame_type == 0x00:
                    buff = self._read_until()
                    return buff.decode("utf-8", "replace")
                else:
                    self.close()
            elif (frame_type & 0x80) == 0x80: # most significant byte is set, New version
                opcode = (frame_type & 0xF)
                maskandlength = ord(self.rfile.read(1))
                (mask,length) = (maskandlength >> 7), (maskandlength & 0x7F)
                if length > 125:
                    length = self._extended_length(length)
                if mask:
                    mask_value = self.rfile.read(4)

                if opcode == 1:
                    if length == 0:
                        self.close()
                        return None
                    if mask:
                        data = self.rfile.read(length)
                        return self.apply_mask(data,mask_value)
                    else:
                        return self.rfile.read(length) # discard the bytes

                elif opcode == 8:
                    data = self.rfile.read(length)
                    self.close()    
                else:
                    print "opcode was " + str(opcode)
                    self.close()
                    return None
            else:
                raise IOError("Reveiced an invalid message")
